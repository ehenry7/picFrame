# ❓ Frequently Asked Questions (FAQ) - PictureFrame

Here is a list of frequently asked questions to help you use and troubleshoot PictureFrame.

---

### General Questions

**Q: What is PictureFrame?**

**A:** PictureFrame is software that turns a Raspberry Pi into a smart digital photo frame. It displays photos imported from a USB stick or a smartphone/computer browser.

**Q: What do I need to use PictureFrame?**

**A:** You will need:
- A Raspberry Pi (model 3, 4, or 5 recommended) with its power supply.
- An SD card with Raspberry Pi OS (64-bit) installed.
- A screen.
- An internet connection (Wi-Fi or Ethernet).

---

### Installation and Configuration

**Q: How do I install PictureFrame?**

**A:** The installation is designed to be simple:
1. Clone the GitHub repository: `git clone https://github.com/ehenry7/picFrame.git`
2. Go into the directory: `cd picFrame`
3. Make the installation script executable: `chmod +x setup.sh`
4. Run the script with administrator rights: `sudo ./setup.sh`
The script takes care of installing all dependencies and configuring the system for automatic startup.

**Q: How do I access the configuration interface?**

**A:** Once the Raspberry Pi has started, open a web browser on another device (computer, smartphone) connected to the same network and simply type in your Raspberry Pi's IP address. For example: `http://192.168.1.25`. If you don't know the IP, it is often displayed on the frame's screen on the first boot or if no photos are found.

**Q: I forgot my password for the web interface. How can I reset it?**

**A:** The initial password is stored in the `/boot/firmware/credentials.json` file. You can connect to your Raspberry Pi via SSH to read this file. If you changed it through the interface and forgot it, you will need to delete this file and reboot the Pi for it to generate a new one (warning: this will reset the user).

**Q: What happens to previously imported photos?**

**A:** They remain in the library under **Imported photos**. Existing metadata, captions, favorites, and playlists are preserved. Remote album downloads are no longer supported.

---

### Features

**Q: What is the "Favorites" tab for?**

**A:** By marking a photo as a favorite (using the star icon <i class="fas fa-star"></i> in the "Preview" tab), you increase its display frequency in the slideshow. You can adjust the "boost factor" in the "Display" tab to make them appear more or less often.

**Q: What is the "Postcard" effect?**

**A:** It's a filter that adds a white border and a space for a caption (if you add one via the interface) to your photos, giving them a postcard look for a more personal and warm touch.

---

### Troubleshooting

**Q: I have a problem, where can I find help?**

**A:** The **System** tab is the best place to start. It contains a **Logs** section.
- `app.py` contains the logs for the web server (configuration interface).
- `local_slideshow_stdout` and `local_slideshow_stderr` contain the logs for the slideshow itself. Errors will most often appear in `stderr`.

**Q: Videos are not smooth or don't display. What should I do?**

**A:** In the **Display** tab, try enabling the "**Enable hardware video decoding**" option. It is much more performant, especially on a Raspberry Pi. If it causes issues (black/blue screen after a video), disable it.

**Q: The Wi-Fi won't connect, but Ethernet (cable) works. Why?**

**A:** Sometimes, if an Ethernet cable is plugged in, the system gives it priority. In the **System** tab, you can try to temporarily disable the "**Wired Interface (eth0)**" to force the system to use Wi-Fi exclusively.

**Q: How do I update PictureFrame?**

**A:** Remote updates from the web interface are not supported. Stop the app, back up configuration, and update the code manually using Git. Review changes and dependencies before restarting; local changes must be preserved.

**Q: I changed a setting, but nothing changes on the slideshow.**

**A:** Some changes, especially those related to display (font, weather, etc.), require the slideshow to be restarted to take effect. You can do this from the **Actions** tab by clicking "Stop" and then "Start Slideshow". For more significant changes, a restart of the web application or the system (from the **System** tab) may be necessary.