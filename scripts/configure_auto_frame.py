"""Install or repair the current user's console-to-Sway frame launcher."""

import argparse
import os
from pathlib import Path
import re
import shlex


def configure_auto_frame(project, home):
    project, home = Path(project).resolve(), Path(home)
    launcher = project / "start_pictureframe.sh"
    if not launcher.is_file():
        raise FileNotFoundError(f"PictureFrame startup script not found: {launcher}")
    profile = home / ".bash_profile"
    source = profile.read_text(encoding="utf-8") if profile.exists() else ""
    if not re.search(r"^\s*exec\s+sway\s*$", source, re.MULTILINE):
        source += ('\nif [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] '
                   '&& [ "$(tty)" = /dev/tty1 ]; then\n  exec sway\nfi\n')
        profile.write_text(source, encoding="utf-8")
    config = home / ".config" / "sway" / "config"
    config.parent.mkdir(parents=True, exist_ok=True)
    source = config.read_text(encoding="utf-8") if config.exists() else ""
    lines = [line for line in source.splitlines()
             if not (re.match(r"^\s*exec(?:_always)?\s", line)
                     and re.search(r"start_(?:pimmich|pictureframe)\.sh", line))]
    command = shlex.quote(f"exec bash {shlex.quote(str(launcher))}")
    lines.append(f"exec --no-startup-id {command}")
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    args = parser.parse_args()
    if not args.home.is_dir():
        parser.error("The user home directory does not exist")
    configure_auto_frame(Path(__file__).resolve().parents[1], args.home)
    print("PictureFrame console and Sway launchers configured.")
