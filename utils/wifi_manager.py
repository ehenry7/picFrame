import subprocess
import time
import re
import os

def get_wifi_status():
    """
    Get the current Wi-Fi connection status (SSID and IP address).
    Return the information in a dictionary.
    """
    status = {"ssid": "Not connected", "ip_address": "N/A", "is_connected": False}
    
    # Avoid calling nmcli if wlan0 does not exist.
    if not os.path.exists("/sys/class/net/wlan0"):
        status["ssid"] = "N/A (Pas de Wi-Fi)"
        return status

    try:
        # Use nmcli to get a reliable status.
        cmd = ['/usr/bin/nmcli', '-t', '-f', 'GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS', 'dev', 'show', 'wlan0']
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        
        lines = output.split('\n')
        state_line = lines[0]
        conn_line = lines[1]
        ip_line = lines[2]

        if '100 (connecté)' in state_line or 'connected' in state_line:
            status["is_connected"] = True
            # Extract the SSID.
            ssid_match = re.search(r'GENERAL.CONNECTION:(.*)', conn_line)
            if ssid_match:
                status["ssid"] = ssid_match.group(1)
            
            # Extract the IP address.
            ip_match = re.search(r'IP4.ADDRESS\[1\]:(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', ip_line)
            if ip_match:
                status["ip_address"] = ip_match.group(1)

    except (subprocess.CalledProcessError, FileNotFoundError):
        pass # Commands fail when disconnected; the default status is correct.
    return status

def set_wifi_config(ssid: str, password: str, country_code: str = "FR"):
    """
    Configure the Wi-Fi country, updates credentials in wpa_supplicant.conf,
    and connects using nmcli (NetworkManager).
    """
    if not country_code:
        raise ValueError("The country code is required.")

    # 1. Set the Wi-Fi country using raspi-config.
    try:
        print(f"Setting Wi-Fi country to: {country_code}")
        subprocess.run(
            ['sudo', '-n', '/usr/bin/raspi-config', 'nonint', 'do_wifi_country', country_code],
            check=True, capture_output=True, text=True, timeout=15
        )
    except subprocess.CalledProcessError as e:
        raise Exception(f"Unable to set Wi-Fi country: {e.stderr}")
    except subprocess.TimeoutExpired:
        raise Exception("The raspi-config command timed out.")
    except FileNotFoundError:
        raise Exception("The 'raspi-config' command was not found. Is this running on Raspberry Pi OS?")

    # 2. Connect using nmcli.
    try:
        print(f"Attempting to connect to Wi-Fi '{ssid}' via nmcli...")
        
        # Delete the old connection, if present, to force a new configuration.
        subprocess.run(['sudo', '-n', 'nmcli', 'connection', 'delete', ssid], capture_output=True, check=False)
        
        # Create the new connection.
        cmd = ['sudo', '-n', '/usr/bin/nmcli', 'device', 'wifi', 'connect', ssid]
        if password:
            cmd.extend(['password', password])
        
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        print(f"Wi-Fi connection succeeded: {result.stdout}")
        
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        stderr = getattr(e, 'stderr', str(e))
        print(f"Error connecting via nmcli: {stderr}")
        raise Exception(f"Wi-Fi connection failed. Details: {stderr}")