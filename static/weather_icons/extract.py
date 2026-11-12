import os
import cv2
import numpy as np

# Change this to the updated downloaded image name
input_image_path = "weather.jpg" 
output_folder = "weather_icons"

os.makedirs(output_folder, exist_ok=True)

img = cv2.imread(input_image_path)
if img is None:
    print(f"Error: Could not load {input_image_path}.")
    exit()

h, w, _ = img.shape

# 4 rows x 5 columns
rows = 4
cols = 5
icon_names = [
    ["01d", "01n", "02d", "02n", "03d"],
    ["03n", "04d", "04n", "09d", "09n"],
    ["10d", "10n", "11d", "11n", "13d"],
    ["13n", "50d", "50n", None,  None ] 
]

block_w = w // cols
block_h = h // rows

print("Extracting transparent, de-spilled weather icons...")

for r in range(rows):
    for c in range(cols):
        name = icon_names[r][c]
        if not name:
            continue
        
        # Calculate cropping box
        x_start = c * block_w
        y_start = r * block_h
        x_end = x_start + block_w
        y_end = y_start + block_h
        
        # Crop the block
        crop = img[y_start:y_end, x_start:x_end]
        
        # Convert to float for precise color-spill math
        bgra = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA).astype(np.float32)
        b, g, r_ch, a = cv2.split(bgra)
        
        # Calculate the "greenness" compared to Blue and Red
        excess_green = g - np.maximum(b, r_ch)
        excess_green = np.maximum(excess_green, 0)
        
        # 1. DE-SPILL: Suppress excess green by pulling it down to 
        # the level of blue/red, turning the green halo into neutral gray/white
        g_despilled = g - excess_green
        
        # 2. TRANSPARENCY (ALPHA): Smooth transition based on excess green.
        # Adjusted 'threshold' to 45.0 (up from 30) so dark fog/mist is NOT cut out.
        threshold = 45.0 
        opacity_factor = 255.0 - (excess_green * (255.0 / (255.0 - threshold)))
        opacity_factor = np.clip(opacity_factor, 0, 255)
        
        # Combine the new transparent channel with existing opaque areas
        final_alpha = np.minimum(a, opacity_factor)
        
        # Apply the changes
        processed = cv2.merge([b, g_despilled, r_ch, final_alpha])
        processed = np.clip(processed, 0, 255).astype(np.uint8)
        
        # Tight-trim spacing around the image
        gray = cv2.cvtColor(processed[:,:,0:3], cv2.COLOR_BGR2GRAY)
        alpha_ch = processed[:, :, 3]
        contours, _ = cv2.findContours(alpha_ch, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if contours:
            x, y, w_box, h_box = cv2.boundingRect(np.vstack(contours))
            # Pad slightly to avoid cutting edge pixels
            pad = 2
            y1 = max(0, y - pad)
            y2 = min(processed.shape[0], y + h_box + pad)
            x1 = max(0, x - pad)
            x2 = min(processed.shape[1], x + w_box + pad)
            final_output = processed[y1:y2, x1:x2]
        else:
            final_output = processed
            
        # Save output image as PNG
        out_path = os.path.join(output_folder, f"{name}.png")
        cv2.imwrite(out_path, final_output)
        print(f"Processed & De-spilled: {out_path}")

print("\nSuccess! Fully de-spilled, clean transparent icons are in the 'weather_icons' folder.")