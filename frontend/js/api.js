// =====================================================================
// CONFIG  –  change USE_MOCK_API to false when the backend is running
// =====================================================================
const CONFIG = {
  USE_MOCK_API: false,                   // ← real Flask API
  API_BASE_URL: "http://localhost:5000",  // ← Flask dev server
};

// =====================================================================
// SESSION  –  kept only in memory (token never in localStorage)
// =====================================================================
let _sess = { token: null, role: null, id: null, name: null };
export const session = () => _sess;
export const setSession = (s) => { _sess = { ..._sess, ...s }; };
export const clearSession = () => { _sess = { token: null, role: null, id: null, name: null }; };

// =====================================================================
// API ERROR
// =====================================================================
class ApiError extends Error {
  constructor(msg, status = 0) { super(msg); this.status = status; }
}

// ---- Real backend call ----
const DEFAULT_MSG = { 400: "Invalid request.", 401: "Please log in again.", 403: "You do not have access to this.", 404: "Not found.", 500: "Server error. Please try again." };
async function real(method, path, body) {
  const headers = {}, opt = { method, headers };
  const t = session().token;
  if (t) headers.Authorization = "Bearer " + t;
  if (body instanceof FormData) opt.body = body;               // multipart (audio)
  else if (body) { headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(CONFIG.API_BASE_URL + path, opt); }
  catch { throw new ApiError("Cannot reach the server. Check your connection and try again.", 0); }
  let data = null;
  try { data = await r.json(); } catch { /* non-JSON body: ignore (never show raw HTML/stack traces) */ }
  if (!r.ok) throw new ApiError(data?.error || DEFAULT_MSG[r.status] || "Something went wrong.", r.status);
  return data;
}

// One entry point. A 401 (outside the login calls) logs out and sends the user to login.
async function request(method, path, body) {
  try { return await (CONFIG.USE_MOCK_API ? mock(method, path, body) : real(method, path, body)); }
  catch (e) {
    if (e.status === 401 && !path.includes("/auth/")) {
      const role = session().role; clearSession();
      location.hash = role === "patient" ? "#/patient-login" : "#/doctor-login";
    }
    throw e;
  }
}

// ---- Public API used by the UI ----
export const api = {
  doctorRegister: (doctor_name, doctor_id, passkey) => request("POST", "/api/auth/doctor-register", { doctor_name, doctor_id, passkey }),
  doctorLogin: (doctor_id, passkey) => request("POST", "/api/auth/doctor-login", { doctor_id, passkey }),
  patientLogin: (patient_id, passkey) => request("POST", "/api/auth/patient-login", { patient_id, passkey }),
  listPatients: () => request("GET", "/api/patients"),
  createConsultation: (pid) => request("POST", `/api/patients/${enc(pid)}/consultations`),
  deletePatient: (pid) => request("DELETE", `/api/patients/${enc(pid)}`),
  deleteConsultation: (id) => request("DELETE", `/api/consultations/${enc(id)}`),
  uploadAudio: async (id, blob, onProgress) => {
    const f = new FormData();
    f.append("audio", blob, "recording.webm");
    // Step 1: submit → get job_id back immediately (202)
    const { job_id } = await request("POST", `/api/consultations/${enc(id)}/audio`, f);
    // Step 2: poll until done or error
    return new Promise((resolve, reject) => {
      const INTERVAL = 1500; // ms between polls
      const poll = async () => {
        let job;
        try { job = await request("GET", `/api/jobs/${enc(job_id)}`); }
        catch (e) { return reject(e); }
        if (typeof onProgress === "function") onProgress(job.step || job.status);
        if (job.status === "done") return resolve(job.result);
        if (job.status === "error") return reject(new ApiError(job.error || "Processing failed."));
        setTimeout(poll, INTERVAL);
      };
      poll();
    });
  },
  getConsultation: (id) => request("GET", `/api/consultations/${enc(id)}`),
  generateNote: async (id, onProgress) => {
    // POST always returns either 200 (pre-generated, instant) or 202 (job to poll)
    // We need raw response to detect the status code, so call real() directly.
    const headers = {}, opt = { method: "POST", headers };
    const t = session().token;
    if (t) headers.Authorization = "Bearer " + t;
    let resp;
    try { resp = await fetch(CONFIG.API_BASE_URL + `/api/consultations/${enc(id)}/generate-note`, opt); }
    catch { throw new ApiError("Cannot reach the server. Check your connection and try again.", 0); }
    let data = null;
    try { data = await resp.json(); } catch { /* ignore */ }
    if (!resp.ok) throw new ApiError(data?.error || "Note generation failed.", resp.status);

    // 200 = note was pre-generated, return immediately
    if (resp.status === 200) return data;

    // 202 = job started or already running, poll it
    const { job_id } = data;
    return new Promise((resolve, reject) => {
      const poll = async () => {
        let job;
        try { job = await request("GET", `/api/jobs/${enc(job_id)}`); }
        catch (e) { return reject(e); }
        if (typeof onProgress === "function") onProgress(job.step || job.status);
        if (job.status === "done") return resolve(job.result);
        if (job.status === "error") return reject(new ApiError(job.error || "Note generation failed."));
        setTimeout(poll, 1500);
      };
      if (typeof onProgress === "function") onProgress("Writing clinical note...");
      poll();
    });
  },
  saveNote: (id, note) => request("PUT", `/api/consultations/${enc(id)}/note`, { note }),
  approve: (id) => request("POST", `/api/consultations/${enc(id)}/approve`),
  resetPasskey: (pid) => request("POST", `/api/patients/${enc(pid)}/reset-passkey`),
  myConsultations: () => request("GET", "/api/patient/consultations"),
  myReport: (id) => request("GET", `/api/patient/consultations/${enc(id)}`),
  genericSuggest: (medications) => request("POST", "/api/generic-suggest", { medications }),
};
const enc = encodeURIComponent;

// =====================================================================
// MOCK LAYER (mock mode only: data lives in localStorage so it survives refresh)
// Shape: patients -> { passHash, consultations: [ ... ] }
// =====================================================================
const KEY = "cda_mock_db_v1";
const wait = () => new Promise(r => setTimeout(r, 400));
const hash = s => btoa([...s].reverse().join("") + "#cda"); // simple obfuscation, NOT real security
const save = d => localStorage.setItem(KEY, JSON.stringify(d));
function db() {
  let d = JSON.parse(localStorage.getItem(KEY) || "null");
  if (!d) {
    d = { doctors: {}, patients: {} };
    [["D101", "Dr. Sarah"], ["D102", "Dr. Arjun"], ["D103", "Dr. Meera"]].forEach(([i, n]) => d.doctors[i] = { name: n, pw: hash("password") });
    save(d);
  }
  return d;
}
const bad = (m, s = 400) => { throw new ApiError(m, s); };
const rid = () => Math.random().toString(36).slice(2, 12);
const CH = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const newKey = () => Array.from({ length: 8 }, () => CH[Math.floor(Math.random() * CH.length)]).join("");
const pub = (pid, c) => ({ id: c.id, patient_id: pid, status: c.status, transcript: c.transcript, note: c.note, patient_summary: c.patient_summary, created_at: c.created_at });
function find(d, id) { for (const pid in d.patients) { const c = d.patients[pid].consultations.find(x => x.id === id); if (c) return [pid, c]; } bad("Consultation not found", 404); }

const SAMPLE_TRANSCRIPT = "Doctor: Good morning, what brings you in today?\nPatient: I have had stomach pain in my lower belly since this morning, after eating outside food yesterday.\nDoctor: Any vomiting or fever?\nPatient: No vomiting, a little fever last night. I am allergic to penicillin.\nDoctor: Let me examine you. The abdomen is tender on the lower right side but soft.\nDoctor: I will prescribe paracetamol 500 mg twice a day for three days, and ORS after each loose stool. Avoid outside food.\nDoctor: Come back in three days, or earlier if the pain gets worse or you have a high fever.";
const SAMPLE_NOTE = {
  chief_complaint: "Stomach pain in lower belly",
  history_of_present_illness: "Stomach pain in the lower belly since this morning after eating outside food yesterday. Mild fever last night. Denies vomiting.",
  symptoms: ["Lower abdominal pain", "Fever last night"], past_medical_history: "Not discussed",
  medications: [{ name: "Paracetamol", dose: "500 mg", frequency: "twice a day for three days" }, { name: "ORS", dose: "Not stated", frequency: "after each loose stool" }],
  allergies: "Penicillin", examination_findings: "Abdomen tender on the lower right side but soft.", assessment: "Not discussed",
  plan: ["Paracetamol 500 mg twice a day for three days", "ORS after each loose stool", "Avoid outside food"],
  follow_up: "Return in three days, or earlier if pain worsens or high fever develops.",
  missing_information: ["Specific diagnosis was not stated by the doctor."],
};
const SAMPLE_SUMMARY = {
  summary: "You came in with stomach pain in your lower belly that began this morning, with a mild fever last night. The doctor examined you and gave you medicine to help you recover.",
  what_the_doctor_found: "Your belly was soft, but tender on the lower right side.",
  medicines: [{ name: "Paracetamol (500 mg)", how_to_take: "Take twice a day for three days." }, { name: "ORS", how_to_take: "Drink after each loose stool." }],
  what_to_do: ["Take your medicines as directed.", "Avoid eating outside food."],
  warning_signs: ["Pain gets worse", "High fever"], follow_up: "Return in three days, or earlier if you feel worse.",
};

async function mock(method, path, body) {
  await wait();
  const d = db(), u = session();
  const need = role => { if (!u.token) bad("Please log in again.", 401); if (u.role !== role) bad("Not allowed.", 403); };
  let m;
  const is = (meth, re) => method === meth && (m = path.match(re));

  if (is("POST", /^\/api\/auth\/doctor-register$/)) {
    const { doctor_name, doctor_id, passkey } = body;
    if (!doctor_name || !doctor_id || !passkey) bad("All fields are required.");
    if (/\s/.test(doctor_id)) bad("Doctor ID cannot contain spaces.");
    if (d.doctors[doctor_id]) bad("That Doctor ID is already taken.", 409);
    d.doctors[doctor_id] = { name: doctor_name, pw: hash(passkey) }; save(d);
    return { ok: true };
  }
  if (is("POST", /^\/api\/auth\/doctor-login$/)) {
    const doc = d.doctors[body.doctor_id];
    if (!doc || doc.pw !== hash(body.passkey)) bad("Incorrect Doctor ID or passkey.", 401);
    return { token: "mock-d-" + rid(), doctor_id: body.doctor_id, doctor_name: doc.name };
  }
  if (is("POST", /^\/api\/auth\/patient-login$/)) {
    const p = d.patients[body.patient_id];
    if (!p || !p.passHash || p.passHash !== hash(String(body.passkey).toUpperCase())) bad("Incorrect Patient ID or passkey.", 401);
    return { token: "mock-p-" + rid(), patient_id: body.patient_id };
  }
  // ---- doctor endpoints ----
  if (is("GET", /^\/api\/patients$/)) {
    need("doctor");
    return Object.entries(d.patients).map(([pid, p]) => ({ patient_id: pid, consultations: p.consultations.map(c => ({ id: c.id, status: c.status, created_at: c.created_at })) }));
  }
  if (is("POST", /^\/api\/patients\/([^/]+)\/consultations$/)) {
    need("doctor"); const pid = decodeURIComponent(m[1]);
    const p = d.patients[pid] ||= { passHash: null, consultations: [] };
    const c = { id: rid(), status: "created", transcript: "", note: null, patient_summary: null, created_at: new Date().toISOString() };
    p.consultations.push(c); save(d); return pub(pid, c);
  }
  if (is("DELETE", /^\/api\/patients\/([^/]+)$/)) { need("doctor"); delete d.patients[decodeURIComponent(m[1])]; save(d); return { ok: true }; }
  if (is("DELETE", /^\/api\/consultations\/([^/]+)$/)) {
    need("doctor"); const [pid, c] = find(d, m[1]); const p = d.patients[pid];
    p.consultations = p.consultations.filter(x => x !== c && x.id !== c.id); save(d); return { ok: true };
  }
  if (is("POST", /^\/api\/patients\/([^/]+)\/reset-passkey$/)) {
    need("doctor"); const p = d.patients[decodeURIComponent(m[1])]; if (!p) bad("Patient not found", 404);
    const k = newKey(); p.passHash = hash(k); save(d); return { passkey: k };
  }
  if (is("POST", /^\/api\/consultations\/([^/]+)\/audio$/)) {
    need("doctor"); const [pid, c] = find(d, m[1]);
    c.transcript = SAMPLE_TRANSCRIPT; if (c.status === "created") c.status = "transcribed"; save(d); return pub(pid, c);
  }
  if (is("GET", /^\/api\/consultations\/([^/]+)$/)) { need("doctor"); const [pid, c] = find(d, m[1]); return pub(pid, c); }
  if (is("POST", /^\/api\/consultations\/([^/]+)\/generate-note$/)) {
    need("doctor"); const [pid, c] = find(d, m[1]);
    if (!c.transcript) bad("No transcript yet");
    if (c.status === "approved") bad("Already approved; note is locked", 409);
    c.note = structuredClone(SAMPLE_NOTE); c.status = "note_generated"; save(d); return pub(pid, c);
  }
  if (is("PUT", /^\/api\/consultations\/([^/]+)\/note$/)) {
    need("doctor"); const [pid, c] = find(d, m[1]);
    if (c.status === "approved") bad("Already approved; note is locked", 409);
    if (!body?.note) bad("'note' object is required");
    c.note = body.note; c.status = "note_generated"; save(d); return pub(pid, c);
  }
  if (is("POST", /^\/api\/consultations\/([^/]+)\/approve$/)) {
    need("doctor"); const [pid, c] = find(d, m[1]); const p = d.patients[pid];
    if (!c.note) bad("Generate a note first");
    c.patient_summary = structuredClone(SAMPLE_SUMMARY); c.status = "approved";
    const out = { consultation: pub(pid, c), patient_id: pid };
    if (!p.passHash) { const k = newKey(); p.passHash = hash(k); out.passkey = k; } // first approval only
    save(d); return out;
  }
  // ---- patient endpoints ----
  if (is("GET", /^\/api\/patient\/consultations$/)) {
    need("patient");
    return d.patients[u.id].consultations.filter(c => c.status === "approved")
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map(c => ({ id: c.id, created_at: c.created_at, title: c.note?.chief_complaint || "Visit summary" }));
  }
  if (is("GET", /^\/api\/patient\/consultations\/([^/]+)$/)) {
    need("patient"); const c = d.patients[u.id].consultations.find(x => x.id === m[1]);
    if (!c || c.status !== "approved") bad("Not available", 403);
    return { id: c.id, created_at: c.created_at, patient_summary: c.patient_summary };
  }
  if (is("POST", /^\/api\/generic-suggest$/)) {
    const meds = body?.medications || body?.medicines || [];
    const suggestions = meds.map(m => {
      const name = String(m?.name || m?.brand_name || m || "").toLowerCase();
      if (name.includes("crocin") || name.includes("paracetamol")) {
        return { brand_name: "Crocin", brand_price: 2.5, generic_name: "Paracetamol 500mg Tab", generic_price: 1.5, saving_rs: 1.0, saving_pct: 40.0 };
      }
      if (name.includes("imatnib") || name.includes("imatinib")) {
        return { brand_name: "Imatinib", brand_price: 4500.0, generic_name: "Imatinib 400mg Tab", generic_price: 35.0, saving_rs: 4465.0, saving_pct: 99.2 };
      }
      if (name.includes("pan") || name.includes("pantoprazole")) {
        return { brand_name: "Pan 40", brand_price: 12.0, generic_name: "Pantoprazole 40mg Tab", generic_price: 3.5, saving_rs: 8.5, saving_pct: 70.8 };
      }
      return null;
    });
    return { suggestions, generic_suggestions: suggestions };
  }
  bad("Not found", 404);
}