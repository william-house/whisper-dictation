# Whisper Offline Dictation System (Windows)

This project implements a fully local, offline speech-to-text dictation utility for Windows powered by **Faster-Whisper**. It runs in the system tray, plays audio cue beeps, and automatically types transcribed text at your current cursor position using global hotkeys.

## The Prompt to use:
- Can you install this offline Whisper dictation utility on my PC from this GitHub repository: https://github.com/william-house/whisper-dictation? Please clone it to a reasonable directory in my user profile, run the install.ps1 script to set up the virtual environment, download the model, configure the startup shortcut, and then start the application.

## Features
- **Alt+C (Toggle Mode)**: Press once to start recording, press again to stop and transcribe.
- **Alt+Z (Push-to-Talk Mode)**: Hold Alt+Z to record, release to stop and transcribe. (Drains duplicate input queue events from keyboard auto-repeat).
- **Offline Inference**: Uses the quantized CTranslate2 model (`base.en` in `int8` mode) which runs extremely fast on consumer CPUs.
- **System Tray Interface**: Shows visual state updates (loading, ready, recording, transcribing).
- **Auto-run at Login**: Configures a Windows Startup shortcut.

---

## File Structure

```text
whisper-dictation/
│
├── requirements.txt      # Python dependencies
├── dictation.pyw         # Main script (runs silently without a cmd window)
├── launch.vbs            # VBS wrapper for running without shell flash
└── install.ps1           # Automated PowerShell setup script
```

---

## Installation Steps (For New PCs)

To install this on a new Windows computer:

1. **Create folder**: Create a folder `C:\Users\<username>\whisper-dictation\` (or any directory of your choice).
2. **Save files**: Recreate the project files (`requirements.txt`, `dictation.pyw`, `launch.vbs`, `install.ps1`, and `_download_model.py`) using the source code provided below.
3. **Run the Installer**:
   - Open PowerShell as a regular user (non-admin).
   - Run the following command:
     ```powershell
     Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process; .\install.ps1
     ```
   - The installer will:
     - find a usable Python 3.9+ install if one already exists
     - install Python 3.12 with `winget` if Python is missing
     - create the virtual environment
     - install all Python dependencies
     - cache the Whisper model
     - create the Startup shortcut
4. **Reboot or Start**:
   - The installer automatically creates a Windows Startup shortcut.
   - You can start the tool immediately by double-clicking `launch.vbs`.

---

## Source Code

### 1. `requirements.txt`
```text
faster-whisper
sounddevice
numpy
pyperclip
pyautogui
pystray
Pillow
```

### 2. `launch.vbs`
```vbscript
' launch.vbs — Starts dictation app using pythonw.exe without a terminal window popping up.
Dim objShell, scriptDir, pythonExe, scriptPath
Set objShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
pythonExe = scriptDir & "\venv\Scripts\pythonw.exe"
scriptPath = scriptDir & "\dictation.pyw"

objShell.Run """" & pythonExe & """ """ & scriptPath & """", 0, False
Set objShell = Nothing
```

### 3. `install.ps1`
```powershell
# install.ps1 - Automated Installation
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  Whisper Dictation - Installer' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan

# Locate or install Python
# Prefer an existing Python 3.9+ install; otherwise install Python 3.12 with winget.

# Create Virtual Environment
$venvDir = Join-Path $scriptDir 'venv'
if (-not (Test-Path $venvDir)) {
    Write-Host '[2/5] Creating virtual environment...' -ForegroundColor Yellow
    & $pythonExe -m venv $venvDir
} else {
    Write-Host '[2/5] Virtual environment already exists.' -ForegroundColor Green
}

# Install dependencies
$pipExe = Join-Path $venvDir 'Scripts\pip.exe'
Write-Host '[3/5] Installing dependencies (this may take a few minutes)...' -ForegroundColor Yellow
& $pipExe install --upgrade pip
& $pipExe install -r (Join-Path $scriptDir 'requirements.txt')
Write-Host '[3/5] Dependencies successfully installed.' -ForegroundColor Green

# Pre-download Whisper Model
$pythonVenv = Join-Path $venvDir 'Scripts\python.exe'
Write-Host '[4/5] Pre-downloading Whisper model (base.en)...' -ForegroundColor Yellow
$downloadScript = Join-Path $scriptDir '_download_model.py'
@"
from faster_whisper import WhisperModel
WhisperModel("base.en", device="cpu", compute_type="int8")
print("Model downloaded successfully.")
"@ | Set-Content -Path $downloadScript -Encoding UTF8

& $pythonVenv $downloadScript
Remove-Item -Path $downloadScript -ErrorAction SilentlyContinue
Write-Host '[4/5] Whisper Model cached.' -ForegroundColor Green

# Create Startup Shortcut
Write-Host '[5/5] Configuring startup entry...' -ForegroundColor Yellow
$startupFolder = [System.Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupFolder 'WhisperDictation.lnk'
$vbsPath = Join-Path $scriptDir 'launch.vbs'

$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'wscript.exe'
$shortcut.Arguments = "`"$vbsPath`""
$shortcut.WorkingDirectory = $scriptDir
$shortcut.Description = 'Whisper Dictation (Alt+C / Alt+Z)'
$shortcut.Save()
Write-Host '[5/5] Startup shortcut created!' -ForegroundColor Green

Write-Host ''
Write-Host '========================================' -ForegroundColor Cyan
Write-Host '  Setup Complete!' -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Cyan
```

### 4. `dictation.pyw`
```python
"""
Whisper-Powered Dictation — Native Windows Hotkeys
================================================
Alt+C -> Toggle Recording
Alt+Z -> Hold to Talk (PTT)
"""
import sys
import os
import threading
import time
import winsound
import numpy as np
import sounddevice as sd
import pyperclip
import pyautogui
from PIL import Image, ImageDraw
import pystray
import ctypes
import ctypes.wintypes

# Configuration
WHISPER_MODEL = "base.en"
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"

BEEP_START = (800, 150)
BEEP_STOP = (600, 150)
BEEP_DONE = (1000, 100)
BEEP_ERROR = (300, 300)

recording = False
audio_chunks = []
stream = None
model = None
model_lock = threading.Lock()
tray_icon = None
app_running = True
hotkey_lock = threading.Lock()

def create_icon_image(color="#4a90d9", ring=None):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse([margin, margin, size-margin, size-margin], fill=color, outline="#ffffff", width=2)
    cx, cy = size // 2, size // 2
    bar_w, bar_h = 6, 18
    draw.rounded_rectangle([cx - bar_w, cy - bar_h + 2, cx + bar_w, cy + 6], radius=bar_w, fill="#ffffff")
    draw.arc([cx - 12, cy - 6, cx + 12, cy + 16], start=0, end=180, fill="#ffffff", width=2)
    draw.line([cx, cy + 16, cx, cy + 22], fill="#ffffff", width=2)
    draw.line([cx - 8, cy + 22, cx + 8, cy + 22], fill="#ffffff", width=2)
    if ring:
        draw.ellipse([1, 1, size-1, size-1], outline=ring, width=3)
    return img

ICON_IDLE = create_icon_image("#4a90d9")
ICON_RECORDING = create_icon_image("#e74c3c", ring="#ff0000")
ICON_TRANSCRIBING = create_icon_image("#f39c12", ring="#ffaa00")
ICON_LOADING = create_icon_image("#95a5a6")

def load_model():
    global model
    from faster_whisper import WhisperModel
    print(f"[dictation] Loading Whisper model '{WHISPER_MODEL}'...", flush=True)
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    print("[dictation] Model loaded. Ready for dictation!", flush=True)
    update_tray_icon(ICON_IDLE, "Dictation — Ready (Alt+C / Alt+Z)")

def update_tray_icon(icon_image, tooltip=None):
    if tray_icon:
        tray_icon.icon = icon_image
        if tooltip:
            tray_icon.title = tooltip

def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"[dictation] Audio status: {status}", flush=True)
    audio_chunks.append(indata.copy())

def start_recording():
    global recording, stream, audio_chunks
    audio_chunks = []
    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE, callback=audio_callback, blocksize=1024)
        stream.start()
    except Exception as e:
        print(f"[dictation] ERROR starting recording: {e}", flush=True)
        threading.Thread(target=winsound.Beep, args=BEEP_ERROR, daemon=True).start()
        return False
    recording = True
    update_tray_icon(ICON_RECORDING, "Dictation — Recording...")
    threading.Thread(target=winsound.Beep, args=BEEP_START, daemon=True).start()
    return True

def stop_recording():
    global recording, stream
    if stream:
        stream.stop()
        stream.close()
        stream = None
    recording = False
    threading.Thread(target=winsound.Beep, args=BEEP_STOP, daemon=True).start()
    if not audio_chunks:
        update_tray_icon(ICON_IDLE, "Dictation — Ready (Alt+C / Alt+Z)")
        return None
    audio = np.concatenate(audio_chunks, axis=0).flatten()
    duration = len(audio) / SAMPLE_RATE
    if duration < 0.3:
        update_tray_icon(ICON_IDLE, "Dictation — Ready (Alt+C / Alt+Z)")
        return None
    return audio

def transcribe(audio):
    update_tray_icon(ICON_TRANSCRIBING, "Dictation — Transcribing...")
    with model_lock:
        segments, info = model.transcribe(audio, beam_size=5, language="en", vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))
        text_parts = [segment.text.strip() for segment in segments]
    return " ".join(text_parts).strip()

def paste_text(text):
    if not text: return
    try: old_clipboard = pyperclip.paste()
    except Exception: old_clipboard = ""
    pyperclip.copy(text)
    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")
    def restore():
        time.sleep(1.0)
        try: pyperclip.copy(old_clipboard)
        except Exception: pass
    threading.Thread(target=restore, daemon=True).start()
    threading.Thread(target=winsound.Beep, args=BEEP_DONE, daemon=True).start()

def on_hotkey():
    global recording
    if not hotkey_lock.acquire(blocking=False): return
    try:
        if model is None:
            threading.Thread(target=winsound.Beep, args=BEEP_ERROR, daemon=True).start()
            return
        if not recording:
            start_recording()
        else:
            audio = stop_recording()
            if audio is not None:
                def _run():
                    try:
                        text = transcribe(audio)
                        paste_text(text)
                    except Exception as e:
                        threading.Thread(target=winsound.Beep, args=BEEP_ERROR, daemon=True).start()
                    finally:
                        update_tray_icon(ICON_IDLE, "Dictation — Ready (Alt+C / Alt+Z)")
                threading.Thread(target=_run, daemon=True).start()
    finally:
        hotkey_lock.release()

def on_hotkey_ptt():
    global recording
    if not hotkey_lock.acquire(blocking=False): return
    try:
        if model is None:
            threading.Thread(target=winsound.Beep, args=BEEP_ERROR, daemon=True).start()
            return
        if not recording:
            if start_recording():
                user32 = ctypes.windll.user32
                # VK_MENU = 0x12 (Alt), VK_Z = 0x5A (Z)
                while (user32.GetAsyncKeyState(0x12) & 0x8000) and (user32.GetAsyncKeyState(0x5A) & 0x8000):
                    time.sleep(0.02)
                audio = stop_recording()
                drain_msg = ctypes.wintypes.MSG()
                while user32.PeekMessageA(ctypes.byref(drain_msg), None, 0x0312, 0x0312, 1):
                    pass
                if audio is not None:
                    def _run():
                        try:
                            text = transcribe(audio)
                            paste_text(text)
                        except Exception as e:
                            threading.Thread(target=winsound.Beep, args=BEEP_ERROR, daemon=True).start()
                        finally:
                            update_tray_icon(ICON_IDLE, "Dictation — Ready (Alt+C / Alt+Z)")
                    threading.Thread(target=_run, daemon=True).start()
    finally:
        hotkey_lock.release()

def on_quit(icon, item):
    global app_running
    app_running = False
    icon.stop()

def setup_tray():
    global tray_icon
    menu = pystray.Menu(pystray.MenuItem("Whisper Dictation", None, enabled=False), pystray.Menu.SEPARATOR, pystray.MenuItem("Quit", on_quit))
    tray_icon = pystray.Icon("whisper_dictation", ICON_LOADING, "Dictation — Loading model...", menu)
    return tray_icon

def main():
    pyautogui.FAILSAFE = False
    icon = setup_tray()
    threading.Thread(target=lambda: load_model(), daemon=True).start()

    def hotkey_loop():
        user32 = ctypes.windll.user32
        MOD_ALT = 0x0001
        VK_C = 0x43
        VK_Z = 0x5A
        msg = ctypes.wintypes.MSG()
        user32.PeekMessageA(ctypes.byref(msg), None, 0, 0, 0)
        reg_c = user32.RegisterHotKey(None, 1, MOD_ALT, VK_C)
        reg_z = user32.RegisterHotKey(None, 2, MOD_ALT, VK_Z)
        if not reg_c and not reg_z: return
        while user32.GetMessageA(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:
                if msg.wParam == 1: on_hotkey()
                elif msg.wParam == 2: on_hotkey_ptt()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageA(ctypes.byref(msg))

    threading.Thread(target=hotkey_loop, daemon=True).start()
    icon.run()

if __name__ == "__main__":
    main()
```

---

## Troubleshooting & customization

### Run in Debug Mode (with Console window)
Rename the script from `dictation.pyw` to `dictation.py`, edit `launch.vbs` to use `python.exe` instead of `pythonw.exe`, and execute it in terminal. This will show startup and runtime errors (e.g. audio device failure, model download logs).

### Window Privilege Isolation (UIPI)
If you focus on an Administrator-elevated window (e.g. Task Manager, or CMD run as Administrator), your global hotkeys will not work unless the Python process is also running as an Administrator.

### Change the hotkeys
To change hotkeys, modify `VK_C`/`VK_Z` inside `dictation.pyw`'s `hotkey_loop` using Windows Virtual Key codes (e.g. `0x44` for 'D', `0x58` for 'X'). Modify the modifiers as well (`0x0001` is `MOD_ALT`, `0x0002` is `MOD_CONTROL`). Remember to update the matching keycodes in `on_hotkey_ptt`'s `GetAsyncKeyState()` checks if changing PTT.
# whisper-dictation
