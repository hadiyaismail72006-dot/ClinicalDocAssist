from faster_whisper import WhisperModel

model = WhisperModel("small", device="cpu", compute_type="int8")
segments, info = model.transcribe("drpatconvo1.m4a", beam_size=5)

full_transcript = ""
for segment in segments:
    line = f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}"
    print(line)
    full_transcript += segment.text.strip() + " "

print("\n--- FULL TRANSCRIPT ---")
print(full_transcript)

# Save the plain transcript (no timestamps) to a text file
with open("transcript.txt", "w", encoding="utf-8") as f:
    f.write(full_transcript)

print("\nSaved to transcript.txt")
     