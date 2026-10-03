from google import genai
from config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)

for m in ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]:
    try:
        r = client.models.generate_content(model=m, contents="Reply with the word OK")
        print(m, "->", r.text.strip())
    except Exception as e:
        print(m, "-> FAILED:", str(e)[:100])