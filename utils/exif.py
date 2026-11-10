from PIL import Image, ExifTags
from datetime import datetime

def get_rotation_angle(image):
    try:
        exif = image._getexif()
        if not exif:
            return 0

        for tag, value in exif.items():
            decoded = ExifTags.TAGS.get(tag, tag)
            if decoded == "Orientation":
                if value == 3:
                    return 180
                elif value == 6:
                    return 270
                elif value == 8:
                    return 90
        return 0
    except Exception as e:
        print(f"Error reading EXIF data: {e}")
        return 0
        
        
        
# Sigalou change 2026-01-25: added photo capture date extraction.
def get_photo_date(image):
    """
    Get the image capture date.
    Priority order:
    1. DateTimeOriginal (capture date)
    2. DateTimeDigitized (digitization date)
    3. DateTime (modification date)
    
    Returns a datetime object, or None if no date is found.
    """
    try:
        exif = image._getexif()
        if not exif:
            return None

        # EXIF date tags, in priority order.
        date_tags = ["DateTimeOriginal", "DateTimeDigitized", "DateTime"]
        
        for tag, value in exif.items():
            decoded = ExifTags.TAGS.get(tag, tag)
            if decoded in date_tags:
                # Format EXIF standard: "YYYY:MM:DD HH:MM:SS"
                try:
                    photo_date = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                    return photo_date
                except ValueError:
                    # If the format differs, continue with the next tag.
                    continue
        
        return None
    except Exception as e:
        print(f"Error reading the EXIF date: {e}")
        return None

def get_photo_date_formatted(image, format="%d/%m/%Y"):
    """
    Get the formatted capture date.
    
    Args:
        image: Image PIL
        format: Output format (default: DD/MM/YYYY)
    
    Returns the formatted string, or None.
    """
    photo_date = get_photo_date(image)
    if photo_date:
        return photo_date.strftime(format)
    return None
# End of Sigalou change 2026-01-25.
