"""
generic_service.py — Jan Aushadhi generic medicine suggestion engine.

Goal: Whenever a medication appears in a prescription/report, show a
cheaper Jan Aushadhi (Government of India) generic with the SAME
active ingredient(s), same strength and same dosage form, plus the
price saving.

Key Rules:
  1. Both CSVs (jan_aushadhi.csv and brand_medicines.csv) are loaded once at startup.
  2. Normalize text: lowercase, trim, split combination ingredients and sort them
     so order does not matter (e.g. 'A|B' == 'B|A').
  3. find_cheaper(brand_name, strength=None, form=None):
     - Look up the brand (or generic name directly).
     - Match Jan Aushadhi on ALL of ingredients + strength + form.
     - Return generic name, both prices, saving in rupees and percent.
     - Return None if there is no match or the generic is not cheaper.
     - Never guess (different strength or form must NOT match).
"""

import csv
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── File paths ────────────────────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# Check standard locations: <root>/data, <backend>/data, or CWD/data
_CANDIDATE_DATA_DIRS = [
    os.path.join(os.path.dirname(_THIS_DIR), "data"),  # backend/.. -> root/data
    os.path.join(_THIS_DIR, "data"),                  # backend/data
    os.path.join(os.getcwd(), "data"),                # cwd/data
]

_DATA_DIR = next((d for d in _CANDIDATE_DATA_DIRS if os.path.isdir(d)), _CANDIDATE_DATA_DIRS[0])
_JA_PATH = os.path.join(_DATA_DIR, "jan_aushadhi.csv")
_BR_PATH = os.path.join(_DATA_DIR, "brand_medicines.csv")


# ── Normalisation helpers ──────────────────────────────────────────────

_FORM_ALIASES = {
    "tab": "tablet",
    "tabs": "tablet",
    "tablets": "tablet",
    "tablet": "tablet",
    "cap": "capsule",
    "caps": "capsule",
    "capsules": "capsule",
    "capsule": "capsule",
    "syp": "syrup",
    "syrup": "syrup",
    "pwd": "powder",
    "powder": "powder",
    "suspension": "syrup",
    "inj": "injection",
    "injection": "injection",
}


def _norm_str(s: Any) -> str:
    """Lowercase, strip, collapse internal whitespace."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).lower().strip())


def _norm_ingredients(raw: Any) -> frozenset:
    """
    Split on '|', '+', or ',', normalise each ingredient, return a frozenset
    so that order and duplicates never matter (e.g. 'A|B' == 'B|A').
    """
    if isinstance(raw, (set, frozenset, list, tuple)):
        parts = raw
    else:
        parts = re.split(r"[|\+,]", str(raw or ""))
    cleaned = [_norm_str(p) for p in parts if _norm_str(p)]
    return frozenset(cleaned)


def _norm_strength(s: Any) -> str:
    """Lowercase, remove spaces, e.g. '500 mg' -> '500mg'."""
    if not s:
        return ""
    st = _norm_str(s).replace(" ", "")
    return st


def _norm_form(s: Any) -> str:
    """Normalize dosage form using aliases (tab -> tablet, etc.)."""
    if not s:
        return ""
    form = _norm_str(s)
    return _FORM_ALIASES.get(form, form)


def _extract_strength_form(text: str) -> tuple[str, str | None, str | None]:
    """
    Helper to extract embedded strength (e.g. '500mg', '650 mg', '40mg', '500mg/1mg')
    and form (e.g. 'tablet', 'cap', 'syrup') from a string like 'Paracetamol 500mg Tab'.
    Returns (cleaned_name, extracted_strength, extracted_form).
    """
    cleaned = _norm_str(text)
    ext_strength = None
    ext_form = None

    # Check for form keyword
    for alias, canonical in _FORM_ALIASES.items():
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, cleaned):
            ext_form = canonical
            cleaned = re.sub(pattern, " ", cleaned)
            break

    # Check for strength pattern (e.g. 500mg/1mg, 125mg/5ml, 500mg, 500 mg, 40mg)
    m = re.search(r"\b(\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml)(?:/\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml))?)\b", cleaned)
    if m:
        ext_strength = _norm_strength(m.group(1))
        cleaned = cleaned[:m.start()] + " " + cleaned[m.end():]
    else:
        # Check for plain number at end of brand like 'Dolo 650' or 'Pan 40'
        # Keep original name intact if it matches brand DB, but note strength if needed
        pass

    cleaned = _norm_str(cleaned)
    return cleaned, ext_strength, ext_form


# ── CSV loading ────────────────────────────────────────────────────────

def _load_csv(path: str, required_cols: list[str]) -> list[dict]:
    """
    Load a CSV, skipping comment lines (starting with '#') and blank rows.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Data file not found: {path}")
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(
            (line for line in f if not line.lstrip().startswith("#"))
        )
        missing = [c for c in required_cols if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"{path}: missing columns {missing}. Found: {reader.fieldnames}"
            )
        for row in reader:
            if not any(v.strip() for v in row.values()):
                continue
            rows.append(row)
    return rows


# ── Build lookup indices ───────────────────────────────────────────────

def _build_ja_index(rows: list[dict]) -> dict:
    """
    Index Jan Aushadhi by (ingredients_frozenset, strength_norm, form_norm) -> dict.
    Also keeps an index by (ingredients_frozenset, strength_norm) -> list of products.
    """
    idx = {}
    for row in rows:
        try:
            ingr = _norm_ingredients(row["ingredients"])
            strength = _norm_strength(row["strength"])
            form = _norm_form(row["form"])
            mrp = float(row["mrp"])

            key = (ingr, strength, form)
            # If multiple JA products match the same key, keep the cheapest
            if key not in idx or mrp < idx[key]["mrp"]:
                idx[key] = {
                    "generic_name": row["generic_name"].strip(),
                    "ingredients": ingr,
                    "strength": strength,
                    "form": form,
                    "mrp": mrp,
                }
        except (KeyError, ValueError) as exc:
            logger.warning("[generic_service] Skipping bad JA row %s: %s", row, exc)
    return idx


def _build_brand_index(rows: list[dict]) -> tuple[dict, dict, dict]:
    """
    Returns:
      by_name: brand_name_lower -> row dict
      by_ingr_str_form: (ingredients_frozenset, strength_norm, form_norm) -> list of row dicts
      by_ingr_str: (ingredients_frozenset, strength_norm) -> list of row dicts
    """
    by_name = {}
    by_ingr_str_form: dict = {}
    by_ingr_str: dict = {}

    for row in rows:
        try:
            bname = _norm_str(row["brand_name"])
            by_name[bname] = row

            ingr = _norm_ingredients(row["ingredients"])
            strength = _norm_strength(row["strength"])
            form = _norm_form(row["form"])

            key_full = (ingr, strength, form)
            by_ingr_str_form.setdefault(key_full, []).append(row)

            key_short = (ingr, strength)
            by_ingr_str.setdefault(key_short, []).append(row)
        except (KeyError, ValueError) as exc:
            logger.warning("[generic_service] Skipping bad brand row %s: %s", row, exc)

    return by_name, by_ingr_str_form, by_ingr_str


# ── Load data at import time ───────────────────────────────────────────

try:
    _JA_ROWS = _load_csv(_JA_PATH, ["generic_name", "ingredients", "strength", "form", "mrp"])
    _JA_INDEX = _build_ja_index(_JA_ROWS)
    logger.info("[generic_service] Loaded %d Jan Aushadhi entries from %s", len(_JA_INDEX), _JA_PATH)
except Exception as exc:
    logger.error("[generic_service] Could not load Jan Aushadhi CSV (%s): %s", _JA_PATH, exc)
    _JA_ROWS = []
    _JA_INDEX = {}

try:
    _BR_ROWS = _load_csv(_BR_PATH, ["brand_name", "ingredients", "strength", "form", "price"])
    _BR_BY_NAME, _BR_BY_INGR_FULL, _BR_BY_INGR_STR = _build_brand_index(_BR_ROWS)
    logger.info("[generic_service] Loaded %d brand entries from %s", len(_BR_BY_NAME), _BR_PATH)
except Exception as exc:
    logger.error("[generic_service] Could not load brand medicines CSV (%s): %s", _BR_PATH, exc)
    _BR_ROWS = []
    _BR_BY_NAME = {}
    _BR_BY_INGR_FULL = {}
    _BR_BY_INGR_STR = {}


# ── Public API ─────────────────────────────────────────────────────────

def find_cheaper(
    brand_name: str | None = None,
    strength: str | None = None,
    form: str | None = None,
    **kwargs,
) -> dict | None:
    """
    Look up 'brand_name' (brand or generic/ingredient), match Jan Aushadhi on
    ALL of: active ingredient(s) + strength + dosage form.

    Returns a dict:
      {
        "brand_name":    str,       # brand name or searched name
        "brand_price":   float,     # brand MRP per unit
        "generic_name":  str,       # Jan Aushadhi product name
        "generic_price": float,     # Jan Aushadhi MRP
        "saving_rs":     float,     # brand_price - generic_price
        "saving_pct":    float,     # percentage saved
      }

    Returns None when:
      - No matching Jan Aushadhi product is found
      - The generic is NOT cheaper than the brand
      - Strength or form mismatch (never guess)
      - Cannot establish a valid brand price
    """
    raw_name = brand_name or kwargs.get("name") or ""
    if not raw_name or not str(raw_name).strip():
        return None

    name_norm = _norm_str(raw_name)

    # ── Step 1: Look up in brand DB by exact brand name ────────────────
    brand_row = _BR_BY_NAME.get(name_norm)

    # If not found directly, check if name has embedded strength/form, e.g. "Crocin 500mg tablet"
    if brand_row is None:
        base_name, ext_str, ext_form = _extract_strength_form(name_norm)
        if base_name in _BR_BY_NAME:
            brand_row = _BR_BY_NAME[base_name]
            if strength is None and ext_str:
                strength = ext_str
            if form is None and ext_form:
                form = ext_form

    # ── Step 2: Handle generic name entered directly ───────────────────
    # (e.g. "paracetamol", "metformin", "amlodipine")
    is_generic_query = False
    if brand_row is None:
        # Check if the name corresponds to known active ingredients
        query_ingr = _norm_ingredients(name_norm)
        # Also try base name if embedded strength was stripped
        base_name, ext_str, ext_form = _extract_strength_form(name_norm)
        if not ext_str and strength:
            ext_str = strength
        if not ext_form and form:
            ext_form = form

        # Find matching brand candidates by ingredients + strength
        eff_str = _norm_strength(ext_str) if ext_str else ""
        eff_form = _norm_form(ext_form) if ext_form else ""

        candidates = []
        if eff_str and eff_form:
            candidates = _BR_BY_INGR_FULL.get((query_ingr, eff_str, eff_form), [])
            if not candidates and base_name != name_norm:
                candidates = _BR_BY_INGR_FULL.get((_norm_ingredients(base_name), eff_str, eff_form), [])
        elif eff_str:
            candidates = _BR_BY_INGR_STR.get((query_ingr, eff_str), [])
            if not candidates and base_name != name_norm:
                candidates = _BR_BY_INGR_STR.get((_norm_ingredients(base_name), eff_str), [])
        else:
            # When no strength was specified, find brand candidates with matching ingredients
            candidates = [r for r in _BR_ROWS if _norm_ingredients(r.get("ingredients")) == query_ingr]
            if not candidates and base_name != name_norm:
                candidates = [r for r in _BR_ROWS if _norm_ingredients(r.get("ingredients")) == _norm_ingredients(base_name)]

        if candidates:
            # Use the first/most representative candidate brand row for pricing & form
            brand_row = candidates[0]
            is_generic_query = True
            if not strength:
                strength = eff_str or brand_row.get("strength")
            if not form:
                form = eff_form or brand_row.get("form")
            elif not form and brand_row.get("form"):
                form = brand_row["form"]

    if brand_row is None:
        # No known brand or generic candidate found in database
        return None

    # ── Step 3: Extract and verify target (ingredients, strength, form) ──
    try:
        target_ingr = _norm_ingredients(brand_row["ingredients"])
        brand_def_strength = _norm_strength(brand_row["strength"])
        brand_def_form = _norm_form(brand_row["form"])

        # Caller-specified strength & form
        target_strength = _norm_strength(strength) if strength else brand_def_strength
        target_form = _norm_form(form) if form else brand_def_form

        # If user explicitly passed a strength that differs from the brand's strength,
        # ensure we use the caller's requested strength (and require JA to match it).
        # But if the brand itself doesn't match that strength and brand wasn't a generic query,
        # this represents a brand-strength conflict.
        if strength and not is_generic_query:
            if _norm_strength(strength) != brand_def_strength:
                # Brand is sold as brand_def_strength, but caller asked for different strength.
                # Must NOT substitute different strengths.
                return None

        # Same for form: if caller specified a form that conflicts with the brand form:
        if form and not is_generic_query:
            if _norm_form(form) != brand_def_form:
                return None

        # Brand price
        raw_price = brand_row.get("price")
        if raw_price in (None, "", "None"):
            return None
        brand_price = float(raw_price)
    except (ValueError, KeyError):
        return None

    # ── Step 4: Look up Jan Aushadhi exact match ──────────────────────
    # MUST match ALL THREE: active ingredients + strength + dosage form
    ja_key = (target_ingr, target_strength, target_form)
    ja_item = _JA_INDEX.get(ja_key)

    if ja_item is None:
        return None  # No matching Jan Aushadhi product

    generic_price = ja_item["mrp"]

    # ── Step 5: Verify generic is strictly cheaper ─────────────────────
    if generic_price >= brand_price:
        return None  # Generic is not cheaper — do not suggest

    saving_rs = round(brand_price - generic_price, 2)
    saving_pct = round((saving_rs / brand_price) * 100, 1)

    return {
        "brand_name": brand_row["brand_name"] if not is_generic_query else raw_name,
        "brand_price": brand_price,
        "generic_name": ja_item["generic_name"],
        "generic_price": generic_price,
        "saving_rs": saving_rs,
        "saving_pct": saving_pct,
    }


def _extract_strength_from_text(text: str) -> str | None:
    """Extract a dosage strength like '500mg', '400 mg', '500mg/1mg' from free text."""
    if not text:
        return None
    m = re.search(
        r"\b(\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml)(?:/\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml))?)\b",
        str(text), re.IGNORECASE
    )
    return _norm_strength(m.group(1)) if m else None


def suggest_for_medications(medications: list[Any]) -> list[dict | None]:
    """
    Given a list of medications (from note or report), return a parallel list
    of suggestion dicts (or None where no cheaper generic match exists).

    Supports:
      - dicts with keys 'name', 'dose', 'frequency' (clinical note format)
      - dicts with keys 'name', 'how_to_take' (patient summary format)
      - dicts with keys 'brand_name', 'strength', 'form'
      - plain string names (e.g. 'Crocin 500mg tablet')
    """
    results = []
    for med in medications:
        if not med:
            results.append(None)
            continue

        if isinstance(med, str):
            results.append(find_cheaper(med))
            continue

        if isinstance(med, dict):
            name = med.get("name") or med.get("brand_name") or ""
            how_to_take = str(med.get("how_to_take") or "")

            # Explicit strength field (note format: 'dose'), else extract from how_to_take or name
            strength = med.get("strength") or med.get("dose") or None

            # Reject non-numeric strengths like "one tablet"
            if strength and not re.search(r"\d", str(strength)):
                strength = None

            # Try to pull strength from how_to_take prose: "Take 500mg twice a day"
            if not strength and how_to_take:
                strength = _extract_strength_from_text(how_to_take)

            # Try to pull strength from the name itself: "Paracetamol 500mg"
            if not strength:
                strength = _extract_strength_from_text(name)

            # Form detection from explicit field or from how_to_take text
            form = med.get("form") or None
            if not form:
                search_text = how_to_take + " " + name
                for alias, canonical in _FORM_ALIASES.items():
                    if re.search(r"\b" + re.escape(alias) + r"\b", search_text.lower()):
                        form = canonical
                        break

            # Primary attempt: with extracted strength + form
            sug = find_cheaper(brand_name=name, strength=strength, form=form)

            # Fallback 1: try without form (more permissive)
            if sug is None and strength and form:
                sug = find_cheaper(brand_name=name, strength=strength, form=None)

            # Fallback 2: try just the brand name only if NO explicit strength was specified
            if sug is None and not strength:
                sug = find_cheaper(brand_name=name)

            results.append(sug)
        else:
            results.append(None)

    return results



# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        # (description, kwargs, expect_match)
        ("MATCH: Crocin 500mg tablet -> JA Paracetamol 500mg Tab",
         dict(brand_name="Crocin", strength="500mg", form="tablet"), True),

        ("MATCH: Dolo 650 -> JA Paracetamol 650mg Tab",
         dict(brand_name="Dolo 650", strength="650mg", form="tablet"), True),

        ("MATCH: Pan 40 -> JA Pantoprazole 40mg Tab",
         dict(brand_name="Pan 40", strength="40mg", form="tablet"), True),

        ("MATCH: Glucovance MF (combo) -> JA Metformin+Glimepiride",
         dict(brand_name="Glucovance MF", strength="500mg/1mg", form="tablet"), True),

        ("MATCH: Generic name 'paracetamol' 500mg tablet -> JA Paracetamol 500mg Tab",
         dict(brand_name="paracetamol", strength="500mg", form="tablet"), True),

        ("MATCH: Generic name 'paracetamol' with strength only -> matches JA Tab",
         dict(brand_name="paracetamol", strength="500mg"), True),

        ("MATCH: Embedded name 'Crocin 500mg tablet'",
         dict(brand_name="Crocin 500mg tablet"), True),

        ("MATCH: Electrol ORS powder -> JA ORS Powder",
         dict(brand_name="Electrol", strength="standard", form="powder"), True),

        ("NO MATCH: Unknown brand -> None",
         dict(brand_name="UnknownBrand XYZ", strength="100mg", form="tablet"), False),

        ("NO MATCH (STRENGTH MISMATCH): Crocin with 250mg -> must NOT match",
         dict(brand_name="Crocin", strength="250mg", form="tablet"), False),

        ("NO MATCH (FORM MISMATCH): Crocin tablet requested as capsule -> must NOT match",
         dict(brand_name="Crocin", strength="500mg", form="capsule"), False),

        ("NO MATCH: Generic paracetamol with wrong strength (250mg) -> must NOT match",
         dict(brand_name="paracetamol", strength="250mg", form="tablet"), False),
    ]

    print("\n=======================================================")
    print("  Jan Aushadhi Generic Medicine Service — Test Suite  ")
    print("=======================================================\n")

    passed = failed = 0
    for desc, kwargs, expect in tests:
        res = find_cheaper(**kwargs)
        matched = res is not None
        ok = matched == expect
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {desc}")
        if res:
            print(f"       -> Generic: {res['generic_name']} @ Rs {res['generic_price']}"
                  f" (Brand: Rs {res['brand_price']}, Save: Rs {res['saving_rs']} / {res['saving_pct']}%)")
        else:
            print("       -> None")
        print()

    print(f"Test Summary: {passed} passed, {failed} failed out of {len(tests)} tests.")
    if failed == 0:
        print("ALL TESTS PASSED SUCCESSFULLY!\n")
    else:
        exit(1)
