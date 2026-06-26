"""
Whisper-Powered Dictation — Global Hotkey Alt+C
================================================
Press Alt+C to start recording, press Alt+C again to stop and transcribe.
Transcribed text is pasted at the current cursor position.
Runs in the system tray with status indicators.
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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WHISPER_MODEL = "base.en"
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"

# Beep tones (frequency_hz, duration_ms)
BEEP_START = (800, 150)
BEEP_STOP = (600, 150)
BEEP_DONE = (1000, 100)
BEEP_ERROR = (300, 300)


# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
recording = False
audio_chunks: list[np.ndarray] = []
stream: sd.InputStream | None = None
model = None
model_lock = threading.Lock()
tray_icon: pystray.Icon | None = None
app_running = True
hotkey_lock = threading.Lock()


# ---------------------------------------------------------------------------
# System tray icon generation
# ---------------------------------------------------------------------------
def create_icon_image(color: str = "#4a90d9", ring: str | None = None) -> Image.Image:
    """Create a 64x64 tray icon — a microphone-style circle with optional ring."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle
    margin = 4
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=color,
        outline="#ffffff",
        width=2,
    )

    # Mic icon (simplified: vertical bar + base)
    cx, cy = size // 2, size // 2
    bar_w, bar_h = 6, 18
    draw.rounded_rectangle(
        [cx - bar_w, cy - bar_h + 2, cx + bar_w, cy + 6],
        radius=bar_w,
        fill="#ffffff",
    )
    # Mic base arc
    draw.arc(
        [cx - 12, cy - 6, cx + 12, cy + 16],
        start=0, end=180,
        fill="#ffffff",
        width=2,
    )
    # Stand line
    draw.line([cx, cy + 16, cx, cy + 22], fill="#ffffff", width=2)
    draw.line([cx - 8, cy + 22, cx + 8, cy + 22], fill="#ffffff", width=2)

    # Optional recording ring
    if ring:
        draw.ellipse(
            [1, 1, size - 1, size - 1],
            outline=ring,
            width=3,
        )

    return img


ICON_IDLE = create_icon_image("#4a90d9")
ICON_RECORDING = create_icon_image("#e74c3c", ring="#ff0000")
ICON_TRANSCRIBING = create_icon_image("#f39c12", ring="#ffaa00")
ICON_LOADING = create_icon_image("#95a5a6")


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------
def load_model():
    """Load the faster-whisper model (called once at startup)."""
    global model
    from faster_whisper import WhisperModel

    print(f"[dictation] Loading Whisper model '{WHISPER_MODEL}'...", flush=True)
    model = WhisperModel(
        WHISPER_MODEL,
        device="cpu",
        compute_type="int8",
    )
    print("[dictation] Model loaded. Ready for dictation!", flush=True)
    update_tray_icon(ICON_IDLE, "Dictation — Ready (Alt+C / Alt+Z)")


# ---------------------------------------------------------------------------
# Tray icon management
# ---------------------------------------------------------------------------
def update_tray_icon(icon_image: Image.Image, tooltip: str | None = None):
    """Update the system tray icon image and tooltip."""
    if tray_icon:
        tray_icon.icon = icon_image
        if tooltip:
            tray_icon.title = tooltip


# ---------------------------------------------------------------------------
# Audio recording
# ---------------------------------------------------------------------------
def audio_callback(indata, frames, time_info, status):
    """Called by sounddevice for each audio block."""
    if status:
        print(f"[dictation] Audio status: {status}", flush=True)
    audio_chunks.append(indata.copy())


def start_recording():
    """Begin capturing audio from the default microphone."""
    global recording, stream, audio_chunks

    audio_chunks = []
    try:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=audio_callback,
            blocksize=1024,
        )
        stream.start()
    except Exception as e:
        print(f"[dictation] ERROR starting recording: {e}", flush=True)
        threading.Thread(target=winsound.Beep, args=BEEP_ERROR, daemon=True).start()
        return False

    recording = True
    update_tray_icon(ICON_RECORDING, "Dictation — Recording...")
    # Play start beep in a thread so we don't block
    threading.Thread(target=winsound.Beep, args=BEEP_START, daemon=True).start()
    print("[dictation] Recording started.", flush=True)
    return True


def stop_recording() -> np.ndarray | None:
    """Stop recording and return the captured audio as a numpy array."""
    global recording, stream

    if stream:
        stream.stop()
        stream.close()
        stream = None
    recording = False

    threading.Thread(target=winsound.Beep, args=BEEP_STOP, daemon=True).start()

    if not audio_chunks:
        print("[dictation] No audio captured.", flush=True)
        update_tray_icon(ICON_IDLE, "Dictation — Ready (Alt+C / Alt+Z)")
        return None

    audio = np.concatenate(audio_chunks, axis=0).flatten()
    duration = len(audio) / SAMPLE_RATE
    print(f"[dictation] Recorded {duration:.1f}s of audio.", flush=True)

    # Ignore very short recordings (< 0.3s) — likely accidental
    if duration < 0.3:
        print("[dictation] Recording too short, ignoring.", flush=True)
        update_tray_icon(ICON_IDLE, "Dictation — Ready (Alt+C / Alt+Z)")
        return None

    return audio


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
def transcribe(audio: np.ndarray) -> str:
    """Transcribe audio using faster-whisper."""
    update_tray_icon(ICON_TRANSCRIBING, "Dictation — Transcribing...")
    print("[dictation] Transcribing...", flush=True)

    with model_lock:
        segments, info = model.transcribe(
            audio,
            beam_size=5,
            language="en",
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
            ),
        )
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())

    text = " ".join(text_parts).strip()
    print(f"[dictation] Transcription: {text!r}", flush=True)
    return text


# ---------------------------------------------------------------------------
# Text insertion
# ---------------------------------------------------------------------------
def paste_text(text: str):
    """Insert text at the cursor position via clipboard paste."""
    if not text:
        return

    # Save current clipboard
    try:
        old_clipboard = pyperclip.paste()
    except Exception:
        old_clipboard = ""

    # Set new text and paste
    pyperclip.copy(text)
    time.sleep(0.05)

    # Use pyautogui to press Ctrl+V
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.1)

    # Restore old clipboard after a short delay
    def restore():
        time.sleep(1.0)
        try:
            pyperclip.copy(old_clipboard)
        except Exception:
            pass

    threading.Thread(target=restore, daemon=True).start()

    # Success beep
    threading.Thread(target=winsound.Beep, args=BEEP_DONE, daemon=True).start()


# ---------------------------------------------------------------------------
# Hotkey handler
# ---------------------------------------------------------------------------
def on_hotkey():
    """Toggle recording on/off when Alt+C is pressed."""
    global recording

    # Prevent re-entrant calls
    if not hotkey_lock.acquire(blocking=False):
        return
    try:
        print("[dictation] Alt+C pressed!", flush=True)

        if model is None:
            # Model still loading
            threading.Thread(
                target=winsound.Beep, args=BEEP_ERROR, daemon=True
            ).start()
            print("[dictation] Model not loaded yet, please wait.", flush=True)
            return

        if not recording:
            start_recording()
        else:
            audio = stop_recording()
            if audio is not None:
                # Transcribe in a thread to keep hotkey responsive
                def _transcribe_and_paste():
                    try:
                        text = transcribe(audio)
                        paste_text(text)
                    except Exception as e:
                        print(f"[dictation] Transcription error: {e}", flush=True)
                        threading.Thread(
                            target=winsound.Beep, args=BEEP_ERROR, daemon=True
                        ).start()
                    finally:
                        update_tray_icon(ICON_IDLE, "Dictation — Ready (Alt+C / Alt+Z)")

                threading.Thread(target=_transcribe_and_paste, daemon=True).start()
    finally:
        hotkey_lock.release()


def on_hotkey_ptt():
    """Push-to-talk recording when Alt+Z is pressed. Recording stops when Alt+Z is released."""
    global recording

    # Prevent re-entrant calls
    if not hotkey_lock.acquire(blocking=False):
        return
    try:
        print("[dictation] Alt+Z pressed (PTT)!", flush=True)

        if model is None:
            # Model still loading
            threading.Thread(
                target=winsound.Beep, args=BEEP_ERROR, daemon=True
            ).start()
            print("[dictation] Model not loaded yet, please wait.", flush=True)
            return

        if not recording:
            if start_recording():
                # Wait for keys to be released
                user32 = ctypes.windll.user32
                # VK_MENU = 0x12 (Alt), VK_Z = 0x5A (Z)
                # Keep looping as long as both Alt and Z are physically held down
                while (user32.GetAsyncKeyState(0x12) & 0x8000) and (user32.GetAsyncKeyState(0x5A) & 0x8000):
                    time.sleep(0.02)
                
                print("[dictation] Alt+Z released!", flush=True)
                audio = stop_recording()

                # Drain any queued WM_HOTKEY (0x0312) messages from keyboard auto-repeat
                drain_msg = ctypes.wintypes.MSG()
                while user32.PeekMessageA(ctypes.byref(drain_msg), None, 0x0312, 0x0312, 1):
                    pass

                if audio is not None:
                    # Transcribe in a thread to keep hotkey responsive
                    def _transcribe_and_paste():
                        try:
                            text = transcribe(audio)
                            paste_text(text)
                        except Exception as e:
                            print(f"[dictation] Transcription error: {e}", flush=True)
                            threading.Thread(
                                target=winsound.Beep, args=BEEP_ERROR, daemon=True
                            ).start()
                        finally:
                            update_tray_icon(ICON_IDLE, "Dictation — Ready (Alt+C / Alt+Z)")

                    threading.Thread(target=_transcribe_and_paste, daemon=True).start()
    finally:
        hotkey_lock.release()


# ---------------------------------------------------------------------------
# System tray setup
# ---------------------------------------------------------------------------
def on_quit(icon, item):
    """Exit the application."""
    global app_running
    print("[dictation] Quitting...", flush=True)
    app_running = False
    icon.stop()


def setup_tray():
    """Create and run the system tray icon."""
    global tray_icon

    menu = pystray.Menu(
        pystray.MenuItem("Whisper Dictation", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    tray_icon = pystray.Icon(
        "whisper_dictation",
        ICON_LOADING,
        "Dictation — Loading model...",
        menu,
    )

    return tray_icon


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("[dictation] Starting Whisper Dictation...", flush=True)

    # Disable pyautogui failsafe (moving mouse to corner won't crash)
    pyautogui.FAILSAFE = False

    # Set up system tray
    icon = setup_tray()

    # Load model in background
    def _load():
        try:
            load_model()
        except Exception as e:
            print(f"[dictation] FATAL: Failed to load model: {e}", flush=True)
            update_tray_icon(ICON_IDLE, f"Dictation — Error: {e}")

    model_thread = threading.Thread(target=_load, daemon=True)
    model_thread.start()

    # Register global hotkey using Windows API (RegisterHotKey)
    def hotkey_loop():
        user32 = ctypes.windll.user32
        MOD_ALT = 0x0001
        VK_C = 0x43
        VK_Z = 0x5A
        # Force the creation of the message queue for this thread
        msg = ctypes.wintypes.MSG()
        user32.PeekMessageA(ctypes.byref(msg), None, 0, 0, 0)

        # Register both hotkeys
        reg_c = user32.RegisterHotKey(None, 1, MOD_ALT, VK_C)
        reg_z = user32.RegisterHotKey(None, 2, MOD_ALT, VK_Z)

        if reg_c:
            print("[dictation] Global hotkey registered: Alt+C (Toggle)", flush=True)
        else:
            print("[dictation] FAILED to register Alt+C (Toggle)", flush=True)

        if reg_z:
            print("[dictation] Global hotkey registered: Alt+Z (Push-to-Talk)", flush=True)
        else:
            print("[dictation] FAILED to register Alt+Z (Push-to-Talk)", flush=True)

        if not reg_c and not reg_z:
            print("[dictation] Both hotkeys failed to register. Exiting.", flush=True)
            return
        
        while user32.GetMessageA(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                if msg.wParam == 1:
                    on_hotkey()
                elif msg.wParam == 2:
                    on_hotkey_ptt()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageA(ctypes.byref(msg))

    hk_thread = threading.Thread(target=hotkey_loop, daemon=True)
    hk_thread.start()

    # Run the tray icon (this blocks)
    icon.run()

    # Cleanup
    print("[dictation] Exited.", flush=True)


if __name__ == "__main__":
    main()
