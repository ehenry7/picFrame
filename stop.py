"""PictureFrame process stopper.

Usage:
    python stop.py            # graceful stop (SIGTERM, then SIGKILL after 5s)
    python stop.py --force    # immediate SIGKILL
    python stop.py --dry-run  # list what would be killed without killing
"""

import os
import sys
import time
import tempfile
from pathlib import Path

try:
    import psutil
except ImportError:
    print("ERROR: psutil is required. Install it with: pip install psutil")
    sys.exit(1)

APP_PORT = 7090

TARGET_SCRIPTS = [
    "app.py",
    "local_slideshow.py",
    "background_updater.py",
    "utils/display_message.py",
    "utils/render_pipeline.py",
    "utils/wallpaper_manager.py",
]

PID_FILES = [
    "pictureframe_slideshow.pid",
    "pictureframe_background.pid",
]

LOCK_FILES = [
    "pictureframe_app.lock",
]

STATUS_FILES = [
    "pictureframe_slideshow_status",
    "pictureframe_current_photo",
]


def find_pictureframe_processes():
    found = []
    for proc in psutil.process_iter(attrs=["pid", "cmdline", "name", "status"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cmdline_str = " ".join(cmdline)
            proc_name = proc.info.get("name", "")
            if any(script in cmdline_str for script in TARGET_SCRIPTS):
                found.append(proc)
                continue
            if proc_name and "ffmpeg" in proc_name.lower():
                found.append(proc)
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr.port == APP_PORT and conn.status == "LISTEN":
                try:
                    proc = psutil.Process(conn.pid)
                    if not any(p.pid == proc.pid for p in found):
                        found.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        pass
    return found


def kill_process(proc, force=False, dry_run=False):
    try:
        if not proc.is_running():
            return True
        pid = proc.pid
        name = proc.name()
        if dry_run:
            cmdline = " ".join(proc.cmdline() or [])
            print(f"  [DRY-RUN] Would kill PID {pid} ({name}): {cmdline[:120]}")
            return True
        if force:
            print(f"  KILL  PID {pid} ({name})")
            proc.kill()
        else:
            print(f"  TERM  PID {pid} ({name})")
            proc.terminate()
        return True
    except psutil.NoSuchProcess:
        return True
    except psutil.AccessDenied:
        print(f"  DENIED PID {proc.pid} -- access denied")
        return False
    except Exception as e:
        print(f"  ERROR PID {proc.pid} -- {e}")
        return False


def wait_for_death(procs, timeout=5):
    deadline = time.time() + timeout
    survivors = []
    for proc in procs:
        try:
            proc.wait(timeout=max(0.1, deadline - time.time()))
        except psutil.TimeoutExpired:
            survivors.append(proc)
        except psutil.NoSuchProcess:
            pass
    return survivors


def cleanup_files():
    temp_dir = Path(tempfile.gettempdir())
    for name in PID_FILES + LOCK_FILES + STATUS_FILES:
        fpath = temp_dir / name
        if fpath.exists():
            try:
                fpath.unlink()
                print(f"  Removed {fpath}")
            except OSError as e:
                print(f"  Could not remove {fpath}: {e}")


def main():
    force = "--force" in sys.argv or "-f" in sys.argv
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    if dry_run:
        print("=== DRY RUN -- no processes will be killed ===\n")
    elif force:
        print("=== FORCE STOP -- immediate SIGKILL ===\n")
    else:
        print("=== GRACEFUL STOP -- SIGTERM with 5s grace period ===\n")

    print("Finding PictureFrame processes...")
    procs = find_pictureframe_processes()

    if not procs:
        print("  No PictureFrame processes found.")
    else:
        print(f"  Found {len(procs)} process(es):\n")
        for p in procs:
            try:
                cmdline_str = " ".join(p.cmdline() or [])[:100]
                print(f"    PID {p.pid:>7}  {p.name():<20}  {cmdline_str}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                print(f"    PID {p.pid:>7}  (details unavailable)")

        print("\nStopping processes...")
        for proc in procs:
            kill_process(proc, force=force, dry_run=dry_run)

        if not dry_run and not force:
            print("\nWaiting up to 5 seconds for graceful exit...")
            survivors = wait_for_death(procs, timeout=5)
            if survivors:
                print(f"\n  {len(survivors)} process(es) did not exit -- force killing...")
                for proc in survivors:
                    kill_process(proc, force=True)

        if not dry_run:
            time.sleep(0.5)
            still_alive = []
            for proc in procs:
                try:
                    if proc.is_running():
                        still_alive.append(proc)
                except psutil.NoSuchProcess:
                    pass
            if still_alive:
                print(f"\n  WARNING: {len(still_alive)} process(es) still alive:")
                for p in still_alive:
                    try:
                        print(f"    PID {p.pid} ({p.name()})")
                    except psutil.NoSuchProcess:
                        pass
            else:
                print("\n  All processes stopped successfully.")

    if not dry_run:
        print("\nCleaning up PID and lock files...")
        cleanup_files()

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())