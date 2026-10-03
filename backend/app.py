"""
app.py - Flask backend for Clinical Documentation Assistant.

Performance changes vs original:
  - Audio upload returns a job_id immediately (HTTP 202); transcription
    runs in a background thread.
  - GET /api/jobs/<job_id> lets the frontend poll for progress/result.
  - Timing is logged at every stage.
  - use_reloader=False prevents the debug reloader from loading the
    Whisper model twice.
  - All existing endpoints and behaviour are preserved unchanged.
"""

import os
import secrets
import time
import threading
import logging
from functools import wraps

from flask import Flask, request, jsonify, g
from flask_cors import CORS
from itsdangerous import URLSafeTimedSerializer, BadSignature
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash

import store
from services import whisper_service
from services import gemini_service as gs
from services import scrub_service
from services import generic_service

# ── Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Flask app
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB audio limit

CORS(app, allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
TOKEN_TTL = 8 * 60 * 60
ser = URLSafeTimedSerializer(SECRET_KEY)

KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def make_key():
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(8))


def err(msg, code=400):
    return jsonify({"error": msg}), code


# ── Error handlers
@app.errorhandler(HTTPException)
def http_err(e):
    msgs = {404: "Not found", 405: "Method not allowed", 413: "File too large (max 20 MB)"}
    return err(msgs.get(e.code, e.description), e.code)


@app.errorhandler(Exception)
def any_err(e):
    app.logger.error("Unhandled %s", type(e).__name__)
    return err("Server error. Please try again.", 500)


# ── Auth helpers
def require(role):
    """Route decorator: valid Bearer token with the right role. Sets g.uid."""
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            h = request.headers.get("Authorization", "")
            if not h.startswith("Bearer "):
                return err("Please log in.", 401)
            try:
                t = ser.loads(h[7:], max_age=TOKEN_TTL)
            except BadSignature:
                return err("Session expired. Please log in again.", 401)
            if t.get("r") != role:
                return err("You do not have access to this.", 403)
            g.uid = t["u"]
            return f(*a, **k)
        return wrapper
    return deco


_attempts = {}


def locked(key):
    return time.time() < _attempts.get(key, {}).get("locked_until", 0)


def record_fail(key):
    s = _attempts.setdefault(key, {"fails": 0, "locked_until": 0})
    s["fails"] += 1
    if s["fails"] >= 5:
        s.update(fails=0, locked_until=time.time() + 300)


def own_consultation(cid):
    """Returns (consultation, error). Doctors only reach their own patients."""
    c = store.get(cid)
    p = store.get_patient(c["patient_id"]) if c else None
    if not c or not p or p["doctor_id"] != g.uid:
        return None, err("Consultation not found", 404)
    return c, None


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


# ── AUTH
@app.post("/api/auth/doctor-register")
def doctor_register():
    d = request.get_json(silent=True) or {}
    name = str(d.get("doctor_name", "")).strip()
    did = str(d.get("doctor_id", "")).strip()
    pk = str(d.get("passkey", ""))
    if not name or not did or not pk:
        return err("Doctor name, ID and passkey are required.")
    if any(ch.isspace() for ch in did) or len(did) > 40:
        return err("Doctor ID cannot contain spaces (max 40 characters).")
    if len(pk) < 6:
        return err("Passkey must be at least 6 characters.")
    if not store.create_doctor(did, name, generate_password_hash(pk)):
        return err("That Doctor ID is already taken.", 409)
    return jsonify({"ok": True}), 201


@app.post("/api/auth/doctor-login")
def doctor_login():
    d = request.get_json(silent=True) or {}
    did, pk = str(d.get("doctor_id", "")).strip(), str(d.get("passkey", ""))
    key = "d:" + did
    if locked(key):
        return err("Too many wrong attempts. Try again in a few minutes.", 429)
    doc = store.get_doctor(did)
    if not doc or not check_password_hash(doc["pw_hash"], pk):
        record_fail(key)
        return err("Incorrect Doctor ID or passkey.", 401)
    _attempts.pop(key, None)
    return jsonify({"token": ser.dumps({"r": "doctor", "u": did}),
                    "doctor_id": did, "doctor_name": doc["doctor_name"]})


@app.post("/api/auth/patient-login")
def patient_login():
    d = request.get_json(silent=True) or {}
    pid, pk = str(d.get("patient_id", "")).strip(), str(d.get("passkey", "")).strip().upper()
    key = "p:" + pid
    if locked(key):
        return err("Too many wrong attempts. Try again in a few minutes.", 429)
    p = store.get_patient(pid)
    if not p or not p.get("key_hash") or not check_password_hash(p["key_hash"], pk):
        record_fail(key)
        return err("Incorrect Patient ID or passkey.", 401)
    _attempts.pop(key, None)
    return jsonify({"token": ser.dumps({"r": "patient", "u": pid}), "patient_id": pid})


# ── DOCTOR: PATIENTS
@app.get("/api/patients")
@require("doctor")
def list_patients():
    return jsonify(store.list_patients(g.uid))


@app.post("/api/patients/<pid>/consultations")
@require("doctor")
def create_consultation(pid):
    pid = pid.strip()
    if not pid or len(pid) > 40 or not all(ch.isalnum() or ch == "-" for ch in pid):
        return err("Patient ID may contain only letters, numbers and dashes (max 40).")
    doc = store.get_doctor(g.uid)
    c, problem = store.create_consultation(pid, g.uid, doc["doctor_name"] if doc else "")
    if problem:
        return err("That Patient ID is already used by another doctor.", 403)
    return jsonify(c), 201


@app.delete("/api/patients/<pid>")
@require("doctor")
def delete_patient(pid):
    p = store.get_patient(pid)
    if not p or p["doctor_id"] != g.uid:
        return err("Patient not found", 404)
    store.delete_patient(pid)
    return jsonify({"ok": True})


@app.post("/api/patients/<pid>/reset-passkey")
@require("doctor")
def reset_passkey(pid):
    p = store.get_patient(pid)
    if not p or p["doctor_id"] != g.uid:
        return err("Patient not found", 404)
    key = make_key()
    store.set_patient_key(pid, generate_password_hash(key))
    _attempts.pop("p:" + pid, None)
    return jsonify({"passkey": key})


@app.get("/api/consultations/<cid>")
@require("doctor")
def get_consultation(cid):
    c, e = own_consultation(cid)
    if e:
        return e
    ps = c.get("patient_summary")
    if isinstance(ps, dict):
        if not ps.get("generic_suggestions") or any(x is None for x in ps.get("generic_suggestions", [])):
            if ps.get("medicines"):
                ps["generic_suggestions"] = generic_service.suggest_for_medications(ps["medicines"])
        c["generic_suggestions"] = ps.get("generic_suggestions")
    note = c.get("note")
    if isinstance(note, dict) and note.get("medications"):
        c["note_generic_suggestions"] = generic_service.suggest_for_medications(note["medications"])
    return jsonify(c)


@app.delete("/api/consultations/<cid>")
@require("doctor")
def delete_consultation(cid):
    c, e = own_consultation(cid)
    if e:
        return e
    store.delete_consultation(cid)
    return jsonify({"ok": True})


# ── ASYNC AUDIO PROCESSING
# Jobs stored in memory (resets on server restart; consultation store is source of truth).
# Job shape: { status, step, result, error, ts }

_jobs: dict = {}
_jobs_lock = threading.Lock()
JOB_TTL = 3600  # 1 hour

# Maps cid -> active note-generation job_id so the endpoint can re-use a
# job that was pre-started by the audio pipeline instead of starting a new one.
_cid_note_job: dict = {}
_cid_note_job_lock = threading.Lock()


def _new_job() -> str:
    jid = secrets.token_urlsafe(12)
    with _jobs_lock:
        _jobs[jid] = {"status": "pending", "step": "Queued",
                      "result": None, "error": None, "ts": time.time()}
    return jid


def _set_job(jid: str, **kwargs):
    with _jobs_lock:
        if jid in _jobs:
            _jobs[jid].update(kwargs)


def _cleanup_old_jobs():
    cutoff = time.time() - JOB_TTL
    with _jobs_lock:
        old = [k for k, v in _jobs.items() if v.get("ts", 0) < cutoff]
        for k in old:
            del _jobs[k]


def _run_note_generation(note_jid: str, cid: str, transcript: str):
    """
    Background thread: call Gemini to generate the clinical note and save it.
    Tracks progress via the shared _jobs dict so the frontend can poll.
    Also cleans up _cid_note_job when finished.
    """
    t0 = time.perf_counter()
    try:
        _set_job(note_jid, status="running", step="Writing clinical note...")
        note = gs.generate_clinical_note(transcript)
        result = store.update(cid, note=note, status="note_generated")
        logger.info("[TIMING] note_generation=%.2fs", time.perf_counter() - t0)
        _set_job(note_jid, status="done", step="Done", result=result)
    except Exception as ex:
        logger.error("[note-job %s] Failed: %s", note_jid, type(ex).__name__)
        _set_job(note_jid, status="error",
                 error="Note generation failed. Please try again.")
    finally:
        with _cid_note_job_lock:
            # Only clear if this job is still the registered one
            if _cid_note_job.get(cid) == note_jid:
                del _cid_note_job[cid]


def _run_audio_pipeline(jid: str, cid: str, src_path: str):
    """
    Background thread: transcribe -> scrub -> save transcript -> pre-generate note.
    Marking the audio job done as soon as the transcript is saved so the frontend
    can show the transcript immediately. Note generation then runs in its own job.
    src_path is a temp file owned by this thread; deleted when done.
    """
    t_total = time.perf_counter()
    try:
        _set_job(jid, status="transcribing", step="Transcribing audio...")
        logger.info("[job %s] Stage: transcription", jid)
        t0 = time.perf_counter()
        try:
            raw_text = whisper_service.transcribe_path(src_path)
        except Exception as ex:
            logger.error("[job %s] Transcription failed: %s", jid, type(ex).__name__)
            _set_job(jid, status="error",
                     error=f"Transcription failed: {type(ex).__name__}. Please try again.")
            return
        logger.info("[TIMING] transcription=%.2fs", time.perf_counter() - t0)

        _set_job(jid, step="Scrubbing sensitive data...")
        text = scrub_service.scrub(raw_text)

        _set_job(jid, step="Saving transcript...")
        result = store.update(cid, transcript=text, status="transcribed")

        logger.info("[TIMING] audio pipeline total=%.2fs", time.perf_counter() - t_total)
        _set_job(jid, status="done", step="Done", result=result)

        # ── Eagerly pre-generate the clinical note in the background so that
        # by the time the doctor reviews the transcript and clicks
        # "Generate Clinical Note" it is already done (instant response).
        note_jid = _new_job()
        with _cid_note_job_lock:
            _cid_note_job[cid] = note_jid
        threading.Thread(
            target=_run_note_generation,
            args=(note_jid, cid, text),
            daemon=True,
            name=f"note-{note_jid[:8]}",
        ).start()
        logger.info("[job %s] Pre-generating note in background job %s", jid, note_jid)

    except Exception as ex:
        logger.error("[job %s] Unexpected error: %s", jid, type(ex).__name__)
        _set_job(jid, status="error", error="Processing failed. Please try again.")
    finally:
        whisper_service.delete_file(src_path)


@app.post("/api/consultations/<cid>/audio")
@require("doctor")
def upload_audio(cid):
    """
    Accepts the audio file and immediately returns a job_id (HTTP 202).
    Poll GET /api/jobs/<job_id> for progress.
    """
    c, e = own_consultation(cid)
    if e:
        return e
    if c["status"] == "approved":
        return err("Already approved; consultation is locked", 409)
    f = request.files.get("audio")
    if not f:
        return err("Send audio as multipart field 'audio'")

    t0 = time.perf_counter()
    try:
        src_path = whisper_service.save_temp(f)
    except Exception as ex:
        return err(f"Failed to save audio: {type(ex).__name__}", 500)
    logger.info("[TIMING] audio_save=%.2fs", time.perf_counter() - t0)

    jid = _new_job()
    threading.Thread(
        target=_run_audio_pipeline, args=(jid, cid, src_path),
        daemon=True, name=f"audio-{jid[:8]}"
    ).start()

    logger.info("[job %s] Started for consultation %s", jid, cid)
    _cleanup_old_jobs()
    return jsonify({"job_id": jid, "status": "pending"}), 202


@app.get("/api/jobs/<jid>")
@require("doctor")
def get_job(jid):
    """Poll for audio processing progress. status: pending|transcribing|done|error"""
    with _jobs_lock:
        job = _jobs.get(jid)
    if not job:
        return err("Job not found", 404)
    out = {"status": job["status"], "step": job["step"]}
    if job["status"] == "done":
        out["result"] = job["result"]
    elif job["status"] == "error":
        out["error"] = job["error"]
    return jsonify(out)


# Dev helper for testing without audio
@app.post("/api/consultations/<cid>/transcript")
@require("doctor")
def set_transcript(cid):
    c, e = own_consultation(cid)
    if e:
        return e
    if c["status"] == "approved":
        return err("Already approved; consultation is locked", 409)
    text = (request.get_json(silent=True) or {}).get("transcript", "").strip()
    if not text:
        return err("'transcript' is required")
    return jsonify(store.update(cid, transcript=scrub_service.scrub(text), status="transcribed"))


@app.post("/api/consultations/<cid>/generate-note")
@require("doctor")
def generate_note(cid):
    """
    Fast path: if the note was pre-generated by the audio pipeline, return it
    immediately (200). Otherwise start an async job and return 202 + job_id
    so the frontend can poll. The frontend should handle both status codes.
    """
    c, e = own_consultation(cid)
    if e:
        return e
    if not c["transcript"]:
        return err("No transcript yet")
    if c["status"] == "approved":
        return err("Already approved; note is locked", 409)

    # ── Fast path: note already written to store (pre-generated) ──────────
    if c.get("note") and c["status"] == "note_generated":
        logger.info("[generate-note] Returning pre-generated note instantly for %s", cid)
        return jsonify(c)   # 200

    # ── Check if a background job is already generating the note ──────────
    with _cid_note_job_lock:
        existing_jid = _cid_note_job.get(cid)

    if existing_jid:
        with _jobs_lock:
            job = _jobs.get(existing_jid)
        if job and job["status"] not in ("done", "error"):
            # Still running – let the frontend poll it
            logger.info("[generate-note] Handing off to running note job %s", existing_jid)
            return jsonify({"job_id": existing_jid, "status": "running"}), 202

    # ── Start a fresh async note-generation job ───────────────────────────
    note_jid = _new_job()
    with _cid_note_job_lock:
        _cid_note_job[cid] = note_jid
    threading.Thread(
        target=_run_note_generation,
        args=(note_jid, cid, c["transcript"]),
        daemon=True,
        name=f"note-{note_jid[:8]}",
    ).start()
    logger.info("[generate-note] Started new note job %s for %s", note_jid, cid)
    return jsonify({"job_id": note_jid, "status": "pending"}), 202


@app.put("/api/consultations/<cid>/note")
@require("doctor")
def edit_note(cid):
    c, e = own_consultation(cid)
    if e:
        return e
    if c["status"] == "approved":
        return err("Already approved; note is locked", 409)
    note = (request.get_json(silent=True) or {}).get("note")
    if not isinstance(note, dict):
        return err("'note' object is required")
    return jsonify(store.update(cid, note=note, status="note_generated"))


@app.post("/api/consultations/<cid>/approve")
@require("doctor")
def approve(cid):
    c, e = own_consultation(cid)
    if e:
        return e
    if c["status"] == "approved":
        return err("Already approved; note is locked", 409)
    if not c["note"]:
        return err("Generate a note first")
    try:
        t0 = time.perf_counter()
        summary = gs.generate_patient_summary(c["note"])
        logger.info("[TIMING] generate_summary=%.2fs", time.perf_counter() - t0)
    except Exception as ex:
        app.logger.error("Summary generation failed: %s", type(ex).__name__)
        return err("Summary generation failed. Please try again.", 502)

    # ── Jan Aushadhi Generic Suggestions ──────────────────────────────
    med_list = (summary.get("medicines") or []) if isinstance(summary, dict) else []
    if not med_list and c.get("note"):
        med_list = c["note"].get("medications") or []
    generic_suggestions = generic_service.suggest_for_medications(med_list)

    if isinstance(summary, dict):
        summary["generic_suggestions"] = generic_suggestions

    updated = store.update(cid, patient_summary=summary, generic_suggestions=generic_suggestions, status="approved")
    out = {
        "consultation": updated,
        "patient_id": c["patient_id"],
        "generic_suggestions": generic_suggestions,
    }
    p = store.get_patient(c["patient_id"])
    if not p.get("key_hash"):
        key = make_key()
        store.set_patient_key(c["patient_id"], generate_password_hash(key))
        out["passkey"] = key
    return jsonify(out)


# ── GENERIC MEDICINE SUGGESTIONS
@app.post("/api/generic-suggest")
def generic_suggest():
    """
    Given a list of medications, return Jan Aushadhi generic suggestions
    with exact active ingredients, strength, form, and price savings.
    Body format: {"medications": [...]} or {"medicines": [...]} or directly [...]
    """
    body = request.get_json(silent=True) or {}
    if isinstance(body, list):
        meds = body
    elif isinstance(body, dict):
        meds = body.get("medications") or body.get("medicines") or []
    else:
        meds = []
    suggestions = generic_service.suggest_for_medications(meds)
    return jsonify({
        "suggestions": suggestions,
        "generic_suggestions": suggestions,
    })


# ── PATIENT
@app.get("/api/patient/consultations")
@require("patient")
def patient_list():
    if not store.get_patient(g.uid):
        return err("Your account no longer exists.", 401)
    items = store.find_approved_by_patient_id(g.uid)
    return jsonify([{"id": c["id"], "created_at": c["created_at"],
                     "title": (c.get("note") or {}).get("chief_complaint") or "Visit summary"} for c in items])


@app.get("/api/patient/consultations/<cid>")
@require("patient")
def patient_one(cid):
    c = store.get(cid)
    if not c or c["patient_id"] != g.uid or c["status"] != "approved":
        return err("Not available", 403)
    ps = c.get("patient_summary")
    if isinstance(ps, dict):
        if not ps.get("generic_suggestions") or any(x is None for x in ps.get("generic_suggestions", [])):
            if ps.get("medicines"):
                ps["generic_suggestions"] = generic_service.suggest_for_medications(ps["medicines"])
    out = {"id": c["id"], "created_at": c["created_at"], "patient_summary": ps}
    if c.get("generic_suggestions") or (isinstance(ps, dict) and ps.get("generic_suggestions")):
        out["generic_suggestions"] = (isinstance(ps, dict) and ps.get("generic_suggestions")) or c.get("generic_suggestions")
    return jsonify(out)


# Optional demo data
if os.getenv("SEED_DEMO") == "1":
    for _id, _name in [("D101", "Dr. Sarah"), ("D102", "Dr. Arjun"), ("D103", "Dr. Meera")]:
        store.create_doctor(_id, _name, generate_password_hash("password"))

if __name__ == "__main__":
    # use_reloader=False: prevents loading Whisper model twice during debug startup.
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=os.getenv("FLASK_DEBUG") == "1",
        use_reloader=False,
    )
