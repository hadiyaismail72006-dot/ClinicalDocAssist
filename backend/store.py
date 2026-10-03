"""JSON-file storage: doctors, patients (one passkey hash each) and consultations."""
import json
import os
import secrets
import threading
from datetime import datetime, timezone

DATA_FILE = os.path.join("data", "db.json")   # new file; the old consultations.json is not used
_lock = threading.RLock()


def _load():
    base = {"doctors": {}, "patients": {}, "consultations": {}}
    if not os.path.exists(DATA_FILE):
        return base
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            db = json.load(f)
        except json.JSONDecodeError:
            return base
    for k in base:
        db.setdefault(k, {})
    return db


def _save(db):
    os.makedirs("data", exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)  # swap in the new file in one step


def _mutate(fn):
    """Load, change, save under one lock."""
    with _lock:
        db = _load()
        result = fn(db)
        _save(db)
        return result


def _read(fn):
    with _lock:
        return fn(_load())


# ---------- doctors ----------
def get_doctor(did):
    return _read(lambda db: db["doctors"].get(did))


def create_doctor(did, name, pw_hash):
    """Returns False if the ID is already taken."""
    def f(db):
        if did in db["doctors"]:
            return False
        db["doctors"][did] = {"doctor_id": did, "doctor_name": name, "pw_hash": pw_hash}
        return True
    return _mutate(f)


# ---------- patients ----------
def get_patient(pid):
    return _read(lambda db: db["patients"].get(pid))


def set_patient_key(pid, key_hash):
    def f(db):
        db["patients"][pid]["key_hash"] = key_hash
    _mutate(f)


def list_patients(doctor_id):
    """[{patient_id, consultations:[{id,status,created_at}]}] for one doctor, oldest consultation first."""
    def f(db):
        out = []
        for pid, p in db["patients"].items():
            if p["doctor_id"] != doctor_id:
                continue
            cons = sorted((c for c in db["consultations"].values() if c["patient_id"] == pid),
                          key=lambda c: c["created_at"])
            out.append({"patient_id": pid,
                        "consultations": [{"id": c["id"], "status": c["status"], "created_at": c["created_at"]} for c in cons]})
        return sorted(out, key=lambda p: p["patient_id"])
    return _read(f)


def delete_patient(pid):
    def f(db):
        db["patients"].pop(pid, None)
        for cid in [k for k, c in db["consultations"].items() if c["patient_id"] == pid]:
            del db["consultations"][cid]
    _mutate(f)


# ---------- consultations ----------
def create_consultation(pid, doctor_id, doctor_name=""):
    """Creates the patient if new. Returns (consultation, None) or (None, 'owned_by_other')."""
    def f(db):
        p = db["patients"].get(pid)
        if p and p["doctor_id"] != doctor_id:
            return None, "owned_by_other"
        if not p:
            db["patients"][pid] = {"patient_id": pid, "doctor_id": doctor_id, "key_hash": None}
        cid = secrets.token_urlsafe(10)  # random, cannot be guessed
        db["consultations"][cid] = {
            "id": cid, "patient_id": pid, "doctor_name": doctor_name, "status": "created",
            "transcript": "", "note": None, "patient_summary": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return db["consultations"][cid], None
    return _mutate(f)


def get(cid):
    return _read(lambda db: db["consultations"].get(cid))


def update(cid, **fields):
    def f(db):
        if cid not in db["consultations"]:
            return None
        db["consultations"][cid].update(fields)
        return db["consultations"][cid]
    return _mutate(f)


def delete_consultation(cid):
    _mutate(lambda db: db["consultations"].pop(cid, None))


def find_approved_by_patient_id(pid):
    def f(db):
        items = [c for c in db["consultations"].values() if c["patient_id"] == pid and c["status"] == "approved"]
        return sorted(items, key=lambda c: c["created_at"], reverse=True)
    return _read(f)