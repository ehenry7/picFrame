import os
import shutil
import json
import subprocess
from pathlib import Path
import tempfile
import time
from platform_utils import get_cancel_flag_path

CANCEL_FLAG = get_cancel_flag_path()
TARGET_DIR = Path("static/photos/usb")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif"}

def is_image_file(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS

def find_and_mount_usb():
    """
    Find a USB device. If it is already mounted, return its mount point.
    Otherwise, mount it in a temporary directory and return that path.
    Return a tuple: (mount_path, device_path, was_mounted_by_script).
    """
    try:
        # Use lsblk for reliable detection and request the device path (PATH).
        result = subprocess.run(
            ['/usr/bin/lsblk', '-J', '-o', 'NAME,MOUNTPOINT,TRAN,PATH'],
            capture_output=True, text=True, check=True, timeout=10
        )
        data = json.loads(result.stdout)
        
        for device in data.get('blockdevices', []):
            if device.get('tran') == 'usb':
                # Iterate over the device partitions.
                for partition in device.get('children', []):
                    mountpoint = partition.get('mountpoint')
                    device_path = partition.get('path')

                    if not device_path:
                        continue

                    # Case 1: already mounted by the system.
                    if mountpoint:
                        print(f"USB device found and already mounted at: {mountpoint}")
                        return Path(mountpoint), device_path, False

                    # Case 2: not mounted; mount it here.
                    print(f"Unmounted USB device detected: {device_path}. Attempting to mount...")
                    
                    # Create a temporary mount directory.
                    temp_mount_dir = tempfile.mkdtemp(prefix="pictureframe_usb_")
                    
                    # Mount the device with sudo privileges.
                    mount_cmd = ['sudo', '-n', '/usr/bin/mount', device_path, temp_mount_dir]
                    subprocess.run(mount_cmd, check=True, capture_output=True, text=True, timeout=15)
                    
                    print(f"Device {device_path} successfully mounted at {temp_mount_dir}")
                    return Path(temp_mount_dir), device_path, True

    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        print(f"Error detecting USB devices via lsblk: {e}. Make sure 'lsblk' is installed.")
    
    return None, None, False # Return None if no device is found or an error occurs.

def import_usb_photos():
    """Import photos from a USB drive, mounting it if necessary."""
    yield {"type": "progress", "stage": "SEARCHING", "percent": 5, "message": "Searching for connected USB drives..."}
    time.sleep(1)
    
    mount_path = None
    device_path = None
    mounted_by_script = False

    try:
        mount_path, device_path, mounted_by_script = find_and_mount_usb()
        
        if not mount_path:
            yield {"type": "error", "message": "No USB drive detected. Check the connection and drive format (e.g. FAT32, exFAT)."}
            return

        yield {"type": "progress", "stage": "DETECTED", "percent": 10, "message": f"USB drive detected: {mount_path}"}

        # Clear the destination folders (source and prepared) before importing to avoid mixing files.
        prepared_usb_dir = Path("static/prepared/usb")
        if TARGET_DIR.exists():
            shutil.rmtree(TARGET_DIR)
        TARGET_DIR.mkdir(parents=True, exist_ok=True)
        if prepared_usb_dir.exists():
            shutil.rmtree(prepared_usb_dir)
        prepared_usb_dir.mkdir(parents=True, exist_ok=True)

        yield {"type": "progress", "stage": "SCANNING", "percent": 15, "message": "Scanning images on the USB drive..."}
        
        image_files = []
        for root, dirs, files in os.walk(mount_path):
            for filename in files:
                if is_image_file(filename):
                    image_files.append(Path(root) / filename)

        total = len(image_files)
        if total == 0:
            yield {"type": "error", "message": "No supported images found on the USB drive (supported formats: JPG, JPEG, PNG, GIF)."}
            return

        yield {"type": "stats", "stage": "STATS", "percent": 20, "message": f"{total} images found; starting import...", "total": total}

        for i, file_path in enumerate(image_files):
            # Check whether cancellation was requested.
            if CANCEL_FLAG.exists():
                yield {"type": "warning", "message": "Import cancelled by the user."}
                return

            try:
                dest_file = TARGET_DIR / file_path.name
                counter = 1
                original_dest = dest_file
                while dest_file.exists():
                    stem = original_dest.stem
                    suffix = original_dest.suffix
                    dest_file = TARGET_DIR / f"{stem}_{counter}{suffix}"
                    counter += 1
                
                shutil.copy2(file_path, dest_file)
                
                percent = 20 + int(((i + 1) / total) * 60)
                yield {
                    "type": "progress", "stage": "COPYING", "percent": percent,
                    "message": f"Copie en cours... ({i + 1}/{total})",
                    "current": i + 1, "total": total
                }
            except Exception as e:
                yield {"type": "warning", "message": f"Unable to copy {file_path.name}: {str(e)}"}

        yield {"type": "done", "stage": "IMPORT_COMPLETE", "percent": 80, "message": f"{total} photos imported.", "total_imported": total}

    finally:
        # Always run this section, even after an error, to clean up.
        if mounted_by_script and mount_path:
            yield {"type": "progress", "stage": "UNMOUNTING", "percent": 99, "message": "Unmounting USB drive..."}
            time.sleep(1)
            try:
                umount_cmd = ['sudo', '-n', '/usr/bin/umount', str(mount_path)]
                subprocess.run(umount_cmd, check=True, capture_output=True, text=True, timeout=15)
                print(f"Successfully unmounted {device_path}.")
                # Remove the temporary mount directory.
                shutil.rmtree(mount_path)
                print(f"Temporary mount directory {mount_path} removed.")
            except Exception as e:
                yield {"type": "warning", "message": f"Warning: Unable to safely unmount the USB drive: {e}"}