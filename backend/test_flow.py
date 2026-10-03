import requests
import json

BASE = "http://localhost:5000/api"
PID = "OP-20458"
SAMPLE = """Doctor: Good morning, what brings you in today?
Patient: I have had stomach pain in my lower belly since this morning, after eating outside food yesterday.
Doctor: Any vomiting or fever?
Patient: No vomiting, a little fever last night. I am allergic to penicillin. Call me on 9876543210.
Doctor: Let me examine you. The abdomen is tender on the lower right side but soft.
Doctor: I will prescribe paracetamol 500 mg twice a day for three days, and ORS after each loose stool. Avoid outside food.
Doctor: Come back in three days, or earlier if the pain gets worse or you have a high fever."""


def show(title, r):
    print(f"\n===== {title} =====")
    print("Status:", r.status_code)
    try:
        print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(r.text[:500])


# 0. Doctor login
r = requests.post(f"{BASE}/auth/doctor-login", json={"doctor_id": "D101", "passkey": "password"})
show("0. Doctor login", r)
doc_token = r.json()["token"]
headers = {"Authorization": f"Bearer {doc_token}"}

# 1. Create consultation
r = requests.post(f"{BASE}/patients/{PID}/consultations", headers=headers)
show("1. Create consultation", r)
cid = r.json()["id"]

# 2. Submit transcript (text with phone number to test scrub)
r = requests.post(f"{BASE}/consultations/{cid}/transcript", headers=headers, json={"transcript": SAMPLE})
show("2. Submit transcript (expect [PHONE] in it)", r)

# 3. Generate note
r = requests.post(f"{BASE}/consultations/{cid}/generate-note", headers=headers)
show("3. Clinical note", r)

# 4. Approve consultation
r = requests.post(f"{BASE}/consultations/{cid}/approve", headers=headers)
show("4. Approve", r)
passkey = r.json().get("passkey")
print("Patient passkey:", passkey)

# 5. Patient login
if passkey:
    r = requests.post(f"{BASE}/auth/patient-login", json={"patient_id": PID, "passkey": passkey})
    show("5. Patient login with correct passkey", r)
    pat_token = r.json().get("token")
    if pat_token:
        pat_headers = {"Authorization": f"Bearer {pat_token}"}
        r = requests.get(f"{BASE}/patient/consultations/{cid}", headers=pat_headers)
        show("6. Patient view approved summary", r)

print("\n--- Test Flow Completed Successfully ---")