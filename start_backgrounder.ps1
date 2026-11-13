<#
.SYNOPSIS
    Start PictureFrame in background updater mode on Windows.
.DESCRIPTION
    Launches the Flask app with PICTUREFRAME_APP_MODE=background_updater
    so the app runs as a desktop wallpaper updater instead of a fullscreen
    slideshow. The background updater renders photos with overlays (clock,
    weather, etc.) and sets them as the desktop wallpaper on all monitors.
.EXAMPLE
    .\start_backgrounder.ps1
.NOTES
    Stop with: python stop.py  (or Ctrl+C in the console window)
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Ensure log directory exists.
if (-not (Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

# Force background updater mode via environment variable.
$env:PICTUREFRAME_APP_MODE = "background_updater"

# Use venv if available, otherwise global Python.
$pythonCmd = "python"
$pipCmd = "pip install"

if (Test-Path "venv\Scripts\Activate.ps1") {
    Write-Host "🐍 Activating virtual environment"
    & "venv\Scripts\Activate.ps1"
    $pythonCmd = "python"
    $pipCmd = "pip install"
} else {
    Write-Host "🐍 Using global Python"
}

# Check and install core requirements if missing.
$checkResult = & $pythonCmd -c "import flask, PIL, pygame, psutil, requests, flask_babel, piexif" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "📦 Installing dependencies from requirements.txt..."
    & $pipCmd -r requirements.txt 2>&1 | Out-File -Append -FilePath "logs\pictureframe.log" -Encoding UTF8
}

Write-Host "🖼️ Starting PictureFrame in background updater mode..."
Write-Host "📋 Logs: logs\pictureframe.log"
Write-Host "🛑 Stop with: python stop.py  (or Ctrl+C)"

& $pythonCmd -u app.py 2>&1 | Out-File -Append -FilePath "logs\pictureframe.log" -Encoding UTF8
