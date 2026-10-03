import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import whisper_service, gemini_service

audio_file = "drpatconvo1.m4a"
if not os.path.exists(audio_file):
    audio_file = os.path.join(os.path.dirname(__file__), "drpatconvo1.m4a")

print(f"Transcribing {audio_file} with high-accuracy transcription pipeline...")
raw_transcript = whisper_service.transcribe_path(audio_file)
print("\n--- RAW TRANSCRIPT ---")
print(raw_transcript)

# Format into dialogue turns
formatted_transcript = gemini_service.format_dialogue(raw_transcript)
print("\n--- FORMATTED DIALOGUE ---")
print(formatted_transcript)

out_path = "transcript.txt"
if not os.path.isabs(out_path):
    out_path = os.path.join(os.path.dirname(__file__), "transcript.txt")

with open(out_path, "w", encoding="utf-8") as f:
    f.write(formatted_transcript)

print(f"\nSaved to {out_path}")