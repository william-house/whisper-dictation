from faster_whisper import WhisperModel
WhisperModel("base.en", device="cpu", compute_type="int8")
print("Model downloaded successfully.")
