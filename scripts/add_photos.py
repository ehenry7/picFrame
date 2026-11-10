"""Import a folder into the Smartphone photo source and prepare it for display."""

import argparse
import os
import shutil
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from utils.photo_import import PHOTO_EXTENSIONS, photo_digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "folder", nargs="?", type=Path,
        help="Folder containing photos (default: static/photos/smartphone). "
             "Only files directly inside this folder are imported.",
    )
    args = parser.parse_args()
    source = (args.folder if args.folder is not None else
              PROJECT_DIR / "static" / "photos" / "smartphone").resolve()
    destination = PROJECT_DIR / "static" / "photos" / "smartphone"

    try:
        if not source.is_dir():
            raise ValueError(f"Photo folder does not exist: {source}")
        photos = sorted(
            (path for path in source.iterdir()
             if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS),
            key=lambda path: path.name.casefold(),
        )
        if not photos:
            raise ValueError(f"No supported photos found in {source}")

        os.chdir(PROJECT_DIR)
        from utils.config_manager import load_config, save_config
        from utils.prepare_all_photos import prepare_all_photos_with_progress

        destination.mkdir(parents=True, exist_ok=True)
        if source != destination.resolve():
            used_stems = {path.stem.casefold() for path in destination.iterdir()}
            existing_digests = {
                photo_digest(path) for path in destination.iterdir()
                if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS
            }
            for photo in photos:
                digest = photo_digest(photo)
                if digest in existing_digests:
                    print(f"Skipped existing photo: {photo.name}", flush=True)
                    continue
                target = destination / photo.name
                suffix = 1
                while target.stem.casefold() in used_stems:
                    target = destination / f"{photo.stem}_{suffix}{photo.suffix}"
                    suffix += 1
                shutil.copy2(photo, target)
                used_stems.add(target.stem.casefold())
                existing_digests.add(digest)
                print(f"Copied: {photo.name} -> {target.name}", flush=True)

        source_photos = [
            path for path in destination.iterdir()
            if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS
        ]
        stems = [path.stem.casefold() for path in source_photos]
        if len(stems) != len(set(stems)):
            raise ValueError(
                "Some Smartphone photos have the same name without the extension. "
                "Rename them so each photo has a unique name, then run again."
            )

        config = load_config()
        completed = False
        failed = False
        for update in prepare_all_photos_with_progress(
            screen_width=config["display_width"],
            screen_height=config["display_height"],
            source_type="smartphone",
        ):
            print(update["message"], flush=True)
            if update["type"] in {"error", "warning"}:
                failed = True
            if update["type"] == "done":
                completed = True

        prepared = PROJECT_DIR / "static" / "prepared" / "smartphone"
        missing = [
            photo.name for photo in source_photos
            if not (prepared / f"{photo.stem}.jpg").is_file()
            or (prepared / f"{photo.stem}.jpg").stat().st_size == 0
        ]
        if missing:
            raise ValueError("Preparation produced no image for: " + ", ".join(missing))
        if failed or not completed:
            raise ValueError("Preparation failed or was cancelled. Source settings were not changed.")

        config = load_config()
        sources = config.setdefault("display_sources", [])
        if "smartphone" not in sources:
            sources.append("smartphone")
        save_config(config)
    except (OSError, ValueError, ImportError) as error:
        print(f"Could not add photos: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nPhoto import cancelled.", file=sys.stderr)
        return 1

    print("Photos prepared and Smartphone source enabled. Restart the slideshow to load them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
