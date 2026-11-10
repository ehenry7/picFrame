import os
import shutil
from pathlib import Path
from PIL import Image, ImageEnhance, ImageOps, ImageFilter, ImageDraw, ImageFont, ImageChops
import random
import piexif
import json
from datetime import date
from utils.migrate_frame_names import LEGACY_BBOX_PREFIX

POLAROID_FONT_PATH = Path(__file__).parent.parent / "static" / "fonts" / "Caveat-Regular.ttf"
# Path to the cache of user-entered text.
USER_TEXT_MAP_CACHE_FILE = Path(__file__).parent.parent / "cache" / "user_texts.json"

def _load_user_texts():
    """Load the user text dictionary from the cache."""
    if not USER_TEXT_MAP_CACHE_FILE.exists():
        return {}
    try:
        with open(USER_TEXT_MAP_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def _save_user_texts(texts_map):
    """Save the user text dictionary to the cache."""
    USER_TEXT_MAP_CACHE_FILE.parent.mkdir(exist_ok=True)
    with open(USER_TEXT_MAP_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(texts_map, f, indent=2, ensure_ascii=False)

def _get_content_bbox(image_with_exif):
    """Read EXIF metadata to find the content bounding box."""
    try:
        exif_dict = piexif.load(image_with_exif.info.get('exif', b''))
        user_comment_bytes = exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment, b'')
        user_comment = user_comment_bytes.decode('ascii', errors='ignore')
        
        if user_comment.startswith(("pictureframe_bbox:", LEGACY_BBOX_PREFIX)):
            coords_str = user_comment.split(":")[1]
            x, y, w, h = map(int, coords_str.split(','))
            return (x, y, x + w, y + h) # Retourne un tuple (left, top, right, bottom)
    except Exception:
        pass # Si erreur de lecture ou format invalide, on retourne None
    return None

def _draw_rounded_rectangle(draw, xy, corner_radius, fill=None):
    """
    Dessine un rectangle avec des coins arrondis.
    """
    x1, y1, x2, y2 = xy
    # Rectangle body.
    draw.rectangle((x1 + corner_radius, y1, x2 - corner_radius, y2), fill=fill)
    draw.rectangle((x1, y1 + corner_radius, x2, y2 - corner_radius), fill=fill)
    # Rounded corners.
    draw.pieslice((x1, y1, x1 + corner_radius * 2, y1 + corner_radius * 2), 180, 270, fill=fill)
    draw.pieslice((x2 - corner_radius * 2, y1, x2, y1 + corner_radius * 2), 270, 360, fill=fill)
    draw.pieslice((x1, y2 - corner_radius * 2, x1 + corner_radius * 2, y2), 90, 180, fill=fill)
    draw.pieslice((x2 - corner_radius * 2, y2 - corner_radius * 2, x2, y2), 0, 90, fill=fill)

def add_stamp_and_postmark(card_image):
    """
    Add a random stamp and postmark to a postcard image.
    Take a PIL image (the postcard) and return the modified postcard.
    """
    try:
        stamps_dir = Path('static/stamps')
        if not stamps_dir.is_dir():
            print("[Stamp] The 'static/stamps' directory does not exist.")
            return card_image

        stamps = [f for f in stamps_dir.iterdir() if f.suffix.lower() == '.png']
        if not stamps:
            print("[Stamp] No stamp (.png) files found in 'static/stamps'.")
            return card_image

        postcard = card_image.copy()
        random_stamp_path = random.choice(stamps)
        stamp = Image.open(random_stamp_path).convert("RGBA")

        stamp.thumbnail((160, 160), Image.Resampling.LANCZOS)

        draw = ImageDraw.Draw(stamp)
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except IOError:
            font = ImageFont.load_default()

        # Draw wavy lines for the postmark.
        for i in range(0, stamp.height, 15):
            draw.line([(0, i), (stamp.width, i + 10)], fill=(0, 0, 0, 100), width=2)
            draw.line([(0, i+5), (stamp.width, i - 5)], fill=(0, 0, 0, 100), width=2)

        # Draw a circle for the date.
        circle_pos = (stamp.width // 4, stamp.height // 4, stamp.width * 3 // 4, stamp.height * 3 // 4)
        draw.ellipse(circle_pos, outline=(0, 0, 0, 150), width=3)

        # Add the date.
        date_text = date.today().strftime("%d %b\n%Y").upper()
        draw.multiline_text((stamp.width/2, stamp.height/2), date_text, font=font, fill=(0,0,0,180), anchor="mm", align="center")

        # Place the stamp on the postcard with a margin from its edge.
        margin = 35 # Augmentation de la marge pour plus d'espace
        position = (postcard.width - stamp.width - margin, margin) # Position at the top right.
        postcard.paste(stamp, position, stamp)

        return postcard

    except Exception as e:
        print(f"[Stamp] Error adding stamp: {e}")
        return card_image

def create_postcard_effect(img_content, caption=None):
    """Create a tilted postcard effect with a border and shadow."""
    # Set effect parameters.
    border_size = 35  # Main white border, enlarged to fit longer text.
    
    # --- ANGLE MODIFICATION ---
    # Limit random tilt to 5-10 degrees for better readability.
    angle = random.uniform(5, 10)
    rotation_angle = random.choice([-1, 1]) * angle
    
    shadow_offset = (15, 15)
    shadow_blur_radius = 25
    shadow_color = (0, 0, 0)

    # --- Add a subtle inner border ---
    # Better separate the photo from the white frame to create a beveled effect.
    draw = ImageDraw.Draw(img_content)
    draw.rectangle(
        [(0, 0), (img_content.width - 1, img_content.height - 1)],
        outline=(220, 220, 220), # Very light gray.
        width=1
    )

    # --- New logic: add the caption directly to the photo ---
    # This keeps the text readable regardless of the tilt.
    if caption and caption.strip():
        # Work on a copy so alpha_composite can be used for transparency.
        img_with_text = img_content.copy()
        if img_with_text.mode != 'RGBA':
            img_with_text = img_with_text.convert('RGBA')

        # Create a transparent layer for the caption band and text.
        overlay = Image.new('RGBA', img_with_text.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        try:
            # Scale the font size relative to image height for consistency.
            font_size = int(img_with_text.height * 0.06)
            font = ImageFont.truetype(str(POLAROID_FONT_PATH), font_size)
        except IOError:
            font = ImageFont.load_default()
        
        # Calculate the banner height based on the text size.
        _, text_top, _, text_bottom = font.getbbox(caption)
        text_height = text_bottom - text_top
        band_padding = int(font_size * 0.3)
        band_height = text_height + (band_padding * 2)
        
        # Position the banner at the bottom of the image.
        band_y0 = img_with_text.height - band_height
        draw.rectangle([(0, band_y0), (img_with_text.width, img_with_text.height)], fill=(0, 0, 0, 128)) # Semi-transparent black (50% opacity).
        
        # Center and draw the text in white inside the band.
        text_x = img_with_text.width / 2
        text_y = band_y0 + (band_height / 2)
        draw.text((text_x, text_y), caption, font=font, fill=(255, 255, 255), anchor="mm")
        
        # Combine the image and overlay, then convert back to RGB.
        img_content = Image.alpha_composite(img_with_text, overlay).convert('RGB')

    # 1. Create the postcard with its white border.
    card_size = (img_content.width + 2 * border_size, img_content.height + 2 * border_size)
    card = Image.new('RGBA', card_size, (255, 255, 255, 255))
    card.paste(img_content, (border_size, border_size))

    # Add the stamp to the postcard before rotating it.
    card = add_stamp_and_postmark(card)

    # 2. Tilt the postcard.
    rotated_card = card.rotate(rotation_angle, expand=True, resample=Image.Resampling.BICUBIC)

    # 3. Create the shadow.
    shadow_layer = Image.new('RGBA', rotated_card.size, (0, 0, 0, 0))
    # Create a black shape the same size as the rotated postcard for the shadow.
    shadow_draw = ImageDraw.Draw(shadow_layer)
    shadow_draw.bitmap((0,0), rotated_card.split()[3], fill=shadow_color) # Use the rotated postcard's alpha channel as the mask.
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur_radius))

    # 4. Combine the shadow and postcard on a final transparent image.
    final_size = (shadow_layer.width + abs(shadow_offset[0]), shadow_layer.height + abs(shadow_offset[1]))
    final_image = Image.new('RGBA', final_size, (0, 0, 0, 0))
    final_image.paste(shadow_layer, shadow_offset, shadow_layer)
    final_image.paste(rotated_card, (0, 0), rotated_card)

    return final_image

def create_polaroid_effect(image_content):
    """
    Apply a color effect and Polaroid frame to the given image.
    Accept a PIL image and return a new PIL image.
    """
    # Work directly on a copy of the original image to preserve its colors.
    content_with_frame = image_content.copy()

    # 2. Draw the frame inside the image.
    draw = ImageDraw.Draw(content_with_frame)
    width, height = content_with_frame.size
    frame_color = (255, 253, 248)
    padding_top = int(height * 0.05)
    padding_sides = int(height * 0.05)
    padding_bottom = int(height * 0.18)
    draw.rectangle([0, 0, width, padding_top], fill=frame_color)
    draw.rectangle([0, height - padding_bottom, width, height], fill=frame_color)
    draw.rectangle([0, padding_top, padding_sides, height - padding_bottom], fill=frame_color)
    draw.rectangle([width - padding_sides, padding_top, width, height - padding_bottom], fill=frame_color)
    
    return content_with_frame

def _caption_image(image, text):
    if not text or not text.strip():
        return image.convert('RGB')
    image = image.convert('RGBA')
    overlay = Image.new('RGBA', image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = image.size
    font_size = max(1, int(height * 0.05))
    try:
        font = ImageFont.truetype(str(POLAROID_FONT_PATH), font_size)
    except IOError:
        font = ImageFont.load_default()
    _, top, _, bottom = font.getbbox(text)
    padding = int(font_size * 0.4)
    box_width = font.getlength(text) + 2 * padding
    box_height = bottom - top + 2 * padding
    x = (width - box_width) / 2
    y = height - box_height - height * 0.03
    _draw_rounded_rectangle(draw, (x, y, x + box_width, y + box_height),
                            int(font_size * 0.3), fill=(255, 255, 255, 180))
    draw.text((width / 2, y + box_height / 2), text, font=font, fill=(0, 0, 0, 255), anchor="mm")
    return Image.alpha_composite(image, overlay).convert('RGB')


def apply_filter_to_image(image_path_str, filter_name, strength=None, caption=""):
    """
    Apply a filter to an image and save it.
    Use a backup so filters are not applied to an already-filtered image.
    """
    image_path = Path(image_path_str)
    from utils.photo_edits import filter_strength, validate_strength
    strength = filter_strength(image_path) if strength is None else validate_strength(strength)
    
    # Determine the backup path. Example: static/prepared/usb/img.jpg -> static/.backups/usb/img.jpg.
    try:
        prepared_index = image_path.parts.index('prepared')
        backup_base_path = Path(*image_path.parts[:prepared_index]) / '.backups'
        backup_path = backup_base_path.joinpath(*image_path.parts[prepared_index+1:])
    except ValueError:
        raise ValueError("The photo path does not appear to be inside a 'prepared' directory.")

    # Ensure the backup directory exists.
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    # Create a backup if one does not exist.
    if not backup_path.exists():
        shutil.copy2(image_path, backup_path)

    # Always process from the backup (the original prepared image).
    source_for_processing = backup_path

    try:
        img = Image.open(source_for_processing)
        # Preserve EXIF metadata so it can be restored when saving.
        exif_bytes = img.info.get('exif')
        if img.mode != 'RGB':
            img = img.convert('RGB')
    except FileNotFoundError:
        raise ValueError(f"Image source introuvable : {source_for_processing}")

    # Apply the selected filter.
    if filter_name == 'original':
        img_to_save = img
    elif filter_name == 'grayscale':
        img_to_save = ImageOps.grayscale(img).convert('RGB')
    elif filter_name == 'auto_enhance':
        img_to_save = ImageOps.autocontrast(img, cutoff=1, preserve_tone=True)
    elif filter_name == 'vivid':
        img_to_save = ImageEnhance.Color(img).enhance(1.35)
        img_to_save = ImageEnhance.Contrast(img_to_save).enhance(1.15)
    elif filter_name in {'warm', 'cool'}:
        red, green, blue = img.split()
        red_scale, blue_scale = (1.08, 0.92) if filter_name == 'warm' else (0.92, 1.08)
        red = red.point(lambda value: min(255, round(value * red_scale)))
        blue = blue.point(lambda value: min(255, round(value * blue_scale)))
        img_to_save = Image.merge('RGB', (red, green, blue))
    elif filter_name == 'dramatic_bw':
        gray = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=1)
        img_to_save = ImageEnhance.Contrast(gray).enhance(1.3).convert('RGB')
    elif filter_name == 'soft_glow':
        blurred = img.filter(ImageFilter.GaussianBlur(radius=max(img.size) * 0.008))
        glow = ImageEnhance.Brightness(blurred).enhance(1.12)
        img_to_save = Image.blend(img, glow, 0.3)
    elif filter_name == 'sharpen':
        img_to_save = img.filter(ImageFilter.UnsharpMask(radius=2, percent=130, threshold=3))
    elif filter_name == 'duotone':
        img_to_save = ImageOps.colorize(ImageOps.grayscale(img), '#172b4d', '#ffd6a0')
    elif filter_name == 'posterize':
        img_to_save = ImageOps.posterize(img, bits=3)
    elif filter_name == 'matte':
        softened = ImageEnhance.Color(img).enhance(0.85)
        img_to_save = softened.point(lambda value: round(24 + value * 0.85))
    elif filter_name == 'film_grain':
        # A local seeded generator keeps repeat applications stable without changing global randomness.
        noise = Image.frombytes('L', img.size, random.Random(0).randbytes(img.width * img.height))
        noise = noise.point(lambda value: 116 + round(value * 24 / 255)).convert('RGB')
        img_to_save = ImageChops.add(img, noise, offset=-128)
    elif filter_name == 'pencil_sketch':
        gray = ImageOps.grayscale(img)
        edges = gray.filter(ImageFilter.FIND_EDGES)
        # FIND_EDGES leaves an unprocessed border; whitening it avoids an artificial dark frame.
        edges_draw = ImageDraw.Draw(edges)
        edges_draw.rectangle((0, 0, img.width - 1, img.height - 1), outline=0)
        sketch = ImageOps.invert(ImageOps.autocontrast(edges))
        img_to_save = Image.blend(sketch, Image.new('L', img.size, 255), 0.15).convert('RGB')
    elif filter_name in {'selective_red', 'selective_green', 'selective_blue'}:
        red, green, blue = img.split()
        selected = {'selective_red': red, 'selective_green': green, 'selective_blue': blue}[filter_name]
        others = {'selective_red': (green, blue), 'selective_green': (red, blue),
                  'selective_blue': (red, green)}[filter_name]
        dominance = ImageChops.subtract(selected, ImageChops.lighter(*others))
        mask = dominance.point(lambda value: min(255, max(0, (value - 15) * 8)))
        img_to_save = Image.composite(img, ImageOps.grayscale(img).convert('RGB'), mask)
    elif filter_name == 'tilt_shift':
        blurred = img.filter(ImageFilter.GaussianBlur(radius=max(img.size) * 0.015))
        mask = Image.new('L', (1, img.height))
        mask.putdata([round(255 * min(1, max(0, (abs((y + 0.5) / img.height - 0.5) - 0.15) / 0.25)))
                      for y in range(img.height)])
        img_to_save = Image.composite(blurred, img, mask.resize(img.size))
    elif filter_name == 'cinematic':
        red, green, blue = img.split()
        shadows = Image.merge('RGB', (
            red.point(lambda value: max(0, value - 12)),
            green.point(lambda value: min(255, value + 6)),
            blue.point(lambda value: min(255, value + 12))))
        highlights = Image.merge('RGB', (
            red.point(lambda value: min(255, value + 12)),
            green.point(lambda value: min(255, value + 3)),
            blue.point(lambda value: max(0, value - 10))))
        toned = Image.composite(highlights, shadows, ImageOps.grayscale(img))
        img_to_save = ImageEnhance.Color(toned).enhance(0.9)
    elif filter_name == 'cross_process':
        red, green, blue = img.split()
        red = red.point(lambda value: round(255 * (3 * (value / 255) ** 2 - 2 * (value / 255) ** 3)))
        green = green.point(lambda value: round(255 * (0.25 * value / 255 +
                           0.75 * (3 * (value / 255) ** 2 - 2 * (value / 255) ** 3))))
        blue = blue.point(lambda value: round(24 + value * 0.82))
        img_to_save = Image.merge('RGB', (red, green, blue))
    elif filter_name == 'watercolor':
        softened = img.filter(ImageFilter.MedianFilter(size=5)).filter(ImageFilter.SMOOTH_MORE)
        painted = Image.blend(softened, ImageOps.posterize(softened, bits=5), 0.65)
        edges = ImageOps.grayscale(softened).filter(ImageFilter.FIND_EDGES)
        ImageDraw.Draw(edges).rectangle((0, 0, img.width - 1, img.height - 1), outline=0)
        ink = edges.point(lambda value: 255 - round(value * 0.25)).convert('RGB')
        img_to_save = ImageChops.multiply(painted, ink)
    elif filter_name == 'sepia':
        grayscale = ImageOps.grayscale(img)
        # Create a sepia palette. It must be a flat list of 768 integers (256 * RGB).
        sepia_palette = []
        for i in range(256):
            r, g, b = int(i * 1.07), int(i * 0.74), int(i * 0.43)
            sepia_palette.extend([min(255, r), min(255, g), min(255, b)])
        grayscale.putpalette(sepia_palette)
        img_to_save = grayscale.convert('RGB')
    elif filter_name == 'vignette':
        img_to_save = ImageOps.grayscale(img).convert('RGB')
        content_bbox = _get_content_bbox(img)
        if content_bbox and not (
                content_bbox[0] <= 0 and content_bbox[1] <= 0
                and content_bbox[2] >= img.width and content_bbox[3] >= img.height):
            img_to_save.paste(img.crop(content_bbox), content_bbox[:2])
        else:
            # Full-frame photos have no separate background; retain a soft color center instead.
            mask = Image.new('L', img.size, 0)
            ImageDraw.Draw(mask).ellipse(
                (img.width * 0.1, img.height * 0.1, img.width * 0.9, img.height * 0.9), fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(radius=max(img.size) * 0.03))
            img_to_save = Image.composite(img, img_to_save, mask)
    elif filter_name == 'dark_vignette':
        # A small elliptical falloff scales to any photo without a full-size Python pixel loop.
        mask = Image.new('L', (129, 129))
        mask.putdata([round(255 * (1 - 0.5 * (((x - 64) / 64) ** 2 / 2 +
                                           ((y - 64) / 64) ** 2 / 2) ** 1.3))
                      for y in range(129) for x in range(129)])
        mask = mask.resize(img.size, Image.Resampling.LANCZOS)
        img_to_save = Image.composite(img, Image.new('RGB', img.size, 0), mask)
    elif filter_name == 'vintage':
        # 1. Reduce color saturation for a faded look.
        enhancer = ImageEnhance.Color(img)
        img_vintage = enhancer.enhance(0.5) # 0.0: N&B, 1.0: original
        
        # 2. Apply a yellow-orange tint to simulate aged paper.
        sepia_tint = Image.new('RGB', img_vintage.size, (255, 240, 192)) # Light sepia tint.
        img_to_save = Image.blend(img_vintage, sepia_tint, alpha=0.3) # alpha controls intensity.
    elif filter_name == 'polaroid_vintage':
        # --- NEW LOGIC TO TARGET THE IMAGE CONTENT ---
        content_bbox = _get_content_bbox(img)
        if not content_bbox:
            print(f"Warning: Bounding box not found for {image_path_str}. The Polaroid Vintage filter may not be applied correctly.")
            img_to_save = img # Do nothing to avoid an incorrect result.
        else:
            # 1. Isolate the image content.
            content_img = img.crop(content_bbox)

            # 2. Apply vintage color filters to the content.
            #    EDIT THE VALUES BELOW TO ADJUST THE INTENSITY.
            
            # Contrast (1.0 = original, < 1.0 = lower contrast). A subtler example: 0.9.
            content_filtered = ImageEnhance.Contrast(content_img).enhance(0.8)
            
            # Yellow tint (alpha from 0.0 to 1.0, 0.0 = no tint). A subtler example: 0.15.
            yellow_overlay = Image.new('RGB', content_filtered.size, (255, 248, 220))
            content_filtered = Image.blend(content_filtered, yellow_overlay, 0.25)
            
            # Brightness (1.0 = original, > 1.0 = brighter). A subtler example: 1.05.
            content_filtered = ImageEnhance.Brightness(content_filtered).enhance(1.1)
            
            # Blue tint in shadows (alpha from 0.0 to 1.0). A subtler example: 0.05.
            blue_overlay = Image.new('RGB', content_filtered.size, (0, 100, 120))
            content_filtered = Image.blend(content_filtered, blue_overlay, 0.08)

            # 3. Draw the Polaroid frame around the filtered content.
            draw = ImageDraw.Draw(content_filtered)
            width, height = content_filtered.size
            frame_color = (255, 253, 248)
            padding_top = int(height * 0.05)
            padding_sides = int(height * 0.05)
            padding_bottom = int(height * 0.18)
            draw.rectangle([0, 0, width, padding_top], fill=frame_color)
            draw.rectangle([0, height - padding_bottom, width, height], fill=frame_color)
            draw.rectangle([0, padding_top, padding_sides, height - padding_bottom], fill=frame_color)
            draw.rectangle([width - padding_sides, padding_top, width, height - padding_bottom], fill=frame_color)
            
            # 4. Place the modified content back into the full image.
            img_to_save = img.copy()
            img_to_save.paste(content_filtered, content_bbox)
    else:
        raise ValueError(f"Filtre inconnu : '{filter_name}'")

    if filter_name != 'original' and strength < 1:
        img_to_save = Image.blend(img, img_to_save, strength)
    img_to_save = _caption_image(img_to_save, caption)
    # Save the modified image in the 'prepared' directory.
    if exif_bytes:
        img_to_save.save(image_path, 'JPEG', quality=90, optimize=True, exif=exif_bytes)
    else:
        img_to_save.save(image_path, 'JPEG', quality=90, optimize=True)

def add_text_to_image(image_path_str, text):
    """
    Update the text for an image, save it, and regenerate the base image.
    et sa version carte postale si elle existe.
    """
    image_path = Path(image_path_str)
    
    # --- 1. Update the text cache file ---
    try:
        # The key is the path relative to 'prepared', e.g. 'usb/photo.jpg'.
        relative_path_key = '/'.join(image_path.parts[-2:])
        user_texts = _load_user_texts()
        
        if text and text.strip():
            user_texts[relative_path_key] = text
        else:
            # If the text is empty, remove it from the cache.
            user_texts.pop(relative_path_key, None)
            
        _save_user_texts(user_texts)
    except Exception as e:
        print(f"Error updating the text cache: {e}")
        # Continue and attempt to regenerate the image.

    # --- 2. Regenerate the images (base and postcard) ---

    # Backup logic.
    try:
        prepared_index = image_path.parts.index('prepared')
        backup_base_path = Path(*image_path.parts[:prepared_index]) / '.backups'
        backup_path = backup_base_path.joinpath(*image_path.parts[prepared_index+1:])
    except ValueError:
        raise ValueError("The photo path does not appear to be inside a 'prepared' directory.")

    if not backup_path.exists():
        # If there is no backup, use the current image as the source and create one.
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, backup_path)

    # Always start from the clean version (the backup).
    base_image_from_backup = Image.open(backup_path)
    exif_bytes = base_image_from_backup.info.get('exif')

    # --- 2a. Regenerate the postcard ---
    postcard_path = image_path.with_name(f"{image_path.stem}_postcard.jpg")
    if postcard_path.exists():
        try:
            background_img = base_image_from_backup.copy()
            if background_img.mode != 'RGB':
                background_img = background_img.convert('RGB')

            content_bbox = _get_content_bbox(background_img)
            if not content_bbox:
                raise ValueError("Bounding box not found; cannot regenerate the postcard.")

            content_img = background_img.crop(content_bbox)
            output_width, output_height = background_img.size

            postcard_img_content = content_img.copy()
            scale_factor = 0.85
            postcard_img_content.thumbnail(
                (int(output_width * scale_factor), int(output_height * scale_factor)), 
                Image.Resampling.LANCZOS
            )
            
            postcard_effect_img = create_postcard_effect(postcard_img_content, caption=text)

            final_postcard_img = background_img.copy()
            postcard_x_offset = (output_width - postcard_effect_img.width) // 2
            postcard_y_offset = (output_height - postcard_effect_img.height) // 2
            final_postcard_img.paste(postcard_effect_img, (postcard_x_offset, postcard_y_offset), postcard_effect_img)

            final_postcard_img.save(postcard_path, 'JPEG', quality=90, optimize=True, exif=exif_bytes)
            print(f"[Text Update] Postcard updated for {image_path.name}")

        except Exception as e:
            print(f"--- POSTCARD UPDATE ERROR for {image_path.name}: {e} ---")

    # --- 2b. Update the base image ---
    img_to_save = _caption_image(base_image_from_backup, text)

    if exif_bytes:
        img_to_save.save(image_path, 'JPEG', quality=90, optimize=True, exif=exif_bytes)
    else:
        img_to_save.save(image_path, 'JPEG', quality=90, optimize=True)

def add_text_to_polaroid(polaroid_path_str, text):
    """
    Add or update text on an existing Polaroid image.
    """
    polaroid_path = Path(polaroid_path_str)
    if not polaroid_path.exists():
        raise FileNotFoundError(f"L'image Polaroid n'existe pas : {polaroid_path}")

    img = Image.open(polaroid_path)
    # Preserve EXIF metadata so it can be restored when saving.
    exif_bytes = img.info.get('exif')

    draw = ImageDraw.Draw(img)

    # --- Use the content bounding box for correct positioning ---
    content_bbox = _get_content_bbox(img)
    if not content_bbox:
        print(f"Warning: Unable to find the content bounding box for {polaroid_path}. Text will not be added.")
        # Do nothing if the content location is unknown.
        return

    # Content coordinates (left, top, right, bottom).
    content_x, content_y, content_right, content_bottom = content_bbox
    content_width = content_right - content_x
    content_height = content_bottom - content_y

    # Set the frame color and bottom-margin dimensions.
    frame_color = (255, 253, 248) # Must match the frame color.
    # Padding is relative to the Polaroid *content* size, not the screen.
    padding_bottom = int(content_height * 0.18)
    padding_sides = int(content_height * 0.05)

    # 1. Clear the old text by redrawing the bottom margin of the Polaroid.
    draw.rectangle([content_x, content_bottom - padding_bottom, content_right, content_bottom], fill=frame_color)

    # 2. Add the new text, if provided.
    if text and text.strip():
        try:
            # Font size is relative to the margin size.
            font_size = int(padding_bottom * 0.4)
            font = ImageFont.truetype(str(POLAROID_FONT_PATH), font_size)
            
            # Calculate the center of the Polaroid text area.
            text_area_center_x = (content_x + content_right) / 2
            text_area_center_y = content_bottom - (padding_bottom / 2)
            # Draw the text using the 'mm' anchor for precise centering.
            draw.text((text_area_center_x, text_area_center_y), text, font=font, fill=(80, 80, 80), anchor="mm")
        except IOError:
            print(f"Warning: Font not found at {POLAROID_FONT_PATH}. Text will not be added.")
    # 3. Save the modified image while preserving EXIF.
    if exif_bytes:
        img.save(polaroid_path, 'JPEG', quality=95, optimize=True, exif=exif_bytes)
    else:
        img.save(polaroid_path, 'JPEG', quality=95, optimize=True)
