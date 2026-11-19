const LANG_LABEL = {
  "hi-IN": "Hindi",
  "mr-IN": "Marathi",
  "en-IN": "English",
  "es-ES": "Spanish",
};
const COLORS = ["#1F4E4A", "#7A5C3E", "#B4711F", "#3E5C7A", "#5C3E7A"];

let selectedId = null;
let pollTimer = null;
const summaryCache = {};

function healthLines(h) {
  if (!h) return [];
  const lines = [];
  if (h.bp_systolic) lines.push("BP " + h.bp_systolic + "/" + (h.bp_diastolic || "—"));
  if (h.sugar_fasting) lines.push("Sugar (fasting) " + h.sugar_fasting);
  if (h.sugar_pp) lines.push("Sugar (PP) " + h.sugar_pp);
  if (h.pulse) lines.push("Pulse " + h.pulse);
  if (h.sleep_quality) lines.push("Sleep: " + h.sleep_quality);
  if (h.food_intake) lines.push("Food: " + h.food_intake);
  if (h.water_intake) lines.push("Water: " + h.water_intake);
  if (h.mood) lines.push("Mood: " + h.mood);
  if (h.energy_level) lines.push("Energy: " + h.energy_level);
  if (h.headache) lines.push("Headache");
  if (h.dizziness) lines.push("Dizziness");
  if (h.chest_discomfort) lines.push("Chest discomfort");
  if (h.body_pain) lines.push("Body pain");
  if (h.breathing_ok === 0 || h.breathing_ok === false) lines.push("Breathing not OK");
  if (h.notes) lines.push(h.notes);
  return lines;
}

function fmtWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderTurns(turns) {
  const list = (turns || []).filter((t) => String(t.message || "").trim());
  if (!list.length) {
    return '<p class="muted-note">No transcript yet. After the call ends, tap Refresh last call — health notes arrive a few seconds after hang-up.</p>';
  }
  return list.map((t) => {
    const isUser = t.role === "user";
    const who = isUser ? "Them" : "Saathi";
    const cls = isUser ? "parent" : "ai";
    return '<div class="bubble ' + cls + '"><span class="who">' + who + "</span>" +
      escapeHtml(t.message) + "</div>";
  }).join("");
}

function renderCallChips(calls, skipFirst) {
  const list = (calls || []).slice(skipFirst ? 1 : 0, skipFirst ? 8 : 8);
  if (!list.length) return '<p class="muted-note">No earlier calls.</p>';
  return list.map((c) =>
    '<div class="call-chip" data-session="' + escapeHtml(c.session_id) + '">' +
      '<div class="when">' + fmtWhen(c.ended_at) + " · " + (c.user_turns || 0) + " replies</div>" +
      escapeHtml(c.preview || "No user speech") +
    "</div>"
  ).join("");
}

async function loadSummary(phone) {
  if (!phone) return null;
  try {
    const s = await fetchUserSummary(phone);
    if (s) summaryCache[phone] = s;
    return s;
  } catch (e) {
    return summaryCache[phone] || null;
  }
}

function applyCompanionSummary(s) {
  const notes = document.getElementById("today-notes");
  const tx = document.getElementById("companion-transcript");
  const callsEl = document.getElementById("companion-calls");
  if (!notes) return;
  if (!s) {
    notes.textContent = "Nothing yet. After your first live call, what you told Saathi will show here.";
    if (tx) tx.innerHTML = "";
    if (callsEl) callsEl.innerHTML = "";
    return;
  }
  const lines = healthLines((s.last_call && s.last_call.health) || s.latest_health);
  if (s.alert && s.alert.level && s.alert.level !== "green") {
    notes.innerHTML = "<b>" + escapeHtml(s.alert.level) + "</b> — " + escapeHtml(s.alert.reason || "");
  } else if (lines.length) {
    notes.innerHTML = lines.map((l) => "<div>" + escapeHtml(l) + "</div>").join("");
  } else if (s.last_call) {
    notes.textContent = "Last call " + fmtWhen(s.last_call.ended_at) +
      (s.last_call.user_turns ? "." : ". Health notes still empty — wait a few seconds after hang-up.");
  } else {
    notes.textContent = "Nothing yet. After your first live call, what you told Saathi will show here.";
  }
  if (tx) tx.innerHTML = renderTurns(s.last_call && s.last_call.turns);
  if (callsEl) {
    callsEl.innerHTML = renderCallChips(s.calls, true);
    bindCallChips(callsEl, (loadProfile() || {}).phone, applyCompanionCall);
  }
}

function applyCompanionCall(detail) {
  const tx = document.getElementById("companion-transcript");
  const notes = document.getElementById("today-notes");
  if (tx) tx.innerHTML = renderTurns(detail && detail.turns);
  const lines = healthLines(detail && detail.health);
  if (notes && lines.length) notes.innerHTML = lines.map((l) => "<div>" + escapeHtml(l) + "</div>").join("");
}

function applyDetailSummary(s) {
  const checkin = document.getElementById("detail-checkin");
  const healthEl = document.getElementById("detail-health");
  const tx = document.getElementById("detail-transcript");
  const callsEl = document.getElementById("detail-calls");
  const histEl = document.getElementById("detail-health-hist");
  if (!checkin) return;
  if (!s) {
    checkin.textContent = "No call on the server for this number yet. After a live call, tap Refresh.";
    healthEl.innerHTML = "";
    tx.innerHTML = "";
    callsEl.innerHTML = "";
    if (histEl) histEl.innerHTML = "";
    return;
  }
  const h = (s.last_call && s.last_call.health) || s.latest_health;
  const lines = healthLines(h);
  if (s.alert && s.alert.reason && s.alert.level && s.alert.level !== "green") {
    checkin.textContent = (s.alert.level || "") + " — " + s.alert.reason;
  } else if (s.last_call) {
    checkin.textContent = "Last call " + fmtWhen(s.last_call.ended_at);
  } else {
    checkin.textContent = "No check-in yet.";
  }
  healthEl.innerHTML = lines.map((l) => '<div class="check-row"><span>' + escapeHtml(l) + "</span></div>").join("");
  tx.innerHTML = renderTurns(s.last_call && s.last_call.turns);
  callsEl.innerHTML = renderCallChips(s.calls, true);
  const person = personById(selectedId);
  bindCallChips(callsEl, person && person.phone, applyPastCallToDetail);
  if (histEl) {
    const hist = [];
    if (s.latest_health) hist.push(s.latest_health);
    (s.calls || []).forEach((c) => {
      if (c.has_health && c.session_id !== (s.last_call && s.last_call.session_id)) {
        hist.push({ recorded_at: c.ended_at, notes: c.preview, session_id: c.session_id });
      }
    });
    histEl.innerHTML = hist.length
      ? hist.slice(0, 6).map((row) => {
          const bits = healthLines(row);
          return '<div class="health-hist-row"><b>' + fmtWhen(row.recorded_at) + "</b> " +
            escapeHtml(bits.join(" · ") || row.notes || "Check-in saved") + "</div>";
        }).join("")
      : '<p class="muted-note">No health history yet.</p>';
  }
}

function applyPastCallToDetail(detail) {
  const tx = document.getElementById("detail-transcript");
  const healthEl = document.getElementById("detail-health");
  const checkin = document.getElementById("detail-checkin");
  if (tx) tx.innerHTML = renderTurns(detail && detail.turns);
  const lines = healthLines(detail && detail.health);
  if (healthEl) {
    healthEl.innerHTML = lines.map((l) => '<div class="check-row"><span>' + escapeHtml(l) + "</span></div>").join("");
  }
  if (checkin && detail) checkin.textContent = "Call " + fmtWhen(detail.ended_at);
}

function bindCallChips(el, phone, applyFn) {
  if (!el || !phone) return;
  el.querySelectorAll("[data-session]").forEach((chip) => {
    chip.addEventListener("click", async () => {
      try {
        const detail = await fetchCallDetail(phone, chip.dataset.session);
        if (detail) applyFn(detail);
      } catch (e) {
        showToast(e.message || "Could not load that call");
      }
    });
  });
}

function stopCallPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function updateInviteSection(p) {
  const block = document.getElementById("invite-block");
  const hint = document.getElementById("invite-hint");
  const callsOnly = document.getElementById("calls-only-note");
  const voiceOnly = !!(p && p.hasPhone === false);
  if (block) block.style.display = voiceOnly ? "none" : "";
  if (callsOnly) {
    callsOnly.style.display = voiceOnly ? "block" : "none";
    if (voiceOnly) {
      callsOnly.textContent =
        "Calls only — they answer the phone. No app or invite needed. Schedule and Call Saathi now work from your phone.";
    }
  }
  if (!hint || voiceOnly) return;
  if (p.inviteAccepted) {
    hint.textContent = "They already joined the app with this invite.";
  } else if (p.inviteUrl || p.inviteCode) {
    hint.textContent = "Share the invite so they can install/open the app as User. Code: " +
      (p.inviteCode || "—");
  } else {
    hint.textContent = "Invite link will appear after the server syncs this person.";
  }
}

function loadProfile() {
  try { return JSON.parse(localStorage.getItem("saathi_profile") || "null"); }
  catch { return null; }
}
function saveProfile(p) {
  localStorage.setItem("saathi_profile", JSON.stringify(p));
}
function loadPeople() {
  try { return JSON.parse(localStorage.getItem("saathi_people") || "[]"); }
  catch { return []; }
}
function savePeople(list) {
  localStorage.setItem("saathi_people", JSON.stringify(list));
}
function personById(id) {
  return loadPeople().find((p) => String(p.id) === String(id));
}

function todayLabel() {
  return new Date().toLocaleDateString("en-IN", {
    weekday: "long", day: "numeric", month: "short",
  });
}

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => t.classList.remove("show"), 2800);
}

function showScreen(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  document.getElementById(id).classList.add("active");
}

function setFamilyTab(tab) {
  document.querySelectorAll(".bottomnav .nav-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
}

async function goHome(profile) {
  const p = profile || loadProfile();
  if (!p) { showScreen("screen-setup"); return; }
  if (p.role === "companion") {
    const me = loadPeople()[0];
    document.getElementById("date-companion").textContent = todayLabel();
    document.getElementById("greet-companion").textContent = "Namaste, " + (p.name || (me && me.name) || "ji");
    document.getElementById("lang-row").innerHTML =
      "<span>Call language</span><b>" + (LANG_LABEL[p.language] || p.language || "—") + "</b>";
    const fam = p.familyName || (me && me.familyName);
    document.getElementById("family-av").textContent = fam ? fam.charAt(0).toUpperCase() : "—";
    document.getElementById("family-who").textContent = fam || "Family is not linked yet";
    const med = document.getElementById("med-time-label");
    if (med) med.textContent = (p.medTime || "18:00") + " — after dinner";
    showScreen("screen-companion");
    const s = await loadSummary(p.phone);
    applyCompanionSummary(s);
    return;
  }
  document.getElementById("date-family").textContent = todayLabel();
  document.getElementById("greet-family").textContent = "Namaste, " + (p.name || "there");
  await syncPeopleFromServer();
  renderPeople();
  setFamilyTab("home");
  showScreen("screen-family");
  await enrichPeople();
}

function mergeRemotePerson(remote) {
  const list = loadPeople();
  const phone = remote.phone;
  const existing = list.find((p) => p.phone === phone);
  const extras = {
    timezone: remote.timezone || "Asia/Kolkata",
    daysOfWeek: remote.days_of_week || "1,2,3,4,5,6,7",
    scheduleEnabled: remote.schedule_enabled !== false && remote.schedule_enabled !== 0,
    city: remote.city || "—",
    hasPhone: !!remote.has_smartphone,
    inviteCode: remote.invite_code || existing && existing.inviteCode,
    inviteUrl: remote.invite_url || existing && existing.inviteUrl,
    inviteAccepted: !!remote.invite_accepted,
  };
  if (existing) {
    existing.name = remote.name || existing.name;
    existing.language = remote.language || existing.language;
    existing.callTime = remote.call_time || existing.callTime;
    Object.assign(existing, extras);
    savePeople(list);
    return;
  }
  list.push({
    id: remote.id || Date.now(),
    name: remote.name,
    relation: "Family",
    phone: remote.phone,
    language: remote.language || "hi-IN",
    callTime: remote.call_time || "09:00",
    color: COLORS[list.length % COLORS.length],
    ...extras,
  });
  savePeople(list);
}

async function syncPeopleFromServer() {
  const p = loadProfile();
  if (!p || p.role === "companion" || !p.phone) return;
  for (const person of loadPeople()) {
    try {
      await addPersonRemote({
        subscriber_phone: p.phone,
        subscriber_name: p.name,
        name: person.name,
        phone: person.phone,
        language: person.language,
        call_time: person.callTime,
        city: person.city,
        has_smartphone: person.hasPhone,
        days_of_week: person.daysOfWeek || "1,2,3,4,5,6,7",
        timezone: person.timezone || "Asia/Kolkata",
      });
    } catch (e) { /* keep going */ }
  }
  try {
    const remote = await fetchPeople(p.phone);
    remote.forEach(mergeRemotePerson);
  } catch (e) {
    /* API not deployed yet — keep local list */
  }
}

function lastCallLabel(person) {
  const s = summaryCache[person.phone];
  if (!s) return person.phone + " · " + (LANG_LABEL[person.language] || person.language);
  if (s.alert && s.alert.level && s.alert.level !== "green") {
    return (s.alert.level || "") + " — " + (s.alert.reason || "Needs a look");
  }
  if (s.last_call) return "Last call " + fmtWhen(s.last_call.ended_at);
  return person.phone + " · no calls yet";
}

function alertDot(person) {
  const s = summaryCache[person.phone];
  const level = (s && s.alert && s.alert.level) || "green";
  return level;
}

function renderHomeAlerts() {
  const el = document.getElementById("home-alerts");
  if (!el) return;
  const hits = loadPeople().map((p) => {
    const s = summaryCache[p.phone];
    if (!s || !s.alert || !s.alert.level || s.alert.level === "green") return null;
    return { name: p.name, level: s.alert.level, reason: s.alert.reason };
  }).filter(Boolean);
  if (!hits.length) {
    el.innerHTML = "";
    return;
  }
  const worst = hits.find((h) => h.level === "emergency" || h.level === "red") || hits[0];
  const cls = (worst.level === "yellow" || worst.level === "orange") ? "alert-banner warn" : "alert-banner";
  el.innerHTML = '<div class="' + cls + '"><b>' + escapeHtml(worst.name) + "</b> · " +
    escapeHtml(worst.level) + " — " + escapeHtml(worst.reason || "") +
    ' <a href="tel:108" style="color:inherit;font-weight:700;">Dial 108</a></div>';
}

function renderPeople() {
  const list = loadPeople();
  document.getElementById("people-label").textContent = "Your people · " + list.length;
  const el = document.getElementById("people-list");
  if (!list.length) {
    el.innerHTML = '<div class="empty-people">No one added yet. Tap Add a person — use a real name and number.</div>';
    renderHomeAlerts();
    return;
  }
  el.innerHTML = list.map((p) => `
    <div class="parent-card" data-open="${p.id}">
      <div class="avatar" style="background:${p.color || COLORS[0]}">${(p.name || "?").charAt(0).toUpperCase()}</div>
      <div class="card-body">
        <div class="name">${escapeHtml(p.name)}</div>
        <div class="rel">${escapeHtml(p.relation || "")} · ${escapeHtml(p.city || "—")}${p.hasPhone === false ? " · calls only" : ""}</div>
        <div class="checkin"><span class="status-dot ${alertDot(p)}"></span>${escapeHtml(lastCallLabel(p))}</div>
      </div>
      <svg class="chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M9 6l6 6-6 6"/></svg>
    </div>`).join("");
  el.querySelectorAll("[data-open]").forEach((card) => {
    card.addEventListener("click", () => openDetail(card.dataset.open));
  });
  renderHomeAlerts();
}

async function enrichPeople() {
  const list = loadPeople();
  await Promise.all(list.map((p) => loadSummary(p.phone)));
  renderPeople();
}

async function openDetail(id) {
  const p = personById(id);
  if (!p) return;
  selectedId = id;
  document.getElementById("detail-name").textContent = p.name;
  document.getElementById("detail-rel").textContent = (p.relation || "") + (p.city ? " · " + p.city : "");
  document.getElementById("detail-phone").textContent = p.phone;
  document.getElementById("detail-lang").textContent = LANG_LABEL[p.language] || p.language;
  document.getElementById("detail-time").textContent = p.callTime || "09:00";
  document.getElementById("status-detail").textContent = "";
  document.getElementById("status-detail").className = "status";
  updateInviteSection(p);
  applyDetailSummary(summaryCache[p.phone] || null);
  showScreen("screen-detail");
  const s = await loadSummary(p.phone);
  applyDetailSummary(s);
}

function renderSchedule() {
  const list = loadPeople();
  const el = document.getElementById("schedule-list");
  if (!list.length) {
    el.innerHTML = '<div class="empty-people">No schedule yet. Add people on Home first.</div>';
    return;
  }
  const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  el.innerHTML = list.map((p) => {
    const days = (p.daysOfWeek || "1,2,3,4,5,6,7").split(",");
    const chips = dayNames.map((label, i) => {
      const d = String(i + 1);
      return '<button type="button" class="day-chip' + (days.indexOf(d) >= 0 ? " on" : "") +
        '" data-day="' + d + '" data-id="' + p.id + '">' + label + "</button>";
    }).join("");
    const on = p.scheduleEnabled !== false;
    return `
    <div class="sched-card" data-sched="${p.id}">
      <div class="sched-top">
        <div class="avatar" style="width:38px;height:38px;font-size:14px;background:${p.color || COLORS[0]}">${(p.name || "?").charAt(0).toUpperCase()}</div>
        <div class="name">${escapeHtml(p.name)}</div>
      </div>
      <div class="sched-row"><span class="k">Daily call</span>
        <label class="sched-toggle"><input type="checkbox" data-enabled-id="${p.id}" ${on ? "checked" : ""}/> ${on ? "On" : "Paused"}</label>
      </div>
      <div class="sched-row"><span class="k">Call time</span>
        <input type="time" data-time-id="${p.id}" value="${p.callTime || "09:00"}" />
      </div>
      <div class="sched-row" style="flex-direction:column;align-items:stretch;gap:8px;">
        <span class="k">Days</span>
        <div class="day-chips">${chips}</div>
      </div>
      <div class="sched-row"><span class="k">Timezone</span>
        <select data-tz-id="${p.id}">
          <option value="Asia/Kolkata"${(p.timezone || "Asia/Kolkata") === "Asia/Kolkata" ? " selected" : ""}>India (IST)</option>
          <option value="Europe/Paris"${p.timezone === "Europe/Paris" ? " selected" : ""}>France</option>
          <option value="America/New_York"${p.timezone === "America/New_York" ? " selected" : ""}>US Eastern</option>
        </select>
      </div>
      <div class="sched-row"><span class="k">Language</span><span class="v">${LANG_LABEL[p.language] || p.language}</span></div>
      <button class="btn-secondary" type="button" data-skip-id="${p.id}" style="width:100%;margin-top:8px;">Skip today</button>
    </div>`;
  }).join("");

  async function persist(person, extra) {
    const listNow = loadPeople();
    const idx = listNow.findIndex((x) => String(x.id) === String(person.id));
    if (idx >= 0) {
      Object.assign(listNow[idx], extra || {}, person);
      savePeople(listNow);
    }
    try {
      await updateUserRemote({
        phone: person.phone,
        call_time: person.callTime,
        schedule_enabled: person.scheduleEnabled !== false,
        days_of_week: person.daysOfWeek || "1,2,3,4,5,6,7",
        timezone: person.timezone || "Asia/Kolkata",
        skip_on: person.skipOn || undefined,
      });
      showToast("Schedule saved for " + person.name);
    } catch (e) {
      showToast("Saved on this phone. Server: " + (e.message || "offline"));
    }
    renderSchedule();
  }

  el.querySelectorAll("[data-time-id]").forEach((inp) => {
    inp.addEventListener("change", async () => {
      const person = loadPeople().find((x) => String(x.id) === String(inp.dataset.timeId));
      if (!person) return;
      person.callTime = inp.value;
      await persist(person);
    });
  });
  el.querySelectorAll("[data-enabled-id]").forEach((inp) => {
    inp.addEventListener("change", async () => {
      const person = loadPeople().find((x) => String(x.id) === String(inp.dataset.enabledId));
      if (!person) return;
      person.scheduleEnabled = inp.checked;
      await persist(person);
    });
  });
  el.querySelectorAll("[data-tz-id]").forEach((inp) => {
    inp.addEventListener("change", async () => {
      const person = loadPeople().find((x) => String(x.id) === String(inp.dataset.tzId));
      if (!person) return;
      person.timezone = inp.value;
      await persist(person);
    });
  });
  el.querySelectorAll(".day-chip").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const person = loadPeople().find((x) => String(x.id) === String(btn.dataset.id));
      if (!person) return;
      let days = (person.daysOfWeek || "1,2,3,4,5,6,7").split(",").filter(Boolean);
      const d = btn.dataset.day;
      if (days.indexOf(d) >= 0) days = days.filter((x) => x !== d);
      else days.push(d);
      if (!days.length) days = [d];
      person.daysOfWeek = days.sort().join(",");
      await persist(person);
    });
  });
  el.querySelectorAll("[data-skip-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const person = loadPeople().find((x) => String(x.id) === String(btn.dataset.skipId));
      if (!person) return;
      person.skipOn = new Date().toISOString().slice(0, 10);
      await persist(person, { skipOn: person.skipOn });
    });
  });
}

function fillProfile() {
  const p = loadProfile() || {};
  document.getElementById("profile-name").textContent = p.name || "Account";
  document.getElementById("profile-av").textContent = (p.name || "A").charAt(0).toUpperCase();
  document.getElementById("s-role").value = p.role || "family";
  document.getElementById("cfg-api").value = apiBase() || (window.SAATHI_DEFAULTS && window.SAATHI_DEFAULTS.apiBase) || "";
  const sub = document.getElementById("profile-sub");
  if (sub) sub.textContent = p.phone || "Your account";
  const people = loadPeople();
  const billP = document.getElementById("bill-people");
  if (billP) billP.textContent = String(people.length) + " · ₹" + (people.length * 499) + "/mo";
  const backup = document.getElementById("s-backup");
  if (backup) backup.value = p.backupPhone || "";
  const st = document.getElementById("bill-status");
  if (st) st.textContent = p.planStatus || "none";
  fetchMe().then((me) => {
    if (!me || !me.user) return;
    const status = (me.user.plan_status || "none");
    if (st) st.textContent = status;
    p.planStatus = status;
    saveProfile(p);
  }).catch(() => {});
}

async function dialPerson(person, statusEl) {
  if (!person || !person.phone) {
    statusEl.textContent = "This person has no phone number.";
    statusEl.className = "status bad";
    return;
  }
  stopCallPoll();
  statusEl.textContent = "Dialing…";
  statusEl.className = "status";
  try {
    const data = await startOutboundCall({
      name: person.name,
      phone: person.phone,
      language: person.language || "hi-IN",
    });
    const who = (data.user && data.user.name) || person.name;
    if (data.provider === "local" && data.local_call_url) {
      statusEl.textContent = "Local dummy call ready. On this PC open: " + data.local_call_url +
        " — type as the elder, End call, then Refresh last call here.";
      statusEl.className = "status ok";
      showToast("Local call — open the PC link");
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(data.local_call_url);
          showToast("Local call URL copied");
        }
      } catch (e) { /* ignore */ }
      return;
    }
    statusEl.textContent = "Ringing " + who + " at " + data.to +
      ". When the call ends, tap Refresh last call for transcript and health notes.";
    statusEl.className = "status ok";
    showToast("Calling " + who + "…");
  } catch (err) {
    statusEl.textContent = err.message || "Network error — is Render up?";
    statusEl.className = "status bad";
  }
}

function makePersonFromForm() {
  const name = document.getElementById("a-name").value.trim();
  const phone = document.getElementById("a-phone").value.trim();
  if (!name || !phone) {
    showToast("Name and phone are required");
    return null;
  }
  const list = loadPeople();
  return {
    id: Date.now(),
    name,
    relation: document.getElementById("a-rel").value,
    phone,
    city: document.getElementById("a-city").value.trim() || "—",
    language: document.getElementById("a-lang").value,
    callTime: document.getElementById("a-time").value || "09:00",
    hasPhone: document.getElementById("a-phone-app") ? document.getElementById("a-phone-app").value === "yes" : true,
    color: COLORS[list.length % COLORS.length],
  };
}

async function openHistoryScreen() {
  const p = personById(selectedId);
  if (!p) return;
  document.getElementById("history-parent-name").textContent = p.name;
  const el = document.getElementById("history-content");
  el.innerHTML = '<p class="muted-note">Loading…</p>';
  showScreen("screen-history");
  try {
    const weeks = await fetchUserHistory(p.phone);
    if (!weeks.length) {
      el.innerHTML = '<p class="muted-note">No check-in weeks yet. This fills after real calls.</p>';
      return;
    }
    el.innerHTML = weeks.map((w, idx) => {
      const food = w.days.filter((d) => d.food).length;
      const sleep = w.days.filter((d) => d.sleep).length;
      const bp = w.days.filter((d) => d.bp).length;
      const flags = w.days.filter((d) => d.flag).length;
      const cells = w.days.map((d) => {
        const dt = new Date(d.date + "T12:00:00");
        const wd = dt.toLocaleDateString("en-IN", { weekday: "narrow" });
        return '<div class="day-cell' + (d.flag ? " flagd" : "") + '"><span class="dc-wd">' + wd +
          '</span><span class="dc-dots">' +
          '<i class="dot' + (d.food ? " on" : "") + '"></i>' +
          '<i class="dot' + (d.sleep ? " on" : "") + '"></i>' +
          '<i class="dot' + (d.medicines ? " on" : "") + '"></i>' +
          '<i class="dot' + (d.bp ? " on" : "") + '"></i></span></div>';
      }).join("");
      return '<div class="week-row"><div class="week-top" data-week="' + idx + '"><span>' +
        w.start + " – " + w.end + "</span><span>" + food + "/7 food · " + sleep + "/7 sleep · " +
        bp + "/7 BP" + (flags ? " · " + flags + " flagged" : "") +
        '</span></div><div class="week-days" id="week-' + idx + '">' + cells + "</div></div>";
    }).join("");
    el.querySelectorAll("[data-week]").forEach((row) => {
      row.addEventListener("click", () => {
        document.getElementById("week-" + row.dataset.week).classList.toggle("open");
      });
    });
  } catch (e) {
    el.innerHTML = '<p class="muted-note">' + escapeHtml(e.message || "Could not load history") + "</p>";
  }
}

async function openRecordingsScreen() {
  const p = personById(selectedId);
  if (!p) return;
  document.getElementById("recordings-parent-name").textContent = p.name;
  const el = document.getElementById("recordings-content");
  const s = summaryCache[p.phone] || await loadSummary(p.phone);
  const calls = (s && s.calls) || [];
  const esc = calls.filter((c) => c.alert_level && c.alert_level !== "green").length;
  el.innerHTML = '<div class="stat-mini-grid">' +
    '<div class="stat-mini"><div class="num">' + calls.length + '</div><div class="lbl">Total</div></div>' +
    '<div class="stat-mini"><div class="num">' + calls.filter((c) => c.user_turns).length + '</div><div class="lbl">With speech</div></div>' +
    '<div class="stat-mini"><div class="num">' + esc + '</div><div class="lbl">Escalated</div></div>' +
    '<div class="stat-mini"><div class="num">' + calls.filter((c) => c.has_health).length + '</div><div class="lbl">Health</div></div></div>' +
    (calls.length ? calls.map((c) =>
      '<div class="call-chip" data-session="' + escapeHtml(c.session_id) + '">' +
      '<div class="when">' + fmtWhen(c.ended_at) + " · " + (c.user_turns || 0) + " replies</div>" +
      escapeHtml(c.preview || "No user speech") + "</div>"
    ).join("") : '<p class="muted-note">No recordings yet. After a live call, hang up and refresh.</p>');
  bindCallChips(el, p.phone, (detail) => openCallSheet(p, detail));
  showScreen("screen-recordings");
}

async function openCallSheet(person, detail) {
  const sheet = document.getElementById("callModalSheet");
  const modal = document.getElementById("callModal");
  if (!sheet || !modal) return;
  const audioSrc = await callAudioBlobUrl(person.phone, detail.session_id);
  const turns = renderTurns(detail.turns);
  const lines = healthLines(detail.health);
  sheet.innerHTML =
    '<div class="modal-handle"></div><div class="modal-title">' + escapeHtml(person.name) + "</div>" +
    '<p class="muted-note">' + fmtWhen(detail.ended_at) + "</p>" +
    (audioSrc
      ? '<audio controls style="width:100%;margin:10px 0;" src="' + audioSrc + '"></audio>'
      : '<p class="muted-note">No WAV on this server yet (local recordings/ folder).</p>') +
    lines.map((l) => '<div class="check-row"><span>' + escapeHtml(l) + "</span></div>").join("") +
    '<div class="section-label">Transcript</div><div class="transcript">' + turns + "</div>" +
    '<button class="btn-secondary" type="button" id="close-call-modal" style="width:100%;margin-top:10px;">Close</button>';
  modal.classList.add("show");
  const close = document.getElementById("close-call-modal");
  if (close) close.onclick = () => modal.classList.remove("show");
}

function bind() {
  document.querySelectorAll(".role-pills button").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".role-pills button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      const family = b.dataset.role === "family";
      document.getElementById("role-hint").textContent = family
        ? "You will see a home of people you care for. Add Mum/Dad after this."
        : "For elders with a smartphone only. If they only have a voice phone, your family adds them — you do not register here.";
      document.getElementById("f-name").placeholder = family ? "Aditi Sharma" : "Kamla Sharma";
    });
  });

  document.getElementById("setup-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const role = document.querySelector(".role-pills button.on").dataset.role;
    const name = document.getElementById("f-name").value.trim();
    const phone = document.getElementById("f-phone").value.trim();
    const language = document.getElementById("f-lang").value;
    const status = document.getElementById("setup-status");
    if (!name || !phone) {
      status.textContent = "Your name and phone are required to register.";
      status.className = "status bad";
      return;
    }
    const consent = document.getElementById("f-consent-calls").checked &&
      document.getElementById("f-consent-rec").checked &&
      document.getElementById("f-consent-health").checked;
    if (!consent) {
      status.textContent = "Please accept the three consent boxes to continue.";
      status.className = "status bad";
      return;
    }
    saveProfile({ role, name, phone, language });
    try {
      const otpRes = await requestOtp(phone);
      const otp = (document.getElementById("f-otp") && document.getElementById("f-otp").value.trim()) || otpRes.dev_otp || "";
      if (otpRes.dev_otp && !document.getElementById("f-otp").value.trim()) {
        document.getElementById("f-otp").value = otpRes.dev_otp;
        showToast("Test code: " + otpRes.dev_otp);
      }
      if (!otp) {
        status.textContent = otpRes.message || "Enter the login code, then tap Register again.";
        status.className = "status";
        return;
      }
      await verifyOtp({ phone, otp, role, name });
    } catch (err) {
      status.textContent = "Login code: " + (err.message || "offline");
      status.className = "status bad";
      return;
    }
    const pendingInvite = localStorage.getItem("saathi_invite") || "";
    if (pendingInvite) {
      try {
        const joined = await acceptInviteRemote({
          invite_code: pendingInvite,
          phone,
          name,
          language,
          consent_calls: true,
          consent_recording: true,
          consent_health: true,
        });
        localStorage.removeItem("saathi_invite");
        const u = joined.user || {};
        saveProfile({
          role: "companion",
          name: u.name || name,
          phone: u.phone || phone,
          language: u.language || language,
        });
        savePeople([{
          id: u.id || Date.now(),
          name: u.name || name,
          relation: "Self",
          phone: u.phone || phone,
          city: u.city || "—",
          language: u.language || language,
          callTime: u.call_time || "09:00",
          color: COLORS[0],
          inviteAccepted: true,
        }]);
        showToast("Joined — you are linked to your family");
        goHome(loadProfile());
        return;
      } catch (err) {
        status.textContent = "Invite: " + (err.message || "could not join") +
          " — use the same phone number your family added.";
        status.className = "status bad";
        return;
      }
    }
    if (role === "companion") {
      savePeople([{
        id: Date.now(),
        name,
        relation: "Self",
        phone,
        city: "—",
        language,
        callTime: "09:00",
        color: COLORS[0],
      }]);
    } else if (!loadPeople().length) {
      savePeople([]);
    }
    try {
      await registerAccount({ role, name, phone, language, consent: true });
    } catch (err) {
      status.textContent = "Saved on this phone. Server register: " + (err.message || "offline");
      status.className = "status";
    }
    goHome(loadProfile());
  });

  document.getElementById("btn-call-companion").addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    await dialPerson(loadPeople()[0], document.getElementById("status-companion"));
    e.currentTarget.disabled = false;
  });
  document.getElementById("btn-sos").addEventListener("click", () => {
    document.getElementById("sosModal").classList.add("show");
  });
  document.getElementById("sos-cancel").addEventListener("click", () => {
    document.getElementById("sosModal").classList.remove("show");
  });
  document.getElementById("sos-yes").addEventListener("click", async () => {
    document.getElementById("sosModal").classList.remove("show");
    const me = loadPeople()[0] || loadProfile();
    const statusEl = document.getElementById("status-companion");
    try {
      const data = await sendSos({
        name: me && me.name,
        phone: me && me.phone,
        language: (me && me.language) || "hi-IN",
      });
      if (data.family_dialed) {
        statusEl.textContent = "SOS sent — calling family at " + (data.family_contact || "") + ".";
        statusEl.className = "status ok";
        showToast("Calling family now");
      } else {
        statusEl.textContent = "SOS saved. Add a family phone on Profile so we can ring them.";
        statusEl.className = "status";
        showToast("SOS saved — no family number to dial");
      }
    } catch (err) {
      showToast(err.message || "SOS not saved on server");
    }
  });
  document.getElementById("open-settings").addEventListener("click", () => {
    fillProfile();
    showScreen("screen-profile");
    setFamilyTab("profile");
  });

  document.getElementById("btn-add-person").addEventListener("click", () => {
    document.getElementById("addModal").classList.add("show");
    const sel = document.getElementById("a-phone-app");
    const hint = document.getElementById("add-phone-hint");
    if (sel && hint) hint.style.display = sel.value === "no" ? "block" : "none";
  });
  const phoneAppSel = document.getElementById("a-phone-app");
  if (phoneAppSel) {
    phoneAppSel.addEventListener("change", () => {
      const hint = document.getElementById("add-phone-hint");
      if (hint) hint.style.display = phoneAppSel.value === "no" ? "block" : "none";
    });
  }
  document.getElementById("add-cancel").addEventListener("click", () => {
    document.getElementById("addModal").classList.remove("show");
  });
  document.getElementById("add-save").addEventListener("click", async () => {
    const person = makePersonFromForm();
    if (!person) return;
    const list = loadPeople();
    list.push(person);
    savePeople(list);
    document.getElementById("addModal").classList.remove("show");
    ["a-name", "a-phone", "a-city"].forEach((id) => { document.getElementById(id).value = ""; });
    const sub = loadProfile() || {};
    try {
      await addPersonRemote({
        subscriber_phone: sub.phone,
        subscriber_name: sub.name,
        name: person.name,
        phone: person.phone,
        language: person.language,
        call_time: person.callTime,
        city: person.city,
        has_smartphone: person.hasPhone,
        days_of_week: person.daysOfWeek || "1,2,3,4,5,6,7",
        timezone: person.timezone || "Asia/Kolkata",
      });
      showToast(person.hasPhone
        ? person.name + " added — share invite if they have a smartphone"
        : person.name + " added — calls only, no app needed");
      await syncPeopleFromServer();
      renderPeople();
      renderSchedule();
      return;
    } catch (err) {
      showToast(person.name + " saved on this phone. Server: " + (err.message || "offline"));
    }
    renderPeople();
    renderSchedule();
  });

  document.getElementById("back-detail").addEventListener("click", () => goHome());
  document.getElementById("btn-call-detail").addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    await dialPerson(personById(selectedId), document.getElementById("status-detail"));
    e.currentTarget.disabled = false;
  });
  const shareBtn = document.getElementById("btn-share-invite");
  if (shareBtn) shareBtn.addEventListener("click", async () => {
    const person = personById(selectedId);
    if (!person) return;
    let url = person.inviteUrl;
    if (!url && person.inviteCode) {
      const base = apiBase() || (window.SAATHI_DEFAULTS && window.SAATHI_DEFAULTS.apiBase) || location.origin;
      url = String(base).replace(/\/$/, "") + "/?invite=" + person.inviteCode;
    }
    if (!url) {
      showToast("No invite yet — refresh people from Home first");
      return;
    }
    const text = "Join Saathi Care for " + person.name + ". Open this link on your phone: " + url;
    try {
      if (navigator.share) {
        await navigator.share({ title: "Saathi Care invite", text, url });
      } else if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(url);
        showToast("Invite link copied");
      } else {
        window.prompt("Copy invite link", url);
      }
    } catch (e) {
      if (e && e.name === "AbortError") return;
      try {
        await navigator.clipboard.writeText(url);
        showToast("Invite link copied");
      } catch (err) {
        window.prompt("Copy invite link", url);
      }
    }
  });
  const refreshInviteBtn = document.getElementById("btn-refresh-invite");
  if (refreshInviteBtn) refreshInviteBtn.addEventListener("click", async () => {
    const person = personById(selectedId);
    if (!person || !person.phone) return;
    try {
      const remote = await refreshInviteRemote(person.phone);
      mergeRemotePerson(remote);
      showToast("New invite link ready — share it again");
      openDetail(selectedId);
    } catch (e) {
      showToast(e.message || "Could not refresh invite");
    }
  });

  document.getElementById("btn-refresh-detail").addEventListener("click", async () => {
    const person = personById(selectedId);
    if (!person) return;
    showToast("Loading last call…");
    const s = await loadSummary(person.phone);
    applyDetailSummary(s);
    if (!s) showToast("No call found for this number yet — wait after hang-up, then try again.");
  });
  document.getElementById("btn-refresh-home").addEventListener("click", async () => {
    showToast("Refreshing…");
    await syncPeopleFromServer();
    await enrichPeople();
  });
  const histBtn = document.getElementById("btn-open-history");
  if (histBtn) histBtn.addEventListener("click", () => openHistoryScreen());
  const recBtn = document.getElementById("btn-open-recordings");
  if (recBtn) recBtn.addEventListener("click", () => openRecordingsScreen());
  const backH = document.getElementById("back-history");
  if (backH) backH.addEventListener("click", () => openDetail(selectedId));
  const backR = document.getElementById("back-recordings");
  if (backR) backR.addEventListener("click", () => openDetail(selectedId));
  const callModal = document.getElementById("callModal");
  if (callModal) callModal.addEventListener("click", (e) => {
    if (e.target === callModal) callModal.classList.remove("show");
  });
  document.getElementById("btn-refresh-companion").addEventListener("click", async () => {
    const p = loadProfile();
    showToast("Loading last call…");
    const s = await loadSummary(p && p.phone);
    applyCompanionSummary(s);
    if (!s) showToast("No call found for your number yet.");
  });

  document.querySelectorAll(".bottomnav .nav-item").forEach((b) => {
    b.addEventListener("click", () => {
      const tab = b.dataset.tab;
      setFamilyTab(tab);
      if (tab === "home") goHome();
      else if (tab === "schedule") { renderSchedule(); showScreen("screen-schedule"); }
      else if (tab === "profile") { fillProfile(); showScreen("screen-profile"); }
    });
  });

  document.getElementById("save-settings").addEventListener("click", async () => {
    const p = loadProfile() || {};
    p.role = document.getElementById("s-role").value;
    const backup = document.getElementById("s-backup");
    if (backup) p.backupPhone = backup.value.trim();
    saveProfile(p);
    localStorage.setItem("saathi_api", document.getElementById("cfg-api").value.trim());
    const me = loadPeople()[0];
    if (p.role === "companion" && me) {
      try {
        await updateUserRemote({
          phone: me.phone,
          name: p.name,
          language: p.language || me.language,
        });
      } catch (e) { /* ignore */ }
    }
    showToast("Settings saved");
    goHome(p);
  });
  document.getElementById("btn-reset").addEventListener("click", () => {
    localStorage.removeItem("saathi_profile");
    localStorage.removeItem("saathi_people");
    localStorage.removeItem("saathi_token");
    showScreen("screen-setup");
  });
  const testPlan = document.getElementById("btn-test-plan");
  if (testPlan) testPlan.addEventListener("click", async () => {
    try {
      const data = await activateTestPlan();
      const p = loadProfile() || {};
      p.planStatus = data.plan_status || "test";
      saveProfile(p);
      fillProfile();
      showToast("Test plan on — nothing charged");
    } catch (e) {
      showToast(e.message || "Could not activate test plan");
    }
  });
  const cancelPlanBtn = document.getElementById("btn-cancel-plan");
  if (cancelPlanBtn) cancelPlanBtn.addEventListener("click", async () => {
    try {
      await cancelPlan();
      const p = loadProfile() || {};
      p.planStatus = "cancelled";
      saveProfile(p);
      fillProfile();
      showToast("Test plan cancelled");
    } catch (e) {
      showToast(e.message || "Could not cancel");
    }
  });
  const delBtn = document.getElementById("btn-delete-account");
  if (delBtn) delBtn.addEventListener("click", async () => {
    if (!window.confirm("Delete this account on the server and clear this phone?")) return;
    try {
      await deleteAccountRemote();
    } catch (e) {
      showToast(e.message || "Server delete failed — clearing this phone anyway");
    }
    localStorage.removeItem("saathi_profile");
    localStorage.removeItem("saathi_people");
    localStorage.removeItem("saathi_token");
    showScreen("screen-setup");
  });
}

async function applyPendingInvite() {
  const params = new URLSearchParams(location.search || "");
  let code = (params.get("invite") || "").trim().toUpperCase();
  if (!code && location.hash) {
    const m = location.hash.match(/invite=([A-Za-z0-9]+)/i);
    if (m) code = m[1].toUpperCase();
  }
  if (!code) code = (localStorage.getItem("saathi_invite") || "").trim().toUpperCase();
  if (!code) return null;
  localStorage.setItem("saathi_invite", code);
  try {
    const inv = await fetchInvite(code);
    if (!inv) {
      showToast("Invite not found — ask family for a new link");
      localStorage.removeItem("saathi_invite");
      return null;
    }
    const banner = document.getElementById("invite-banner");
    if (banner) {
      banner.style.display = "block";
      banner.textContent = "Invite from " + (inv.family_name || "Family") +
        " for " + (inv.name || "you") + ". Use phone " + (inv.phone || "") + " to join as User.";
    }
    const companionBtn = document.querySelector('.role-pills button[data-role="companion"]');
    const familyBtn = document.querySelector('.role-pills button[data-role="family"]');
    if (companionBtn && familyBtn) {
      familyBtn.classList.remove("on");
      companionBtn.classList.add("on");
      companionBtn.click();
    }
    if (inv.name) document.getElementById("f-name").value = inv.name;
    if (inv.phone) document.getElementById("f-phone").value = inv.phone;
    if (inv.language) document.getElementById("f-lang").value = inv.language;
    return inv;
  } catch (e) {
    showToast(e.message || "Could not load invite");
    return null;
  }
}

async function boot() {
  bind();
  try {
    const mode = await fetchAuthMode();
    const hint = document.getElementById("otp-hint");
    if (hint && mode.test_otp_allowed) {
      hint.textContent = "Development: the server may fill a test code. Production will SMS when SMS_OTP is on.";
    } else if (hint) {
      hint.textContent = "Enter the 6-digit code sent to this phone.";
    }
  } catch (e) { /* ignore */ }
  const invite = await applyPendingInvite();
  const p = loadProfile();
  if (p && p.personName && p.phone && !loadPeople().length) {
    savePeople([{
      id: Date.now(),
      name: p.personName,
      relation: p.relation || "Mother",
      phone: p.phone,
      city: "—",
      language: p.language || "hi-IN",
      callTime: "09:00",
      color: COLORS[0],
    }]);
  }
  if (invite) {
    showScreen("screen-setup");
    return;
  }
  if (p && (p.name || p.familyName || p.personName)) goHome(p);
  else showScreen("screen-setup");
}

boot();
