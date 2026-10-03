// UI + hash router. All network calls go through api.js. No patient data is logged or put in URLs (ids only).
import { api, session, setSession, clearSession } from "./api.js";

const $ = s => document.querySelector(s);
const app = $("#app");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = d => new Date(d).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
const go = h => { location.hash = h; };
const LOGO = '<span class="logo">✚</span>';

// Kept in memory ONLY (never stored): one-time passkey shown after first approval / reset.
const memory = { reveal: null, reset: null };
let flash = "";

// ---------- Helpers ----------
// Draws header + content. Header shows doctor name/ID or patient ID plus Logout.
function page(html, cls = "") {
  const s = session();
  document.body.className = s.role === "patient" || location.hash.startsWith("#/patient-login") ? "patient" : "";
  const who = s.role === "doctor" ? `<span class="who">${esc(s.name)} (ID: ${esc(s.id)})</span><button class="btn sm" id="lo">Logout</button>`
    : s.role === "patient" ? `<span class="who">Patient ID: ${esc(s.id)}</span><button class="btn sm" id="lo">Logout</button>` : "";
  app.innerHTML = `<header class="top no-print"><a class="brand" href="#/">${LOGO}<span>Clinical Documentation Assistant</span></a><div class="right">${who}</div></header><main class="${cls}">${html}</main>`;
  $("#lo")?.addEventListener("click", () => { clearSession(); go("#/"); });
  window.scrollTo(0, 0);
}
const loading = (t = "Loading...") => page(`<div class="center"><span class="spin"></span><p class="muted">${t}</p></div>`);

// Shows an error page with "Try Again". Patient 403s get a friendly message instead of the raw error.
function fail(e, retry, friendly403) {
  const msg = e.status === 403 && friendly403 ? friendly403 : e.message;
  page(`<div class="card"><div class="err">${esc(msg)}</div><button class="btn primary" id="retry">Try Again</button></div>`);
  $("#retry").onclick = retry;
}
const inlineErr = (el, e) => { el.innerHTML = `<div class="err">${esc(e.message)}</div>`; };

// Disables a button and shows a spinner while an async function runs.
async function busy(btn, label, fn) {
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spin sm"></span> ${label}`;
  try { return await fn(); } finally { if (btn.isConnected) { btn.disabled = false; btn.innerHTML = old; } }
}

// Confirmation dialog -> Promise<boolean>
function confirmBox(title, text, okLabel, danger) {
  return new Promise(res => {
    const o = document.createElement("div"); o.className = "overlay no-print";
    o.innerHTML = `<div class="modal"><h3>${esc(title)}</h3><p>${esc(text)}</p><div class="btns"><button class="btn" id="c-no">Cancel</button><button class="btn ${danger ? "danger" : "primary"}" id="c-ok">${esc(okLabel)}</button></div></div>`;
    document.body.appendChild(o);
    const done = v => { o.remove(); res(v); };
    o.querySelector("#c-no").onclick = () => done(false);
    o.querySelector("#c-ok").onclick = () => done(true);
  });
}

// Turns "Doctor: ...\nPatient: ..." into readable lines (never raw JSON).
function transcriptHtml(t) {
  if (!t) return '<p class="muted">No transcript yet.</p>';
  return String(t).split("\n").filter(l => l.trim()).map(l => {
    const m = l.match(/^(Doctor|Patient):\s*(.*)$/i);
    return m ? `<div class="line"><b class="${m[1][0].toUpperCase()}">${esc(m[1])}:</b> ${esc(m[2])}</div>` : `<div class="line">${esc(l)}</div>`;
  }).join("");
}

// ---------- Public pages ----------
function home() {
  page(`
  <section class="hero">
    <div style="display:inline-flex;align-items:center;gap:6px;background:var(--brand-l);border:1px solid var(--brand-m);color:var(--brand-d);border-radius:99px;padding:5px 14px;font-size:.8rem;font-weight:700;letter-spacing:.04em;margin-bottom:18px">✦ AI-POWERED · PRIVACY-FIRST · DOCTOR-REVIEWED</div>
    <h1>Turn consultations into<br>safe, clear medical records</h1>
    <p>Record a visit, review an AI-drafted clinical note, and give your patient a simple report they can trust — in minutes, not hours.</p>
  </section>
  <div class="grid2">
    <div class="card role"><div class="ico">🩺</div><h2>I'm a Doctor</h2><p class="muted">Record, review and approve clinical notes with AI assistance.</p>
      <div class="btns"><a class="btn primary" href="#/doctor-login">Login</a><a class="btn" href="#/doctor-register">Create Account</a></div></div>
    <div class="card role"><div class="ico">🙂</div><h2>I'm a Patient</h2><p class="muted">Read your visit summary securely with your private passkey.</p>
      <div class="btns"><a class="btn primary" href="#/patient-login">View My Summary</a></div></div>
  </div>
  <h2 style="text-align:center;margin-top:36px;margin-bottom:16px">Why clinics choose it</h2>
  <div class="grid3">
    <div class="card feat"><div class="ico">🎙️</div><b>Voice to structured note</b>Record the consultation and get a complete clinical draft instantly.</div>
    <div class="card feat"><div class="ico">✅</div><b>Doctor approval first</b>Patients see nothing until you review, edit, and approve.</div>
    <div class="card feat"><div class="ico">🔒</div><b>Privacy protected</b>Personally identifiable details are scrubbed from the transcript.</div>
    <div class="card feat"><div class="ico">🔑</div><b>Secure patient access</b>Patients unlock their report with a one-time private passkey.</div>
  </div>
  <footer>Clinical Documentation Assistant · AI drafts always require doctor review before sharing with patients</footer>`);
}

// Generic form page used by the three public auth screens.
function authPage({ title, fields, submit, onSubmit, links }) {
  page(`<div class="card"><h2>${title}</h2><form id="f">
    ${fields.map(f => `<label>${f.label}<input name="${f.name}" type="${f.type || "text"}" autocomplete="off" required></label>`).join("")}
    <div id="msg"></div><button class="btn primary big" style="width:100%;margin-top:16px">${submit}</button></form>
    <p class="small">${links}</p></div>`, "narrow");
  $("#f").onsubmit = async ev => {
    ev.preventDefault();
    const v = Object.fromEntries(new FormData(ev.target));
    $("#msg").innerHTML = "";
    try { await busy(ev.target.querySelector("button"), "Please wait...", () => onSubmit(v)); }
    catch (e) { inlineErr($("#msg"), e); }
  };
}

const docLogin = () => authPage({
  title: "Doctor Login", submit: "Login",
  fields: [{ label: "Doctor ID", name: "id" }, { label: "Passkey", name: "pk", type: "password" }],
  links: '<a href="#/doctor-register">Create account</a> · <a href="#/">← Home</a>',
  onSubmit: async v => { const r = await api.doctorLogin(v.id.trim(), v.pk); setSession({ token: r.token, role: "doctor", id: r.doctor_id, name: r.doctor_name }); go("#/dashboard"); },
});
const patLogin = () => authPage({
  title: "Patient Login", submit: "Login",
  fields: [{ label: "Patient ID", name: "id" }, { label: "Passkey (printed on your report)", name: "pk", type: "password" }],
  links: '<a href="#/">← Home</a>',
  onSubmit: async v => { const r = await api.patientLogin(v.id.trim(), v.pk.trim()); setSession({ token: r.token, role: "patient", id: r.patient_id }); go("#/my"); },
});
const docRegister = () => authPage({
  title: "Create Doctor Account", submit: "Create Account",
  fields: [{ label: "Doctor Name", name: "name" }, { label: "Doctor ID (no spaces)", name: "id" }, { label: "Passkey", name: "pk", type: "password" }, { label: "Confirm Passkey", name: "pk2", type: "password" }],
  links: '<a href="#/doctor-login">Already have an account? Login</a> · <a href="#/">← Home</a>',
  onSubmit: async v => {
    if (/\s/.test(v.id)) throw new Error("Doctor ID cannot contain spaces.");
    if (v.pk !== v.pk2) throw new Error("Passkeys do not match.");
    await api.doctorRegister(v.name.trim(), v.id, v.pk);
    flash = "Account created. Please log in."; go("#/doctor-login");
  },
});

// ---------- Doctor dashboard ----------
async function dashboard() {
  loading("Loading patients...");
  let patients;
  try { patients = await api.listPatients(); } catch (e) { return fail(e, dashboard); }
  const open = new Set(); let q = "", showNew = false, newMsg = "";
  const hasNote = c => ["note_generated", "approved"].includes(c.status);

  const draw = () => {
    const list = patients.filter(p => p.patient_id.toLowerCase().includes(q.toLowerCase()));
    page(`
    <div class="bar"><h2>Patients</h2><button class="btn primary" data-a="new">+ New Consultation</button></div>
    ${flash ? `<div class="ok-msg">${esc(flash)}</div>` : ""}
    ${showNew ? `<div class="card"><h3>New Consultation</h3><label>Patient ID (letters, numbers, dashes. e.g. 101 or P-205)
      <input id="npid" maxlength="40"></label><div id="nmsg">${newMsg}</div>
      <div style="margin-top:12px;display:flex;gap:8px"><button class="btn primary" data-a="start">Start Consultation</button><button class="btn" data-a="cancelnew">Cancel</button></div></div>` : ""}
    <input id="q" placeholder="Search by Patient ID" value="${esc(q)}" style="margin-bottom:16px">
    ${!patients.length ? '<div class="card center muted">No patients yet. Click "New Consultation" to begin.</div>' : ""}
    ${list.map(p => `<div class="card"><div class="prow" data-a="toggle" data-p="${esc(p.patient_id)}">
      <div><b>Patient ID: ${esc(p.patient_id)}</b> <span class="muted">· ${p.consultations.length} consultation(s)</span></div>
      <div class="acts" style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn sm primary" data-a="add" data-p="${esc(p.patient_id)}">Add Consultation</button>
        <button class="btn sm" data-a="reset" data-p="${esc(p.patient_id)}">Reset Passkey</button>
        <button class="btn sm danger" data-a="delp" data-p="${esc(p.patient_id)}">Delete Patient</button></div></div>
      ${open.has(p.patient_id) ? p.consultations.map(c => `<div class="crow"><div>${fmt(c.created_at)} ${c.status === "approved" ? '<span class="badge ok">Approved</span>' : '<span class="badge prog">In progress</span>'}</div>
        <div class="acts">
          ${c.status !== "approved" && !hasNote(c) ? `<a class="btn sm" href="#/record/${c.id}">Continue</a>` : ""}
          ${hasNote(c) ? `<a class="btn sm" href="#/note/${c.id}">View Clinical Note</a>` : '<button class="btn sm" disabled>View Clinical Note</button><span class="small muted">Note not generated</span>'}
          ${c.status === "approved" ? `<a class="btn sm" href="#/report/${c.id}">View Report</a>` : '<button class="btn sm" disabled>View Report</button><span class="small muted">Report not ready</span>'}
          <button class="btn sm danger" data-a="delc" data-c="${c.id}">Delete Consultation</button></div></div>`).join("") : ""}</div>`).join("")}`);
    flash = "";
    $("#q").oninput = e => { q = e.target.value; draw(); $("#q").focus(); $("#q").setSelectionRange(q.length, q.length); };
  };

  // One click handler for the whole dashboard (event delegation)
  app.onclick = async ev => {
    const b = ev.target.closest("[data-a]"); if (!b) return;
    const a = b.dataset.a, pid = b.dataset.p;
    if (a === "toggle") { open.has(pid) ? open.delete(pid) : open.add(pid); return draw(); }
    ev.stopPropagation();
    if (a === "new") { showNew = true; newMsg = ""; return draw(); }
    if (a === "cancelnew") { showNew = false; return draw(); }
    if (a === "add") return startFor(pid);
    if (a === "start") {
      const id = $("#npid").value.trim();
      if (!/^[A-Za-z0-9-]+$/.test(id)) { $("#nmsg").innerHTML = '<div class="err">Use only letters, numbers and dashes (no spaces).</div>'; return; }
      const ex = patients.find(p => p.patient_id === id);
      if (ex && !(await confirmBox("Patient exists", `Patient ID ${id} already exists with ${ex.consultations.length} previous consultation(s). Add a new consultation to this patient?`, "Add Consultation"))) return;
      return startFor(id, b);
    }
    if (a === "reset") {
      if (!(await confirmBox("Reset Passkey", `Create a new passkey for Patient ID ${pid}? The old passkey will stop working.`, "Reset Passkey"))) return;
      try { const r = await busy(b, "Resetting...", () => api.resetPasskey(pid)); memory.reset = { pid, passkey: r.passkey }; go("#/passkey/" + encodeURIComponent(pid)); }
      catch (e) { flash = ""; alert(e.message); }
      return;
    }
    if (a === "delp" || a === "delc") {
      const msg = a === "delp" ? `Delete Patient ID ${pid} and ALL their consultations permanently? This cannot be undone.` : "Delete this consultation permanently?";
      if (!(await confirmBox("Confirm delete", msg, "Delete", true))) return;
      try {
        await busy(b, "Deleting...", () => a === "delp" ? api.deletePatient(pid) : api.deleteConsultation(b.dataset.c));
        flash = a === "delp" ? "Patient deleted." : "Consultation deleted."; dashboard();
      } catch (e) { alert(e.message); }
    }
  };
  async function startFor(pid, btn) {
    try { const c = await (btn ? busy(btn, "Starting...", () => api.createConsultation(pid)) : api.createConsultation(pid)); go("#/record/" + c.id); }
    catch (e) { newMsg = `<div class="err">${esc(e.message)}</div>`; showNew = true; draw(); }
  }
  draw();
}

// ---------- Recording page ----------
async function record(id) {
  loading();
  let c; try { c = await api.getConsultation(id); } catch (e) { return fail(e, () => record(id)); }
  if (c.status === "approved") return go("#/report/" + id);
  page(`
    <div class="bar">
      <div><span class="pid">Patient ${esc(c.patient_id)}</span> <span class="muted small" style="margin-left:8px">${fmt(c.created_at)}</span></div>
      <span class="badge ok" style="font-size:.75rem">🔒 Privacy Protected</span>
    </div>
    <div class="card no-print" id="rec" style="text-align:center;padding:32px 24px">
      <div style="margin-bottom:8px"><span class="dot" id="dot"></span><span id="st" class="muted" style="font-weight:600;font-size:.92rem">Ready to record</span></div>
      <div class="timer" id="tm">00:00</div>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:4px">
        <button class="btn primary big" id="start">● Start Recording</button>
        <button class="btn big" id="pause" disabled>⏸ Pause</button>
        <button class="btn big" id="stop" disabled>⏹ Stop</button>
      </div>
      <div id="rmsg"></div>
      <div id="up" style="margin-top:16px"></div>
    </div>
    <div id="tr"></div>`);

  const showTr = t => {
    $("#tr").innerHTML = `<div class="card"><h3>Conversation Transcript</h3>${transcriptHtml(t)}<div id="gmsg"></div>
      <button class="btn primary big" id="gen" style="margin-top:12px">Generate Clinical Note</button></div>`;
    $("#gen").onclick = async e => {
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.innerHTML = '<span class="spin sm"></span> Checking...';
      const showProgress = (step) => {
        if (btn.isConnected) btn.innerHTML = `<span class="spin sm"></span> ${step}`;
      };
      try {
        await api.generateNote(id, showProgress);
        go("#/note/" + id);
      } catch (er) {
        btn.disabled = false; btn.textContent = "Generate Clinical Note";
        inlineErr($("#gmsg"), er);
      }
    };
  };
  if (c.transcript) showTr(c.transcript);

  // MediaRecorder logic
  let rec, chunks = [], stream, secs = 0, tick;
  const setT = () => { $("#tm").textContent = String(Math.floor(secs / 60)).padStart(2, "0") + ":" + String(secs % 60).padStart(2, "0"); };
  const run = () => { tick = setInterval(() => { secs++; setT(); }, 1000); };
  $("#start").onclick = async () => {
    $("#rmsg").innerHTML = "";
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { $("#rmsg").innerHTML = '<div class="err">Microphone access was denied or is unavailable. Allow microphone permission in your browser settings and try again.</div>'; return; }
    rec = new MediaRecorder(stream); chunks = []; secs = 0; setT();
    rec.ondataavailable = e => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      clearInterval(tick); stream.getTracks().forEach(t => t.stop());
      $("#dot").classList.remove("rec"); $("#st").textContent = "Recording finished";
      const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
      $("#up").innerHTML = '<button class="btn primary big" id="upb">Upload & Process Recording</button><div id="umsg"></div>';
      $("#upb").onclick = async e => {
        const btn = e.currentTarget;
        // Show live progress steps from the background job
        const showProgress = (step) => {
          if (btn.isConnected) btn.innerHTML = `<span class="spin sm"></span> ${step}`;
        };
        try {
          btn.disabled = true; btn.innerHTML = '<span class="spin sm"></span> Uploading...';
          const r = await api.uploadAudio(id, blob, showProgress);
          $("#up").innerHTML = ""; showTr(r.transcript);
        }
        catch (er) { btn.disabled = false; btn.textContent = "Upload & Process Recording"; inlineErr($("#umsg"), er); }
      };
    };
    rec.start(); run();
    $("#dot").classList.add("rec"); $("#st").textContent = "Recording...";
    $("#start").disabled = true; $("#pause").disabled = false; $("#stop").disabled = false; $("#up").innerHTML = "";
  };
  $("#pause").onclick = () => {
    if (rec.state === "recording") { rec.pause(); clearInterval(tick); $("#pause").textContent = "Resume"; $("#dot").classList.remove("rec"); $("#st").textContent = "Paused"; }
    else { rec.resume(); run(); $("#pause").textContent = "Pause"; $("#dot").classList.add("rec"); $("#st").textContent = "Recording..."; }
  };
  $("#stop").onclick = () => { rec.stop(); $("#pause").disabled = true; $("#stop").disabled = true; $("#start").disabled = false; $("#start").textContent = "● Record again"; };
}

// ---------- Clinical note (editable until approved) ----------
async function notePage(id) {
  loading();
  let c; try { c = await api.getConsultation(id); } catch (e) { return fail(e, () => notePage(id)); }
  if (!c.note) return go("#/record/" + id);
  const ro = c.status === "approved";
  const n = { ...c.note };
  ["symptoms", "plan", "missing_information", "medications"].forEach(k => n[k] = Array.isArray(n[k]) ? n[k] : []);

  let noteSuggestions = c.note_generic_suggestions || [];
  if (n.medications.length && (!noteSuggestions.length || noteSuggestions.every(x => !x))) {
    try {
      const res = await api.genericSuggest(n.medications);
      noteSuggestions = res.suggestions || res.generic_suggestions || [];
    } catch {}
  }

  const T = (k, l, r = 2) => `<label>${l}<textarea name="${k}" rows="${r}">${esc(n[k])}</textarea></label>`;
  const L = (k, l) => `<div data-list="${k}"><h4>${l}</h4>${n[k].map((v, i) => `<div class="row"><input value="${esc(v)}"><button type="button" class="btn sm dng-o" data-rm="${k}:${i}">Remove</button></div>`).join("")}<button type="button" class="btn sm" data-add="${k}">+ Add</button></div>`;
  const medRows = () => n.medications.map((m, i) => {
    const sug = noteSuggestions[i];
    return `<div style="margin-bottom:12px;padding:10px 12px;background:hsl(215,20%,97%);border-radius:var(--radius-sm);border:1px solid var(--line)">
      <div class="row" data-med style="margin-bottom:6px">
        <input data-f="name" placeholder="Name" value="${esc(m.name)}" style="flex:2">
        <input data-f="dose" placeholder="Dose" value="${esc(m.dose)}" style="flex:1">
        <input data-f="frequency" placeholder="Frequency" value="${esc(m.frequency)}" style="flex:1.5">
        <button type="button" class="btn sm dng-o" data-rm="medications:${i}">Remove</button>
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        ${sug ? `<button type="button" class="btn ja-btn" data-ja-note-idx="${i}">🏥 Jan Aushadhi Generic: ${esc(sug.generic_name)} · Save Rs ${esc(sug.saving_rs)} (${esc(sug.saving_pct)}%)</button>`
              : `<button type="button" class="btn ja-btn-muted" data-ja-check-note-idx="${i}">🔍 Check Jan Aushadhi generic</button>`}
      </div>
    </div>`;
  }).join("");

  // Copy what is typed in the form back into n (before re-drawing or saving)
  const collect = () => {
    document.querySelectorAll("textarea[name]").forEach(t => n[t.name] = t.value);
    document.querySelectorAll("[data-list]").forEach(d => n[d.dataset.list] = [...d.querySelectorAll("input")].map(i => i.value.trim()).filter(Boolean));
    n.medications = [...document.querySelectorAll("[data-med]")].map(r => ({ name: r.querySelector('[data-f=name]').value.trim(), dose: r.querySelector('[data-f=dose]').value.trim(), frequency: r.querySelector('[data-f=frequency]').value.trim() })).filter(m => m.name);
  };
  const noteHtml = () => `
    <div class="bar"><h2>Clinical Note <span class="muted small">· Patient ${esc(c.patient_id)}</span></h2>${ro ? '<span class="badge ok">✓ Approved</span>' : ""}</div>
    <div class="banner no-print">⚕️ AI-generated draft — please review all fields carefully before approving.</div>
    ${n.missing_information.length ? `<div class="warn"><b>Missing Information.</b> The following was not available in the transcript:<ul>${n.missing_information.map(m => `<li>${esc(m)}</li>`).join("")}</ul></div>` : ""}
    <div class="card"><form id="nf" class="${ro ? "ro" : ""}"><fieldset ${ro ? "disabled" : ""}>
      ${T("chief_complaint", "Chief complaint")}${T("history_of_present_illness", "History of present illness", 4)}${L("symptoms", "Symptoms")}
      ${T("past_medical_history", "Past medical history")}
      <div data-meds><h4>Medications</h4>${medRows()}<button type="button" class="btn sm" data-add="medications">+ Add</button></div>
      ${T("allergies", "Allergies")}${T("examination_findings", "Examination findings", 3)}${T("assessment", "Assessment")}${L("plan", "Plan")}${T("follow_up", "Follow-up")}${L("missing_information", "Missing information")}
    </fieldset></form><div id="fb"></div>
    <div class="no-print" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:16px">
      ${ro ? '<button class="btn primary" id="pr">Print Note</button><a class="btn" href="#/dashboard">Back to Dashboard</a>'
        : '<button class="btn" id="sv">Save Edits</button><button class="btn primary" id="ap">Approve & View</button><a class="btn" href="#/dashboard">Back to Dashboard</a>'}</div></div>
    <div class="card"><h3>Transcript</h3>${transcriptHtml(c.transcript)}</div>`;

  const draw = () => {
    page(noteHtml());
    $("#pr")?.addEventListener("click", () => window.print());

    // Jan Aushadhi button listeners on Note page
    document.querySelectorAll("[data-ja-note-idx]").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = +btn.dataset.jaNoteIdx;
        const sug = noteSuggestions[idx];
        if (sug) showJaPopup(sug);
      });
    });

    document.querySelectorAll("[data-ja-check-note-idx]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const idx = +btn.dataset.jaCheckNoteIdx;
        collect();
        const med = n.medications[idx];
        if (!med) return;
        btn.disabled = true;
        btn.textContent = "Checking...";
        try {
          const res = await api.genericSuggest([med]);
          const sug = (res.suggestions || res.generic_suggestions || [])[0];
          if (sug) {
            noteSuggestions[idx] = sug;
            showJaPopup(sug);
            draw();
          } else {
            showJaNotFound(med.name || "this medicine");
          }
        } catch {
          showJaNotFound(med.name || "this medicine");
        } finally {
          btn.disabled = false;
        }
      });
    });

    $("#nf").onclick = e => {
      const rm = e.target.closest("[data-rm]"), ad = e.target.closest("[data-add]");
      if (!rm && !ad) return;
      collect();
      if (rm) {
        const [k, i] = rm.dataset.rm.split(":");
        n[k].splice(+i, 1);
        if (k === "medications") noteSuggestions.splice(+i, 1);
      }
      else if (ad.dataset.add === "medications") {
        n.medications.push({ name: "", dose: "", frequency: "" });
        noteSuggestions.push(null);
      }
      else n[ad.dataset.add].push("");
      draw();
    };
    const save = async () => { collect(); await api.saveNote(id, n); };
    $("#sv")?.addEventListener("click", async e => {
      try { await busy(e.currentTarget, "Saving...", save); $("#fb").innerHTML = '<div class="ok-msg">Edits saved.</div>'; }
      catch (er) { inlineErr($("#fb"), er); }
    });
    $("#ap")?.addEventListener("click", async e => {
      const btn = e.currentTarget;
      if (!(await confirmBox("Approve Clinical Note?", "Please make sure you have reviewed the AI-generated documentation before the summary is created for the patient.", "Approve & View"))) return;
      try {
        const r = await busy(btn, "Approving...", async () => { await save(); return api.approve(id); });
        const cons = r.consultation || r;
        memory.reveal = { id, patient_id: r.patient_id || cons.patient_id, passkey: r.passkey || null };
        go("#/report/" + id);
      } catch (er) { inlineErr($("#fb"), er); }
    });
  };
  draw();
}

// ---------- Jan Aushadhi popup modal ----------
function showJaPopup(sug) {
  const o = document.createElement("div");
  o.className = "overlay no-print";
  o.id = "ja-overlay";
  o.innerHTML = `
    <div class="modal ja-modal">
      <div class="ja-modal-header">
        <span class="ja-modal-icon">🏥</span>
        <div>
          <h3 style="margin:0 0 2px">Jan Aushadhi Generic</h3>
          <p style="margin:0;font-size:.82rem;color:var(--mut)">Government of India generic medicine</p>
        </div>
      </div>
      <div class="ja-modal-body">
        <div class="ja-modal-row">
          <span class="ja-modal-label">Generic Medicine</span>
          <span class="ja-modal-value ja-green"><b>${esc(sug.generic_name)}</b></span>
        </div>
        <div class="ja-modal-row">
          <span class="ja-modal-label">Jan Aushadhi Price</span>
          <span class="ja-modal-value ja-green"><b>Rs ${esc(sug.generic_price)}</b> per unit</span>
        </div>
        <div class="ja-modal-row">
          <span class="ja-modal-label">Brand Price</span>
          <span class="ja-modal-value">Rs ${esc(sug.brand_price)} per unit</span>
        </div>
        <div class="ja-savings-banner">
          <span class="ja-savings-icon">💰</span>
          <div>
            <div class="ja-savings-main">Save Rs ${esc(sug.saving_rs)} (${esc(sug.saving_pct)}%)</div>
            <div class="ja-savings-sub">same active ingredient · same strength · same form</div>
          </div>
        </div>
        <div class="ja-disclaimer">⚠️ Suggestion only. Confirm with your doctor before switching medicines.</div>
      </div>
      <div class="btns" style="margin-top:20px">
        <button class="btn primary" id="ja-close">Close</button>
      </div>
    </div>`;
  document.body.appendChild(o);
  const close = () => { o.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = e => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  o.querySelector("#ja-close").onclick = close;
  o.addEventListener("click", e => { if (e.target === o) close(); });
}

function showJaNotFound(name) {
  const o = document.createElement("div");
  o.className = "overlay no-print";
  o.innerHTML = `
    <div class="modal ja-modal">
      <div class="ja-modal-header">
        <span class="ja-modal-icon">ℹ️</span>
        <div>
          <h3 style="margin:0 0 2px">Jan Aushadhi Generic</h3>
          <p style="margin:0;font-size:.82rem;color:var(--mut)">Government of India generic medicine</p>
        </div>
      </div>
      <div class="ja-modal-body">
        <p>No cheaper government Jan Aushadhi generic equivalent was found in the dataset for <b>${esc(name)}</b> with matching active ingredients, strength, and dosage form.</p>
        <p class="muted small" style="margin-top:8px">Jan Aushadhi substitutions require an exact match on active ingredient(s), dosage strength, and form.</p>
      </div>
      <div class="btns" style="margin-top:20px">
        <button class="btn primary" id="ja-nf-close">Close</button>
      </div>
    </div>`;
  document.body.appendChild(o);
  const close = () => o.remove();
  o.querySelector("#ja-nf-close").onclick = close;
  o.addEventListener("click", e => { if (e.target === o) close(); });
}

// ---------- Patient report (shared by doctor + patient views) ----------
function reportHtml(s) {
  const ul = (a, ic) => !a?.length ? '' : `<ul>${a.map(x => `<li>${ic} ${esc(x)}</li>`).join("")}</ul>`;
  const suggestions = s.generic_suggestions || [];

  const medicinesHtml = (s.medicines || []).length
    ? `<ul class="med-list">${s.medicines.map((m, idx) => {
        const sug = suggestions[idx];
        return `<li class="med-item">
          <div class="med-line">
            <span>💊 <b>${esc(m.name)}</b> — ${esc(m.how_to_take)}</span>
            ${sug ? `<button type="button" class="btn ja-btn" data-ja-idx="${idx}">🏥 Jan Aushadhi Generic (Save Rs ${esc(sug.saving_rs)})</button>`
                  : `<button type="button" class="btn ja-btn-muted" data-ja-check-idx="${idx}">🔍 Check Jan Aushadhi</button>`}
          </div>
          ${sug ? `<div class="ja-note-hint" style="margin-top:4px;font-size:.84rem;color:var(--green)">✓ Inexpensive Gov't generic: <b>${esc(sug.generic_name)}</b> @ Rs ${esc(sug.generic_price)} (Save Rs ${esc(sug.saving_rs)} · ${esc(sug.saving_pct)}%)</div>` : ''}
        </li>`;
      }).join("")}</ul>`
    : '<p class="muted">None prescribed.</p>';

  return `<div class="rep">
    <h3>Summary</h3><p>${esc(s.summary)}</p>
    <h3>What the doctor found</h3><p>${esc(s.what_the_doctor_found)}</p>
    <h3>Your medicines</h3>${medicinesHtml}
    <h3>What to do</h3>${ul(s.what_to_do, "✅") || '<p class="muted">No specific instructions.</p>'}
    ${s.warning_signs?.length ? `<h3>Warning signs — seek care if you notice:</h3>${ul(s.warning_signs, "⚠️")}` : ''}
    <h3>Follow-up</h3><p>${esc(s.follow_up)}</p>
    <p class="muted small" style="margin-top:16px;padding-top:12px;border-top:1px solid var(--line)">This is a patient-friendly summary of your visit. Always follow your doctor's direct instructions.</p></div>`;
}

function attachJaButtons(medicines, suggestions) {
  document.querySelectorAll("[data-ja-idx]").forEach(btn => {
    btn.addEventListener("click", () => {
      const sug = suggestions[+btn.dataset.jaIdx];
      if (sug) showJaPopup(sug);
    });
  });

  document.querySelectorAll("[data-ja-check-idx]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const idx = +btn.dataset.jaCheckIdx;
      const med = medicines[idx];
      if (!med) return;
      btn.disabled = true;
      btn.textContent = "Checking...";
      try {
        const res = await api.genericSuggest([med]);
        const s = (res.suggestions || res.generic_suggestions || [])[0];
        if (s) {
          suggestions[idx] = s;
          showJaPopup(s);
          btn.className = "btn ja-btn";
          btn.textContent = `🏥 Jan Aushadhi Generic (Save Rs ${s.saving_rs})`;
          btn.removeAttribute("data-ja-check-idx");
          btn.setAttribute("data-ja-idx", idx);
        } else {
          showJaNotFound(med.name || "this medicine");
        }
      } catch {
        showJaNotFound(med.name || "this medicine");
      } finally {
        btn.disabled = false;
      }
    });
  });
}

async function report(id) {
  loading();
  const rv = memory.reveal && memory.reveal.id === id ? memory.reveal : null; memory.reveal = null;
  let c; try { c = await api.getConsultation(id); } catch (e) { return fail(e, () => report(id)); }
  if (c.status !== "approved" || !c.patient_summary) return go("#/note/" + id);
  if (!c.patient_summary.generic_suggestions || c.patient_summary.generic_suggestions.every(x => !x)) {
    if (c.generic_suggestions && c.generic_suggestions.some(Boolean)) {
      c.patient_summary.generic_suggestions = c.generic_suggestions;
    } else if (c.patient_summary.medicines?.length) {
      try {
        const res = await api.genericSuggest(c.patient_summary.medicines);
        c.patient_summary.generic_suggestions = res.suggestions || res.generic_suggestions;
      } catch { /* graceful fallback */ }
    }
  }
  page(`<div class="card"><p class="muted small">Patient ID</p><span class="pid">${esc(c.patient_id)}</span>
    ${rv?.passkey ? `<p style="margin-top:16px"><b>Patient passkey</b></p><span class="key">${esc(rv.passkey)}</span><div class="warn" style="margin-top:12px"><b>Keep this passkey private. Do not share it.</b></div>`
      : '<p class="muted">Use the passkey you received earlier.</p>'}
    <hr style="border:0;border-top:1px solid var(--line);margin:16px 0">${reportHtml(c.patient_summary)}
    <div class="no-print" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:16px"><button class="btn primary" id="pr">Print</button><a class="btn" href="#/dashboard">${rv ? "Home" : "Back to Dashboard"}</a></div></div>`);
  $("#pr").onclick = () => window.print();
  attachJaButtons(c.patient_summary.medicines || [], c.patient_summary.generic_suggestions || []);
}

function passkeyPage(pid) {
  const r = memory.reset && memory.reset.pid === pid ? memory.reset : null; memory.reset = null;
  if (!r) return go("#/dashboard");
  page(`<div class="card"><h2>New Patient Passkey</h2><p class="muted small">Patient ID</p><span class="pid">${esc(r.pid)}</span>
    <p style="margin-top:16px"><b>New passkey (shown once)</b></p><span class="key">${esc(r.passkey)}</span>
    <div class="warn" style="margin-top:12px"><b>Keep this passkey private. Do not share it.</b> The old passkey no longer works.</div>
    <div class="no-print" style="display:flex;gap:8px;margin-top:16px"><button class="btn primary" id="pr">Print</button><a class="btn" href="#/dashboard">Back</a></div></div>`);
  $("#pr").onclick = () => window.print();
}

// ---------- Patient side ----------
const NONE = "Your doctor hasn't approved any summary yet.";
async function myList() {
  loading();
  let list;
  try { list = await api.myConsultations(); }
  catch (e) { if (e.status === 403) list = []; else return fail(e, myList); }
  page(`<h2>Your visit summaries</h2>${list.length ? list.map(c => `<a class="card pcard" href="#/my/${c.id}"><b>${esc(c.title || "Visit summary")}</b><div class="muted">${fmt(c.created_at)}</div></a>`).join("") : `<div class="card center">${NONE}</div>`}`);
}
async function myReport(id) {
  loading();
  let c; try { c = await api.myReport(id); } catch (e) { return fail(e, () => myReport(id), NONE); }
  if (c.patient_summary && (!c.patient_summary.generic_suggestions || c.patient_summary.generic_suggestions.every(x => !x))) {
    if (c.generic_suggestions && c.generic_suggestions.some(Boolean)) {
      c.patient_summary.generic_suggestions = c.generic_suggestions;
    } else if (c.patient_summary.medicines?.length) {
      try {
        const res = await api.genericSuggest(c.patient_summary.medicines);
        c.patient_summary.generic_suggestions = res.suggestions || res.generic_suggestions;
      } catch { /* graceful fallback */ }
    }
  }
  page(`<div class="card"><p class="muted">${fmt(c.created_at)}</p>${reportHtml(c.patient_summary)}
    <div class="no-print" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:16px"><button class="btn primary big" id="pr">Print</button><a class="btn big" href="#/my">Back</a></div></div>`);
  $("#pr").onclick = () => window.print();
  attachJaButtons((c.patient_summary || {}).medicines || [], (c.patient_summary || {}).generic_suggestions || []);
}

// ---------- Router with role guard ----------
const routes = [
  ["", home, null], ["doctor-login", docLogin, null], ["doctor-register", docRegister, null], ["patient-login", patLogin, null],
  ["dashboard", dashboard, "doctor"], ["record/:id", record, "doctor"], ["note/:id", notePage, "doctor"], ["report/:id", report, "doctor"], ["passkey/:id", passkeyPage, "doctor"],
  ["my", myList, "patient"], ["my/:id", myReport, "patient"],
];
function router() {
  app.onclick = null;
  const parts = (location.hash.replace(/^#\/?/, "") || "").split("/");
  const s = session();
  for (const [pattern, fn, role] of routes) {
    const pp = pattern ? pattern.split("/") : [""];
    if (pp.length !== parts.length || pp[0] !== parts[0]) continue;
    // Role guard: wrong or missing login -> redirect (works even if URL is typed)
    if (role && s.role !== role) return go(s.role === "doctor" ? "#/dashboard" : s.role === "patient" ? "#/my" : role === "doctor" ? "#/doctor-login" : "#/patient-login");
    const arg = pp[1] ? decodeURIComponent(parts[1]) : undefined;
    if (!role && pattern === "doctor-login" && flash) { const f = flash; flash = ""; fn(); $("#msg").innerHTML = `<div class="ok-msg">${esc(f)}</div>`; return; }
    return fn(arg);
  }
  go("#/");
}
window.addEventListener("hashchange", router);
router();