"""
test_generic_suggestions.py — Test cases for Jan Aushadhi generic medicine suggestions.

Tests cover:
  1. Exact brand match: Crocin 500mg tablet -> Jan Aushadhi Paracetamol 500mg Tab
  2. Exact brand match with number in name: Dolo 650 -> Jan Aushadhi Paracetamol 650mg Tab
  3. Combination medicine match: Glucovance MF -> Metformin+Glimepiride
  4. Generic name typed directly: 'paracetamol 500mg tablet' -> matches JA
  5. STRENGTH MISMATCH: Crocin requested with 250mg must NOT match (never substitute different strengths)
  6. FORM MISMATCH: Crocin tablet requested as capsule must NOT match
  7. UNKNOWN DRUG: UnknownBrand XYZ must return None
  8. API route: POST /api/generic-suggest returns parallel list of suggestions
"""

import unittest
import json
import os
import sys

# Ensure backend directory is in sys.path
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from generic_service import find_cheaper, suggest_for_medications
from app import app


class TestJanAushadhiService(unittest.TestCase):

    def test_01_exact_brand_match(self):
        """Crocin 500mg tablet must match JA Paracetamol 500mg Tab with price savings."""
        res = find_cheaper("Crocin", strength="500mg", form="tablet")
        self.assertIsNotNone(res)
        self.assertEqual(res["generic_name"], "Paracetamol 500mg Tab")
        self.assertEqual(res["brand_price"], 2.50)
        self.assertEqual(res["generic_price"], 1.50)
        self.assertEqual(res["saving_rs"], 1.00)
        self.assertEqual(res["saving_pct"], 40.0)

    def test_02_brand_with_number(self):
        """Dolo 650 tablet must match JA Paracetamol 650mg Tab."""
        res = find_cheaper("Dolo 650", strength="650mg", form="tablet")
        self.assertIsNotNone(res)
        self.assertEqual(res["generic_name"], "Paracetamol 650mg Tab")
        self.assertEqual(res["brand_price"], 3.20)
        self.assertEqual(res["generic_price"], 2.00)
        self.assertEqual(res["saving_rs"], 1.20)

    def test_03_combination_medicine(self):
        """Combination drug Glucovance MF (metformin+glimepiride) must match JA."""
        res = find_cheaper("Glucovance MF", strength="500mg/1mg", form="tablet")
        self.assertIsNotNone(res)
        self.assertEqual(res["generic_name"], "Metformin+Glimepiride 500/1mg Tab")
        self.assertEqual(res["saving_rs"], 13.50)
        self.assertEqual(res["saving_pct"], 75.0)

    def test_04_generic_name_directly(self):
        """A generic name typed directly (paracetamol 500mg tablet) must match JA."""
        res = find_cheaper("paracetamol", strength="500mg", form="tablet")
        self.assertIsNotNone(res)
        self.assertEqual(res["generic_name"], "Paracetamol 500mg Tab")
        self.assertEqual(res["generic_price"], 1.50)
        self.assertGreater(res["saving_rs"], 0)

    def test_05_strength_mismatch_must_not_match(self):
        """CRITICAL: Crocin (normally 500mg) requested with 250mg must NOT match (never guess)."""
        res = find_cheaper("Crocin", strength="250mg", form="tablet")
        self.assertIsNone(res, "Different strength must NOT match!")

    def test_06_form_mismatch_must_not_match(self):
        """CRITICAL: Crocin tablet requested as capsule must NOT match."""
        res = find_cheaper("Crocin", strength="500mg", form="capsule")
        self.assertIsNone(res, "Different form must NOT match!")

    def test_07_unknown_brand_must_not_match(self):
        """An unknown brand must return None."""
        res = find_cheaper("UnknownBrand XYZ", strength="100mg", form="tablet")
        self.assertIsNone(res)

    def test_08_suggest_for_medications_list(self):
        """suggest_for_medications returns a parallel list of suggestions and None."""
        meds = [
            {"name": "Crocin", "dose": "500mg", "frequency": "twice daily"},
            {"name": "Crocin", "dose": "250mg", "frequency": "once daily"},  # mismatch
            {"name": "Pan 40", "dose": "40mg", "frequency": "before breakfast"},
        ]
        results = suggest_for_medications(meds)
        self.assertEqual(len(results), 3)
        self.assertIsNotNone(results[0])
        self.assertIsNone(results[1])
        self.assertIsNotNone(results[2])
        self.assertEqual(results[0]["generic_name"], "Paracetamol 500mg Tab")
        self.assertEqual(results[2]["generic_name"], "Pantoprazole 40mg Tab")

    def test_09_api_endpoint(self):
        """POST /api/generic-suggest should return suggestions in JSON."""
        client = app.test_client()
        payload = {
            "medications": [
                {"name": "Crocin", "dose": "500mg"},
                {"name": "Crocin", "dose": "250mg"},
                {"name": "UnknownBrand XYZ", "dose": "100mg"},
            ]
        }
        resp = client.post("/api/generic-suggest", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("suggestions", data)
        self.assertEqual(len(data["suggestions"]), 3)
        self.assertIsNotNone(data["suggestions"][0])
        self.assertIsNone(data["suggestions"][1])
        self.assertIsNone(data["suggestions"][2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
