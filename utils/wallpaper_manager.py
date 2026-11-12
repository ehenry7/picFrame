"""Desktop wallpaper backend for PictureFrame's background updater mode.

This module applies a single image file as the desktop wallpaper on **all
monitors** of the current machine, and reports the monitor layout so callers
can render at an appropriate resolution.

Platform support
----------------
- Windows: ``SystemParametersInfoW`` (SPI_SETDESKWALLPAPER) via ctypes. The
  wallpaper style is also set to "Fit" so photos are never distorted on
  differently sized monitors.
- Linux: desktop-environment specific commands, detected via
  ``XDG_CURRENT_DESKTOP`` / ``DESKTOP_SESSION``:
    - GNOME/Ubuntu: ``gsettings`` (``picture-uri`` + ``picture-uri-dark``)
    - MATE:         ``gsettings`` (``picture-filename``)
    - Cinnamon:     ``gsettings`` (``picture-uri``)
    - KDE Plasma:   ``plasma-apply-wallpaper``
    - XFCE:         ``xfconf-query`` (every monitor property is set)
    - X11 fallback: ``feh --bg-fill`` when available

Contract (mirrors platform_utils): every function is safe to call on any OS,
never raises, and reports unavailability with a ``False``/empty return value
and a log line — never by pretending an unsupported operation succeeded.
"""

import logging
import os
import subprocess
from pathlib import Path

from platform_utils import IS_LINUX, IS_WINDOWS

logger = logging.getLogger("pictureframe.wallpaper_manager")

# Windows: SPI_SETDESKWALLPAPER action for SystemParametersInfoW.
_SPI_SETDESKWALLPAPER = 20
# SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
_SPIF_UPDATEINIFILE = 0x01
_SPIF_SENDCHANGE = 0x02

# ── Windows COM interface for per-monitor wallpaper ──────────────

# Lazily initialised COM IDesktopWallpaper instance.  Created on first use
# and cached for the process lifetime.
_desktop_wallpaper_com = None


def _init_desktop_wallpaper_com():
    """Create and cache an IDesktopWallpaper COM instance.

    Returns None when comtypes is unavailable or COM initialisation fails.
    """
    global _desktop_wallpaper_com
    if _desktop_wallpaper_com is not None:
        return _desktop_wallpaper_com
    try:
        import ctypes
        import ctypes.wintypes
        import comtypes
        from comtypes import GUID, HRESULT, IUnknown, POINTER

        CLSID_DesktopWallpaper = GUID("{C2CF3110-460E-4fc1-B9D0-8A1C0C9CC4BD}")
        IID_IDesktopWallpaper = GUID("{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}")

        class IDesktopWallpaper(IUnknown):
            _iid_ = IID_IDesktopWallpaper
            _methods_ = [
                comtypes.COMMETHOD([], HRESULT, "SetWallpaper",
                    (["in"], ctypes.c_wchar_p, "monitorID"),
                    (["in"], ctypes.c_wchar_p, "wallpaper")),
                comtypes.COMMETHOD([], HRESULT, "GetWallpaper",
                    (["in"], ctypes.c_wchar_p, "monitorID"),
                    (["out"], POINTER(ctypes.c_wchar_p), "wallpaper")),
                comtypes.COMMETHOD([], HRESULT, "GetMonitorDevicePathAt",
                    (["in"], ctypes.wintypes.UINT, "monitorIndex"),
                    (["out"], POINTER(ctypes.c_wchar_p), "monitorID")),
                comtypes.COMMETHOD([], HRESULT, "GetMonitorDevicePathCount",
                    (["out"], POINTER(ctypes.wintypes.UINT), "count")),
                comtypes.COMMETHOD([], HRESULT, "GetMonitorRECT",
                    (["in"], ctypes.c_wchar_p, "monitorID"),
                    (["out"], POINTER(ctypes.wintypes.RECT), "displayRect")),
                comtypes.COMMETHOD([], HRESULT, "SetPosition",
                    (["in"], ctypes.c_int, "position")),
                comtypes.COMMETHOD([], HRESULT, "GetPosition",
                    (["out"], POINTER(ctypes.c_int), "position")),
            ]

        _desktop_wallpaper_com = comtypes.CoCreateInstance(
            CLSID_DesktopWallpaper, IDesktopWallpaper, comtypes.CLSCTX_ALL)
    except Exception as exc:
        logger.debug("IDesktopWallpaper COM init failed: %s", exc)
        _desktop_wallpaper_com = False  # sentinel: tried and failed
    return _desktop_wallpaper_com if _desktop_wallpaper_com is not False else None


# ── Environment detection ───────────────────────────────────────


def desktop_environment() -> str:
    """Return a short lower-case desktop environment identifier.

    Returns 'gnome', 'mate', 'cinnamon', 'kde', 'xfce' or '' when unknown.
    Always returns '' on Windows.
    """
    if IS_WINDOWS or not IS_LINUX:
        return ""
    raw = " ".join((
        os.environ.get("XDG_CURRENT_DESKTOP", ""),
        os.environ.get("DESKTOP_SESSION", ""),
        os.environ.get("GDMSESSION", ""),
    )).lower()
    for key in ("gnome", "mate", "cinnamon", "kde", "plasma", "xfce"):
        if key in raw:
            if key == "plasma":
                return "kde"
            return key
    return ""


def _run(command, timeout=10):
    """Run a command, return True on success (logging failures)."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("Command failed: %s (%s)", command, exc)
        return False
    if result.returncode != 0:
        logger.debug("Command failed (%d): %s — %s",
                     result.returncode, command, (result.stderr or "").strip())
        return False
    return True


# ── Monitor detection ───────────────────────────────────────────


def _windows_monitors():
    """Return [(width, height), ...] for all monitors via ctypes.

    Also caches the per-monitor work-area rects (in the module-level
    ``_windows_monitor_info`` list) so that :func:`max_taskbar_inset`
    can compute how much of the bottom is reserved by the taskbar on
    each monitor — accounting for per-monitor DPI scaling.
    """
    try:
        import ctypes
        import ctypes.wintypes

        # Report true pixel dimensions, not DPI-scaled ones, so wallpapers
        # are rendered at the monitor's real resolution. Harmless if the
        # process is already DPI-aware.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        monitors = []
        info_list = []
        user32 = ctypes.windll.user32

        monitor_enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.wintypes.HMONITOR, ctypes.wintypes.HDC,
            ctypes.wintypes.LPRECT, ctypes.wintypes.LPARAM)

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT),
                ("dwFlags", ctypes.wintypes.DWORD),
            ]

        def _callback(hMonitor, _hdc, _rect, _lparam):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hMonitor, ctypes.byref(info)):
                rect = info.rcMonitor
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width > 0 and height > 0:
                    monitors.append((width, height))
                    work = info.rcWork
                    info_list.append({
                        "monitor": (width, height),
                        "work": (work.right - work.left,
                                 work.bottom - work.top),
                    })
            return 1  # continue enumeration

        # NOTE: ctypes.wintypes has no LPCRECT; the clip rectangle is
        # declared as LPRECT (a plain RECT pointer) in argtypes.
        user32.EnumDisplayMonitors.argtypes = [
            ctypes.wintypes.HDC, ctypes.wintypes.LPRECT,
            monitor_enum_proc, ctypes.wintypes.LPARAM]
        if user32.EnumDisplayMonitors(None, None, monitor_enum_proc(_callback), 0):
            globals()["_windows_monitor_info"] = info_list
            return monitors
    except Exception as exc:  # pragma: no cover - depends on windowing API
        logger.debug("Windows monitor enumeration failed: %s", exc)
    return []


def _windows_work_area():
    """Return the primary monitor's work-area (width, height) on Windows.

    Kept for backward compatibility; prefer :func:`max_taskbar_inset` which
    examines every monitor and accounts for per-monitor DPI scaling.
    """
    try:
        import ctypes
        import ctypes.wintypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        # SPI_GETWORKAREA retrieves the work area of the primary monitor.
        work_rect = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(work_rect), 0):
            width = work_rect.right - work_rect.left
            height = work_rect.bottom - work_rect.top
            if width > 0 and height > 0:
                return (width, height)
    except Exception as exc:
        logger.debug("Windows work area query failed: %s", exc)
    return None


def max_taskbar_inset(config=None):
    """Return the largest taskbar height (in physical pixels) across monitors.

    Windows applies one wallpaper file to every monitor, so overlays must
    clear the taskbar on **all** of them.  Monitors with different DPI
    scaling have different physical taskbar heights — the returned value is
    the maximum, ensuring overlays are above the taskbar on every screen.

    Returns 0 on non-Windows platforms or when the API is unavailable.
    """
    if not IS_WINDOWS:
        return 0
    # Ensure _windows_monitors has been called so the info cache is populated.
    get_monitors(config)
    info_list = globals().get("_windows_monitor_info") or []
    max_inset = 0
    for entry in info_list:
        mon_w, mon_h = entry["monitor"]
        work_w, work_h = entry["work"]
        inset = mon_h - work_h
        if inset > max_inset:
            max_inset = inset
    return max_inset


def get_monitor_details(config=None):
    """Return per-monitor details for wallpaper rendering.

    Each entry is a dict:
        ``{"id": str, "width": int, "height": int, "taskbar_inset": int}``

    On Windows, uses the IDesktopWallpaper COM API to enumerate real
    monitors (filtering out ghost entries) and GetMonitorInfoW for
    per-monitor work areas.  On Linux or when COM is unavailable, returns
    a single entry covering the largest monitor with a 0 inset.
    """
    if not IS_WINDOWS:
        w, h = largest_monitor_size(config)
        return [{"id": None, "width": w, "height": h, "taskbar_inset": 0}]

    dw = _init_desktop_wallpaper_com()
    if dw is None:
        # Fallback: no COM, use the old single-image approach.
        w, h = largest_monitor_size(config)
        return [{"id": None, "width": w, "height": h,
                 "taskbar_inset": max_taskbar_inset(config)}]

    try:
        count = dw.GetMonitorDevicePathCount()
        details = []
        for i in range(count):
            monitor_id = dw.GetMonitorDevicePathAt(i)
            if not monitor_id:
                continue  # ghost entry
            try:
                rect = dw.GetMonitorRECT(monitor_id)
            except Exception:
                continue  # can't get rect, skip
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w <= 0 or h <= 0:
                continue

            # Get the work area for this specific monitor to compute the
            # taskbar inset (physical pixels, DPI-aware).
            taskbar_inset = _monitor_taskbar_inset(
                int(rect.left), int(rect.top),
                int(rect.right), int(rect.bottom))

            details.append({
                "id": monitor_id,
                "width": w,
                "height": h,
                "taskbar_inset": taskbar_inset,
            })
        if details:
            return details
    except Exception as exc:
        logger.debug("COM monitor enumeration failed: %s", exc)

    # Fallback
    w, h = largest_monitor_size(config)
    return [{"id": None, "width": w, "height": h,
             "taskbar_inset": max_taskbar_inset(config)}]


def _monitor_taskbar_inset(left, top, right, bottom):
    """Return the taskbar height (physical px) for the monitor at the
    given virtual-screen coordinates.

    Uses EnumDisplayMonitors + GetMonitorInfoW to find the work area
    that matches the given monitor rect.
    """
    try:
        import ctypes
        import ctypes.wintypes

        # Ensure DPI awareness so rects are in physical pixels.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        user32 = ctypes.windll.user32
        best_inset = 0

        class MONITORINFOEX(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("szDevice", ctypes.c_wchar * 32),
            ]

        def _callback(hMonitor, _hdc, rect_ptr, _lparam):
            nonlocal best_inset
            info = MONITORINFOEX()
            info.cbSize = ctypes.sizeof(MONITORINFOEX)
            if user32.GetMonitorInfoW(hMonitor, ctypes.byref(info)):
                mr = info.rcMonitor
                if (int(mr.left) == left and int(mr.top) == top and
                        int(mr.right) == right and int(mr.bottom) == bottom):
                    work = info.rcWork
                    inset = int(mr.bottom) - int(mr.top) - (int(work.bottom) - int(work.top))
                    if inset > best_inset:
                        best_inset = inset
            return 1

        monitor_enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.wintypes.HMONITOR, ctypes.wintypes.HDC,
            ctypes.wintypes.LPRECT, ctypes.wintypes.LPARAM)
        user32.EnumDisplayMonitors(None, None, monitor_enum_proc(_callback), 0)
        return best_inset
    except Exception as exc:
        logger.debug("Per-monitor taskbar inset failed: %s", exc)
        return 0


def set_wallpaper_per_monitor(monitor_images):
    """Set a different wallpaper image on each monitor.

    Args:
        monitor_images: list of (monitor_id, image_path) tuples.
            monitor_id is the IDesktopWallpaper monitor ID string, or None
            to use the legacy single-image SystemParametersInfoW path.

    Returns True if all monitors were set, False on any failure.
    """
    all_ok = True
    used_com = False
    for monitor_id, image_path in monitor_images:
        if monitor_id is None:
            # Legacy path (no COM per-monitor support)
            if not _windows_set_wallpaper(image_path):
                all_ok = False
        else:
            dw = _init_desktop_wallpaper_com()
            if dw is None:
                if not _windows_set_wallpaper(image_path):
                    all_ok = False
            else:
                try:
                    if not used_com:
                        # Set position to "Stretch" (DWPOS_STRETCH=2) so the
                        # image is mapped 1:1 to the monitor when rendered at
                        # native resolution.  We pre-render at each monitor's
                        # exact pixel dimensions, so no cropping or fitting
                        # is needed from the OS.
                        try:
                            dw.SetPosition(2)
                        except Exception:
                            pass
                        used_com = True
                    dw.SetWallpaper(monitor_id, str(image_path))
                except Exception as exc:
                    logger.debug("SetWallpaper failed for %s: %s",
                                 monitor_id, exc)
                    all_ok = False
    return all_ok


def _linux_monitors():
    """Return [(width, height), ...] by parsing xrandr, largest first."""
    try:
        result = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True,
            timeout=10, check=False)
        if result.returncode == 0:
            monitors = []
            for line in result.stdout.splitlines():
                line = line.strip()
                # e.g. "HDMI-1 connected primary 1920x1080+0+0"
                if " connected" in line:
                    parts = line.split()
                    for part in parts:
                        if "x" in part and part.replace("+", "").replace("x", "").isdigit():
                            try:
                                w, h = part.split("x")[0], part.split("x")[1].split("+")[0]
                                monitors.append((int(w), int(h)))
                            except (ValueError, IndexError):
                                continue
            return monitors
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("xrandr query failed: %s", exc)
    return []


def get_monitors(config=None):
    """Return a non-empty list of (width, height) tuples.

    Resolution order: OS monitor enumeration → config ``display_width`` /
    ``display_height`` → (1920, 1080) fallback. Callers may additionally sort
    with :func:`largest_monitor_size` to pick a render target.
    """
    monitors = _windows_monitors() if IS_WINDOWS else _linux_monitors() if IS_LINUX else []
    if monitors:
        return monitors

    if config:
        width = int(config.get("display_width", 0) or 0)
        height = int(config.get("display_height", 0) or 0)
        if width > 0 and height > 0:
            return [(width, height)]
    return [(1920, 1080)]


def largest_monitor_size(config=None):
    """Return the (width, height) of the largest monitor by pixel count."""
    monitors = get_monitors(config)
    return max(monitors, key=lambda wh: wh[0] * wh[1])


def wallpaper_render_size(config=None):
    """Return the (width, height) to render the wallpaper at.

    Always returns the full largest monitor size.  Overlay positioning
    (weather, tides) is adjusted separately via :func:`max_taskbar_inset`
    so that bottom-anchored elements sit above the taskbar without
    shrinking the photo.
    """
    return largest_monitor_size(config)


# ── Windows wallpaper setters ───────────────────────────────────


def _windows_set_wallpaper(image_path):
    try:
        import ctypes
        import winreg

        # "Fill" style (WallpaperStyle=10): scale to cover the screen,
        # center-cropping excess.  This avoids letterbox black bars that
        # would shift overlays upward on monitors with a different aspect
        # ratio than the render resolution.  Combined with bottom_inset
        # in draw_overlay, overlays sit just above the taskbar on every
        # monitor regardless of DPI scaling.
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Control Panel\Desktop",
                                0, winreg.KEY_SET_VALUE) as key:
                for name, value in (("WallpaperStyle", "10"),
                                    ("TileWallpaper", "0")):
                    try:
                        current, _ = winreg.QueryValueEx(key, name)
                    except OSError:
                        current = None
                    if current != value:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        except OSError as exc:
            logger.debug("Could not set WallpaperStyle: %s", exc)

        result = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_SETDESKWALLPAPER, 0, str(image_path),
            _SPIF_UPDATEINIFILE | _SPIF_SENDCHANGE)
        if result:
            return True
        logger.debug("SystemParametersInfoW returned %d", result)
    except Exception as exc:  # pragma: no cover - depends on windowing API
        logger.debug("Windows wallpaper API failed: %s", exc)
    return False


# ── Linux wallpaper setters ─────────────────────────────────────


def _gsettings(schema, key, value):
    return _run(["gsettings", "set", schema, key, value])


def _linux_set_wallpaper(image_path):
    de = desktop_environment()
    uri = Path(image_path).resolve().as_uri()

    if de == "gnome":
        ok = (_gsettings("org.gnome.desktop.background", "picture-uri", uri)
              and _gsettings("org.gnome.desktop.background",
                             "picture-uri-dark", uri))
        if ok:
            _gsettings("org.gnome.desktop.background", "picture-options", "zoom")
        return ok
    if de == "mate":
        return _gsettings("org.mate.background",
                          "picture-filename", str(image_path))
    if de == "cinnamon":
        return _gsettings("org.cinnamon.desktop.background", "picture-uri", uri)
    if de == "kde":
        # plasma-apply-wallpaper applies to every screen/containment.
        return _run(["plasma-apply-wallpaper", str(image_path)])
    if de == "xfce":
        return _xfce_set_wallpaper(image_path)

    # Last-resort X11 fallback.
    if _run(["which", "feh"]):
        if _run(["feh", "--bg-fill", str(image_path)]):
            return True
    logger.warning("No supported desktop environment detected; "
                   "cannot set the wallpaper")
    return False


def _xfce_set_wallpaper(image_path):
    """Set the wallpaper on every XFCE monitor/workspace property."""
    try:
        result = subprocess.run(
            ["xfconf-query", "-c", "xfce4-desktop", "-l"],
            capture_output=True, text=True, timeout=10, check=False)
        if result.returncode != 0:
            return False
        properties = [p for p in result.stdout.splitlines()
                      if p.endswith("last-image")]
        if not properties:
            logger.debug("No XFCE backdrop properties found")
            return False
        return all(
            _run(["xfconf-query", "-c", "xfce4-desktop",
                  "-p", prop, "-s", str(image_path)])
            for prop in properties
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("xfconf-query failed: %s", exc)
    return False


# ── Public API ──────────────────────────────────────────────────


def set_wallpaper(image_path):
    """Apply ``image_path`` as the wallpaper on all monitors.

    Args:
        image_path: absolute path to an image file on local disk.

    Returns:
        True when the wallpaper was applied, False otherwise (including on
        unsupported platforms). Never raises.
    """
    path = Path(image_path)
    if not path.is_absolute():
        path = path.resolve()
    if not path.is_file():
        logger.warning("Wallpaper file does not exist: %s", path)
        return False

    if IS_WINDOWS:
        return _windows_set_wallpaper(str(path))
    if IS_LINUX:
        return _linux_set_wallpaper(str(path))
    logger.warning("Setting the wallpaper is not supported on this platform")
    return False
