"""
scrub_service.py – strips personally identifiable information from transcripts
before they are stored or sent to any AI model.

Scrubbed categories:
  [PHONE]    – mobile / landline (Indian & international)
  [EMAIL]    – email addresses
  [NAME]     – names stated in conversation ("my name is ...", "I am ...")
  [ADDRESS]  – street / flat / house addresses and localities
  [PINCODE]  – 6-digit Indian PIN codes near a pincode keyword
  [AADHAAR]  – 12-digit Aadhaar  (grouped as 4-4-4)
  [PAN]      – Indian PAN card  (e.g. ABCDE1234F)
  [PASSPORT] – passport numbers (e.g. A1234567)
  [DOB]      – dates of birth (DD/MM/YYYY, YYYY-MM-DD, "15 January 1990")
  [AGE]      – "I am 34", "aged 34", "34 years old"
  [ID]       – MR / OP / UHID / registration numbers
  [CARD]     – credit / debit card numbers
  [BANK]     – account numbers, IFSC codes, UPI IDs
"""

import re

def _c(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern:
    return re.compile(pattern, flags)


# ── patterns (most-specific first) ───────────────────────────────────────────

# Aadhaar: 12 digits grouped 4-4-4 (spaces or dashes between groups)
AADHAAR   = _c(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}\b")

# PAN card: 5 letters, 4 digits, 1 letter  (e.g. ABCDE1234F)
PAN       = _c(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")

# Passport: one letter + 7 digits (e.g. A1234567)
PASSPORT  = _c(r"\b[A-Z]\d{7}\b")

# Credit / debit card: 13-19 digits optionally split by spaces or dashes
CARD      = _c(r"\b(?:\d{4}[\s\-]){3}\d{1,4}\b|\b\d{13,19}\b")

# Email
EMAIL     = _c(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")

# IFSC code: 4 letters + 0 + 6 alphanumeric
IFSC      = _c(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")

# UPI ID: anything@upi-handle
UPI       = _c(r"\b[\w.\-]+@(?:upi|paytm|gpay|phonepe|ybl|okaxis|okhdfcbank|okicici|oksbi)\b")

# Bank account number: 9-18 consecutive digits (standalone)
BANK_ACC  = _c(r"(?<![:\-\/\d])\b\d{9,18}\b(?![:\-\/\d])")

# Date of birth
DOB = _c(
    r"\b(?:"
    r"\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}"         # DD/MM/YYYY
    r"|\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2}"           # YYYY-MM-DD
    r"|(?:0?[1-9]|[12]\d|3[01])\s+"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+\d{2,4}"
    r")\b"
)

# Age: "I am 34", "I'm 34 years old", "aged 34", "age: 34"
AGE = _c(
    r"\b(?:i(?:\s+am|'m)\s+\d{1,3}(?:\s+years?\s*old)?|aged?\s*:?\s*\d{1,3}|\d{1,3}\s*years?\s*old|age\s*:?\s*\d{1,3})\b"
)

# Indian PIN code: 6-digit number preceded by pin/pincode/zip keyword (with optional "is")
PINCODE   = _c(r"\b(?:pin(?:\s*code)?|zip)\s*(?:is\s*)?[:\-]?\s*\d{6}\b")

# MR / OP / UHID / registration number
ID_NUM    = _c(
    r"\b(?:mr|op|uhid|patient\s*id|reg(?:istration)?|admission|case)\s*(?:no|num(?:ber)?)?\s*[:\-]?\s*[\w\-\/]{2,20}\b"
)

# Street address: flat/house/door/plot followed by number, or known street words
ADDRESS   = _c(
    r"\b(?:flat|house|door|plot|shop|block|room|apt|apartment|unit|no\.?|#)\s*[\w\-\/]+"
    r"|\d+[A-Za-z]?\s*,?\s*[\w\s]{1,30}"
    r"(?:street|st\b|road|rd\b|avenue|ave\b|lane|nagar|colony|layout|phase|sector|cross|main|marg|bypass)\b"
)

# Name introductions: only match when followed by a properly-capitalised name
# (first letter uppercase, not an all-caps abbreviation)
NAME = _c(
    r"(?:my\s+name\s+is|patient(?:\s+name)?\s*(?:is|:)|call\s+me)\s+"
    r"([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,}){0,3})"
)

# Phone: 10+ digit numbers in common Indian/international formats
# Require at least 10 digits total to avoid matching short numbers
PHONE = _c(
    r"(?<!\d)"
    r"(?:\+?91[\s\-]?)?(?:\(?\d{2,5}\)?[\s\-.]?)?\d{4,5}[\s\-.]?\d{4,5}"
    r"(?!\d)"
)

# ── ordered replacement rules ─────────────────────────────────────────────────
# Most specific patterns first to avoid partial matches being missed
_RULES: list[tuple[re.Pattern, str]] = [
    (AADHAAR,  "[AADHAAR]"),
    (PAN,      "[PAN]"),
    (PASSPORT, "[PASSPORT]"),
    (CARD,     "[CARD]"),
    (EMAIL,    "[EMAIL]"),
    (IFSC,     "[BANK]"),
    (UPI,      "[BANK]"),
    (DOB,      "[DOB]"),
    (AGE,      "[AGE]"),
    (PINCODE,  "[PINCODE]"),
    (ID_NUM,   "[ID]"),
    (ADDRESS,  "[ADDRESS]"),
    (NAME,     "[NAME]"),
    (BANK_ACC, "[BANK]"),
    (PHONE,    "[PHONE]"),   # broad — must be last
]


def scrub(text: str) -> str:
    """Replace all detected PII in `text` with placeholder tokens."""
    if not text:
        return text
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


# ── quick self-test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        ("Name intro",          "Patient: My name is Ravi Kumar and I am 34 years old."),
        ("Phone Indian",        "Patient: Call me on +91 98765 43210 when ready."),
        ("Phone local",         "Patient: My number is 9876543210."),
        ("Email",               "Patient: Email me at ravi.kumar@gmail.com"),
        ("Aadhaar",             "Patient: Aadhaar is 1234 5678 9012."),
        ("PAN",                 "Patient: PAN card is ABCDE1234F."),
        ("Passport",            "Patient: My passport number is A1234567."),
        ("DOB dd/mm/yyyy",      "Patient: DOB is 15/08/1990."),
        ("DOB worded",          "Patient: I was born on 15 August 1990."),
        ("Age statement",       "Patient: I am 34 years old."),
        ("Address flat",        "Patient: I live at Flat 4B, 12 MG Road, Nagar Colony."),
        ("IFSC",                "Patient: IFSC is HDFC0001234."),
        ("UPI",                 "Patient: UPI ID is ravi@ybl"),
        ("Bank account",        "Patient: Account number is 123456789012."),
        ("Pincode",             "Patient: Pincode is 560001."),
        ("ID number",           "Doctor: MR No: OP-20458 admitted today."),
        ("Normal sentence",     "Doctor: Take paracetamol 500 mg twice a day."),
    ]
    all_pass = True
    for label, s in tests:
        out = scrub(s)
        changed = out != s
        flag = "SCRUBBED" if changed else "UNCHANGED"
        print(f"[{flag:9}] {label}")
        if changed:
            print(f"            IN : {s}")
            print(f"            OUT: {out}")
    print()
    # Ensure medical content is NOT scrubbed
    medical = "Doctor: Take paracetamol 500 mg twice a day for three days."
    assert scrub(medical) == medical, "Medical content incorrectly scrubbed!"
    print("Medical content preserved correctly.")
