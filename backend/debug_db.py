import json
with open('data/db.json', encoding='utf-8') as f:
    db = json.load(f)
print("=== Approved consultations ===")
for cid, c in db['consultations'].items():
    if c.get('status') == 'approved':
        ps = c.get('patient_summary') or {}
        meds = ps.get('medicines', [])
        gs_in_ps = ps.get('generic_suggestions')
        gs_in_c = c.get('generic_suggestions')
        print(f"\nCID: {cid}  patient: {c['patient_id']}")
        print(f"  meds count: {len(meds)}")
        for m in meds:
            print(f"    med: {m}")
        print(f"  generic_suggestions in patient_summary: {gs_in_ps is not None}")
        print(f"  generic_suggestions in consultation: {gs_in_c is not None}")
        if gs_in_ps:
            print(f"  ps.generic_suggestions: {json.dumps(gs_in_ps, indent=2)}")
        if gs_in_c:
            print(f"  c.generic_suggestions: {json.dumps(gs_in_c, indent=2)}")
