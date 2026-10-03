import os
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NOTE_MODEL = os.getenv("NOTE_MODEL", "gemini-3.8-flash")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY missing in .env")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "gemini-3.5-flash-lite")