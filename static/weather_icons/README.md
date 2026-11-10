# PictureFrame Weather Icons

This directory contains the weather icons used by the slideshow. Weather data
comes from Open-Meteo; its WMO weather codes are mapped to the OpenWeatherMap-style
icon filenames used by the slideshow.

## Windows HTTPS certificates

Install the current core dependencies with `python -m pip install -r requirements.txt`
and restart the slideshow. On Windows, the slideshow uses `truststore` to validate
HTTPS certificates against the Windows certificate store, including locally
trusted organizational certificates. Certificate verification remains enabled.
If the chain is still untrusted, have your administrator install the appropriate
trusted certificate; do not disable HTTPS verification.

## Getting the icons

PictureFrame uses OpenWeatherMap API icon codes. Download the corresponding
images and place them in this directory.

1. **Open the OpenWeatherMap weather conditions page:**
   [https://openweathermap.org/weather-conditions](https://openweathermap.org/weather-conditions)

2. **Download the icons.** For each icon code (for example, `01d` or `10n`),
   download the corresponding image. The URL format is:
   `https://openweathermap.org/img/wn/CODE@2x.png`

   Replace `CODE` with the icon code. For example, the URL for `10d` (daytime
   rain) is:
   https://openweathermap.org/img/wn/10d@2x.png

3. **Save the images in this directory** (`static/weather_icons/`), naming each
   file after its code followed by `.png`.
   - Rename `10d@2x.png` to `10d.png`.
   - Rename `01n@2x.png` to `01n.png`.
   - And so on.

### Common icons to download

* `01d.png` (clear sky, day) and `01n.png` (night)
* `02d.png` (few clouds, day) and `02n.png` (night)
* `03d.png` and `03n.png` (scattered clouds)
* `04d.png` and `04n.png` (broken clouds)
* `09d.png` and `09n.png` (rain showers)
* `10d.png` (rain, day) and `10n.png` (night)
* `11d.png` and `11n.png` (thunderstorm)
* `13d.png` and `13n.png` (snow)
* `50d.png` and `50n.png` (fog)

Download at least the icons most common in your region. If an icon is missing,
only the text will be displayed.
