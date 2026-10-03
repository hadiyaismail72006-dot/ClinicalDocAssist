"""
Verify suggest_for_medications works with all the actual medicine formats seen in db.json
and also re-compute generic_suggestions for all existing consultations.
"""
import sys, json
sys.path.insert(0, 'backend')
from services import generic_service as g

# Test all medicine formats seen in db.json
test_cases = [
    # (description, medicines_list)
    ("Paracetamol no dose", [{"name": "Paracetamol", "how_to_take": "One tablet was taken yesterday as needed."}]),
    ("paracetamol no dose", [{"name": "paracetamol", "how_to_take": "Take as discussed."}]),
    ("paracetamol twice a day", [{"name": "paracetamol", "how_to_take": "Take twice a day"}]),
    ("Imatnib 400mg", [{"name": "Imatnib", "how_to_take": "400 mg, 2 times"}]),
    ("Imatnib 400 mg in name", [{"name": "Imatnib 400 mg", "how_to_take": "Take 2 times"}]),
    ("Imatinib 400mg in how_to_take", [{"name": "Imatinib", "how_to_take": "Take 400mg, 2 times."}]),
    ("Crocin 500mg twice daily", [{"name": "Crocin 500mg", "how_to_take": "twice daily"}]),
    ("Pan 40 once daily", [{"name": "Pan 40", "how_to_take": "once daily"}]),
]

print("=== suggest_for_medications test ===\n")
for desc, meds in test_cases:
    result = g.suggest_for_medications(meds)
    sug = result[0] if result else None
    if sug:
        print(f"[MATCH] {desc}")
        print(f"        -> {sug['generic_name']} @ Rs {sug['generic_price']} vs Rs {sug['brand_price']} (save {sug['saving_pct']}%)")
    else:
        print(f"[ NONE ] {desc}")
    print()

# Re-compute and update generic_suggestions for all consultations
print("\n=== Re-computing generic_suggestions for all consultations ===\n")
with open('data/db.json', encoding='utf-8') as f:
    db = json.load(f)

updated = 0
for cid, c in db['consultations'].items():
    if c.get('status') != 'approved':
        continue
    ps = c.get('patient_summary')
    if not isinstance(ps, dict):
        continue
    meds = ps.get('medicines', [])
    if not meds:
        continue
    suggestions = g.suggest_for_medications(meds)
    ps['generic_suggestions'] = suggestions
    c['generic_suggestions'] = suggestions
    updated += 1
    print(f"CID {cid}: updated suggestions = {[s['generic_name'] if s else None for s in suggestions]}")

with open('data/db.json', 'w', encoding='utf-8') as f:
    json.dump(db, f, indent=2, ensure_ascii=False)

print(f"\nDone. Updated {updated} consultations.")
