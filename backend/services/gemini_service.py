"""
gemini_service.py – Gemini API calls for clinical note and patient summary.

Optimisations vs the original:
  • generate_all() merges note + summary into ONE Gemini call (used at approve time)
    → saves one full round-trip (~3-8 s)
  • max_output_tokens=2048 cap avoids open-ended generation timeouts
  • temperature=0.1  (more deterministic, less verbose, slightly faster)
  • Compact prompt  (fewer input tokens = faster TTFT)
  • Retry: 2x main + 1x fallback  (original was 2+2, removed one redundant retry)
  • Timing logged for profiling
"""

import json
import time
import logging

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from config import GEMINI_API_KEY, NOTE_MODEL, FALLBACK_MODEL

logger = logging.getLogger(__name__)
client = genai.Client(api_key=GEMINI_API_KEY)

# ── System prompts ───────────────────────────────────────────────────────────

NOTE_SYSTEM = """You are a clinical documentation assistant.
Convert the transcript into a structured clinical note.
Rules:
- Use ONLY what is in the transcript. Never invent diagnoses, doses, or findings.
- Missing info → "Not discussed" or empty list.
- Infer speaker from context; flag unclear speaker in missing_information.
- Prescribed medicines must appear in both medications and plan.
Return ONLY JSON with keys:
chief_complaint(str), history_of_present_illness(str), symptoms(list[str]),
past_medical_history(str), medications(list[{name,dose,frequency}]),
allergies(str), examination_findings(str), assessment(str),
plan(list[str]), follow_up(str), missing_information(list[str])."""

SUMMARY_SYSTEM = """You write patient-friendly summaries from an approved clinical note.
Rules:
- Simple words (6th-grade level). Explain any medical term briefly.
- Use ONLY the approved note. No new advice, diagnoses, or medicines.
- Warm and clear. Do not alarm the patient.
Return ONLY JSON with keys:
summary(str, 2-4 sentences), what_the_doctor_found(str),
medicines(list[{name,how_to_take}]), what_to_do(list[str]),
warning_signs(list[str], only if in the note), follow_up(str)."""

COMBINED_SYSTEM = """You are a clinical documentation assistant.
From the transcript, produce TWO JSON objects in one response.

Step 1 – clinical note (key "note"):
- Use ONLY transcript content. Never invent.
- Missing info → "Not discussed" or [].
- Prescribed medicines in both medications and plan.
Keys: chief_complaint, history_of_present_illness, symptoms, past_medical_history,
medications([{name,dose,frequency}]), allergies, examination_findings, assessment,
plan, follow_up, missing_information.

Step 2 – patient summary (key "summary"), written from the note above:
- Simple language (6th-grade). Explain medical terms briefly.
- Warm, not alarming. No new advice.
Keys: summary, what_the_doctor_found, medicines([{name,how_to_take}]),
what_to_do, warning_signs(only if mentioned), follow_up.

Return ONLY: {"note": {...}, "summary": {...}}"""


# ── Internal call helper ─────────────────────────────────────────────────────

def _json_call(system: str, content: str, label: str = "") -> dict:
    """Call Gemini and return parsed JSON. Retries on transient errors."""
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        temperature=0.1,
        max_output_tokens=2048,
    )
    last_error = None
    # Try main model twice, then fallback once
    for model in (NOTE_MODEL, NOTE_MODEL, FALLBACK_MODEL):
        t0 = time.perf_counter()
        try:
            resp = client.models.generate_content(
                model=model, contents=content, config=config
            )
            result = json.loads(resp.text)
            logger.info(
                "[TIMING] gemini_%s model=%s %.2fs",
                label, model, time.perf_counter() - t0,
            )
            return result
        except genai_errors.ServerError as e:      # 5xx overloaded
            last_error = e
            logger.warning("[gemini] ServerError on %s, retrying…", model)
            time.sleep(1)
        except genai_errors.ClientError as e:      # 429 rate-limit
            if getattr(e, "code", None) == 429:
                last_error = e
                logger.warning("[gemini] 429 rate-limit on %s, retrying…", model)
                time.sleep(3)
            else:
                raise                              # bad key / bad model → propagate
        except (json.JSONDecodeError, KeyError) as e:
            last_error = e
            logger.warning("[gemini] JSON parse error from %s: %s", model, e)
            time.sleep(0.5)

    raise last_error or RuntimeError("Gemini call failed with no error captured")


# ── Public API ───────────────────────────────────────────────────────────────

def generate_clinical_note(transcript: str) -> dict:
    """Generate a structured clinical note from a transcript."""
    return _json_call(
        NOTE_SYSTEM,
        f"Transcript:\n{transcript}",
        label="note",
    )


def generate_patient_summary(approved_note: dict) -> dict:
    """Generate a patient-friendly summary from an approved clinical note."""
    return _json_call(
        SUMMARY_SYSTEM,
        f"Approved clinical note:\n{json.dumps(approved_note, indent=2)}",
        label="summary",
    )


def generate_note_and_summary(transcript: str) -> tuple[dict, dict]:
    """
    Single Gemini call that returns BOTH the clinical note and patient summary.
    Use at approve-time instead of calling generate_clinical_note +
    generate_patient_summary separately to save one full API round-trip.

    Returns: (note_dict, summary_dict)
    """
    result = _json_call(
        COMBINED_SYSTEM,
        f"Transcript:\n{transcript}",
        label="combined",
    )
    if "note" not in result or "summary" not in result:
        raise ValueError(f"Gemini combined response missing keys: {list(result.keys())}")
    return result["note"], result["summary"]


def format_dialogue(raw_transcript: str) -> str:
    """
    Format speech transcript into clean Doctor: and Patient: dialogue turns.
    Returns original text on error or if speaker tags already exist.
    """
    if not raw_transcript or not raw_transcript.strip():
        return raw_transcript
    if "Doctor:" in raw_transcript or "Patient:" in raw_transcript:
        return raw_transcript

    prompt = f"""You are a clinical transcription assistant.
Format the following spoken consultation transcript into clear dialogue lines prefixed with 'Doctor:' or 'Patient:'.
Rules:
- Identify speaker based on context (doctor asks questions, prescribes medicines, advises; patient reports symptoms, history).
- Keep every spoken word faithfully without adding or inventing any facts.
- Output ONLY the formatted dialogue lines (no code fences, no extra preamble).

Transcript:
{raw_transcript}"""

    try:
        resp = client.models.generate_content(
            model=NOTE_MODEL,
            contents=prompt,
        )
        text = resp.text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:]).strip()
        return text if text else raw_transcript
    except Exception as e:
        logger.warning("[gemini] format_dialogue fallback: %s", e)
        return raw_transcript