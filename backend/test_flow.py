import json
import requests

BASE = "http://127.0.0.1:5000/api"
PID = "OP-20458"

SAMPLE = """Doctor: Good morning, what brings you in today?
Patient: I have had stomach pain in my lower belly since this morning, after eating outside food yesterday.
Doctor: Any vomiting or fever?
Patient: No vomiting, a little fever last night. I am allergic to penicillin.
Doctor: Let me examine you. The abdomen is tender on the lower right side but soft.
Doctor: I will prescribe paracetamol 500 mg twice a day for three days, and ORS after each loose stool. Avoid outside food.
Doctor: Come back in three days, or earlier if the pain gets worse or you have a high fever.
Patient: Okay. You can call me on 98765 43210 if the report is ready."""


def show(title, r):
    print(f"\n===== {title} =====")
    print("Status:", r.status_code)
    try:
        print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(r.text[:500])


# 1. Create
r = requests.post(f"{BASE}/consultations", json={"patient_id": PID, "doctor_name": "Dr. Test"})
show("1. Create consultation", r)
cid = r.json()["id"]

# 2. Submit transcript (text)
r = requests.post(f"{BASE}/consultations/{cid}/transcript", json={"transcript": SAMPLE})
show("2. Submit transcript (expect [PHONE] in it)", r)

# 3. Generate note
r = requests.post(f"{BASE}/consultations/{cid}/generate-note")
show("3. Clinical note", r)

# 4. Patient tries before approval (expect 403)
r = requests.post(f"{BASE}/patient/summary", json={"patient_id": PID, "key": "WRONG"})
show("4. Before approval (expect 403)", r)

# 5. Approve
r = requests.post(f"{BASE}/consultations/{cid}/approve")
show("5. Approve", r)
key = r.json()["access_key"]

# 6. Wrong key, then right key
r = requests.post(f"{BASE}/patient/summary", json={"patient_id": PID, "key": "WRONG"})
show("6a. Wrong key (expect 403)", r)
r = requests.post(f"{BASE}/patient/summary", json={"patient_id": PID, "key": key})
show("6b. Correct key (expect 200)", r)