import requests

BASE = 'http://localhost:5000/api'
login = requests.post(f'{BASE}/auth/doctor-login', json={'doctor_id': 'D101', 'passkey': 'password'}).json()
headers = {'Authorization': f'Bearer {login["token"]}'}

c = requests.post(f'{BASE}/patients/OP-20458/consultations', headers=headers).json()
cid = c['id']

sample = """Doctor: Hello, what is your name?
Patient: Hello Doctor, my name is Priya Sharma, and my brother Arjun Sharma accompanied me. My phone is 9876543210 and my email is priya.sharma@example.com.
Doctor: Welcome, Priya. What symptoms are you experiencing?
Patient: I have acute bronchitis and high fever.
Doctor: I will prescribe Amoxicillin 500mg and Paracetamol 650mg."""

res = requests.post(f'{BASE}/consultations/{cid}/transcript', headers=headers, json={'transcript': sample}).json()
scrubbed = res.get('transcript', '')
print('=== SCRUBBED TRANSCRIPT ===')
print(scrubbed)

assert "[patient's name]" in scrubbed, "Patient name not masked!"
assert "[patient's phone]" in scrubbed, "Phone not masked!"
assert "[patient's email]" in scrubbed, "Email not masked!"
assert 'bronchitis' in scrubbed, "Medical diagnosis should not be masked!"
assert 'Amoxicillin' in scrubbed, "Medication should not be masked!"
print('\n>>> ALL ASSERTIONS PASSED! <<<')
