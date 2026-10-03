"""
whisper_service.py – fast, single-load transcription service.

Optimisations vs the original:
  • base.en  instead of small  (approx 3x faster, same accuracy for English)
  • beam_size=1                 (greedy decode, fastest)
  • compute_type="int8"         (already was int8 – kept)
  • language="en"               (skip language-detection overhead)
  • vad_filter=True             (skips silence – kept)
  • 16 kHz mono WAV conversion  (gives Whisper exactly what it wants,
                                 avoids internal re-sampling overhead)
  • Model loaded ONCE at import  (not per-request)
  • Timing logged for profiling
"""

import io
import os
import time
import logging
import tempfile

import av                          # PyAV – already in requirements (av==18.x)
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# ── Load model ONCE at import time ──────────────────────────────────────────
# Use WHISPER_MODEL env-var to override (e.g. "small" / "base.en" / "tiny").
# Default: small – multilingual, much higher accuracy for medical/accented speech.
_MODEL_NAME = os.getenv("WHISPER_MODEL", "small")

_t0 = time.perf_counter()
logger.info("[whisper] Loading model '%s' ...", _MODEL_NAME)
try:
    _model = WhisperModel(_MODEL_NAME, device="cpu", compute_type="int8")
except Exception as ex:
    logger.warning("[whisper] Failed to load %s (%s), falling back to base.en", _MODEL_NAME, ex)
    _MODEL_NAME = "base.en"
    _model = WhisperModel(_MODEL_NAME, device="cpu", compute_type="int8")
logger.info("[whisper] Model loaded in %.1f s", time.perf_counter() - _t0)

MEDICAL_HINT = (
    "Doctor-patient medical consultation. "
    "Symptoms, medications, dosage, diagnosis."
)


# ── Audio helpers ────────────────────────────────────────────────────────────

def _to_wav16k(src_path: str) -> str:
    """
    Convert any audio file to a 16 kHz mono PCM WAV in a temp file.
    Returns the new path (caller must delete it).
    Uses PyAV (libav) – already installed as 'av'.
    """
    fd, dst_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    try:
        with av.open(src_path) as in_c:
            in_stream = next(s for s in in_c.streams if s.type == "audio")
            resampler = av.AudioResampler(
                format="s16",
                layout="mono",
                rate=16000,
            )
            with av.open(dst_path, "w", format="wav") as out_c:
                out_stream = out_c.add_stream("pcm_s16le", rate=16000)
                out_stream.layout = "mono"
                for frame in in_c.decode(in_stream):
                    for r_frame in resampler.resample(frame):
                        for pkt in out_stream.encode(r_frame):
                            out_c.mux(pkt)
                # flush encoder
                for pkt in out_stream.encode(None):
                    out_c.mux(pkt)
    except Exception:
        delete_file(dst_path)
        raise

    return dst_path


# ── Public API ───────────────────────────────────────────────────────────────

def _transcribe_gemini(wav_path: str) -> str | None:
    """
    High-accuracy medical audio transcription using Gemini 3.5 Transcribe.
    Returns plain text or None if unavailable.
    """
    try:
        from services import gemini_service
        from google.genai import types

        with open(wav_path, "rb") as f:
            wav_bytes = f.read()

        part = types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")
        resp = gemini_service.client.models.generate_content(
            model="gemini-3.5-transcribe",
            contents=[part],
        )
        for p in resp.candidates[0].content.parts:
            if hasattr(p, "audio_transcription") and p.audio_transcription:
                text = getattr(p.audio_transcription, "text", "")
                if text and text.strip():
                    return text.strip()
            if hasattr(p, "text") and p.text and p.text.strip():
                return p.text.strip()
    except Exception as ex:
        import traceback
        logger.error("[transcribe] Gemini audio transcription error: %s\n%s", ex, traceback.format_exc())
    return None


def transcribe_path(path: str) -> str:
    """
    Transcribe an audio file with maximum accuracy:
    1. Converts input audio to 16 kHz mono WAV.
    2. Primary: Gemini 3.5 Transcribe (state-of-the-art medical speech model).
    3. Standby fallback: Local faster-whisper (small, beam_size=3, VAD).
    Returns plain text.
    """
    wav_path = None
    try:
        t0 = time.perf_counter()
        wav_path = _to_wav16k(path)
        logger.info("[TIMING] audio_conversion=%.2fs", time.perf_counter() - t0)

        # ── Primary: Gemini 3.5 Transcribe
        t1 = time.perf_counter()
        gemini_text = _transcribe_gemini(wav_path)
        if gemini_text:
            logger.info("[TIMING] gemini_transcription=%.2fs", time.perf_counter() - t1)
            return gemini_text

        # ── Fallback: Local faster-whisper
        t2 = time.perf_counter()
        segments, info = _model.transcribe(
            wav_path,
            beam_size=3,
            vad_filter=True,
            initial_prompt=MEDICAL_HINT,
        )
        text = " ".join(s.text.strip() for s in segments if s.text.strip()).strip()
        logger.info(
            "[TIMING] whisper_transcription=%.2fs (lang=%s, audio_dur=%.1fs)",
            time.perf_counter() - t2,
            info.language,
            info.duration or 0,
        )
        return text
    finally:
        delete_file(wav_path)


def save_temp(file_storage) -> str:
    """Save a Werkzeug FileStorage to a temp file. Returns the path."""
    suffix = os.path.splitext(file_storage.filename or "")[1] or ".webm"
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        file_storage.save(path)
    except Exception:
        delete_file(path)
        raise
    return path


def delete_file(path: str) -> None:
    """Safely remove a temp file (ignores errors)."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

