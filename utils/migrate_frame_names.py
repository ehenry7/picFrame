"""Migrate deployment filenames from installations predating PictureFrame."""

import argparse
from pathlib import Path


def migrate_frame_names(system_root, user_home):
    root = Path(system_root)
    home = Path(user_home)
    renames = (
        ("etc/nginx/sites-available/pimmich", "etc/nginx/sites-available/pictureframe"),
        ("etc/sudoers.d/pimmich-auth", "etc/sudoers.d/pictureframe-auth"),
    )
    for old_name, new_name in renames:
        old, new = root / old_name, root / new_name
        if old.exists():
            if new.exists():
                if old.read_bytes() != new.read_bytes():
                    raise RuntimeError(f"Conflicting deployment files: {old} and {new}")
                old.unlink()
            else:
                old.rename(new)
    old_site = root / "etc/nginx/sites-enabled/pimmich"
    new_site = root / "etc/nginx/sites-enabled/pictureframe"
    if old_site.is_symlink():
        old_site.unlink()
    elif old_site.exists():
        if new_site.exists() and old_site.read_bytes() != new_site.read_bytes():
            raise RuntimeError(f"Conflicting deployment files: {old_site} and {new_site}")
        if not new_site.exists():
            old_site.rename(new_site)
        else:
            old_site.unlink()
    sway_config = home / ".config" / "sway" / "config"
    if sway_config.exists():
        source = sway_config.read_text(encoding="utf-8")
        updated = source.replace("start_pimmich.sh", "start_pictureframe.sh")
        if source != updated:
            sway_config.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-home", required=True, type=Path)
    args = parser.parse_args()
    if not args.user_home.is_absolute() or not args.user_home.is_dir():
        parser.error("--user-home must be an existing absolute directory")
    migrate_frame_names(Path("/"), args.user_home)
