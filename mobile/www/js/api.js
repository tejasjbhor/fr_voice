function apiBase() {
  const saved = localStorage.getItem("saathi_api");
  if (saved) return saved.replace(/\/$/, "");
  const defaults = (window.SAATHI_DEFAULTS && window.SAATHI_DEFAULTS.apiBase) || "";
  const proto = (typeof location !== "undefined" && location.protocol) || "";
  const host = (typeof location !== "undefined" && location.hostname) || "";
  // Capacitor Android uses androidScheme "https" → page is https://localhost,
  // not capacitor:. Empty base would call the phone, not Render.
  const native =
    (window.Capacitor && typeof window.Capacitor.isNativePlatform === "function"
      && window.Capacitor.isNativePlatform()) ||
    proto === "capacitor:" ||
    proto === "file:" ||
    proto === "ionic:" ||
    (proto === "https:" && (host === "localhost" || host === "127.0.0.1"));
  if (native) return String(defaults).replace(/\/$/, "");
  // Browser on Render (same origin) or npm start with proxy → relative URLs.
  return "";
}

function authHeaders(extra) {
  const token = localStorage.getItem("saathi_token") || "";
  const headers = extra ? Object.assign({}, extra) : {};
  if (token) headers.Authorization = "Bearer " + token;
  return headers;
}

async function apiJson(path, options) {
  const opts = options || {};
  opts.headers = authHeaders(opts.headers);
  const res = await fetch(apiBase() + path, opts);
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

async function startOutboundCall({ name, phone, language }) {
  const { res, data } = await apiJson("/call/outbound", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      to_number: phone,
      language,
    }),
  });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}

async function fetchUserSummary(phone) {
  const q = encodeURIComponent(phone || "");
  const { res, data } = await apiJson("/api/user/summary?phone=" + q);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}

async function fetchCallDetail(phone, sessionId) {
  const q = encodeURIComponent(phone || "");
  const { res, data } = await apiJson(
    "/api/user/calls/" + encodeURIComponent(sessionId) + "?phone=" + q
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data.call || data;
}

async function fetchUserHealth(phone, days) {
  const q = encodeURIComponent(phone || "");
  const { res, data } = await apiJson(
    "/api/user/health?phone=" + q + "&days=" + (days || 14)
  );
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data.health || [];
}

async function registerAccount({ role, name, phone, language, familyContact, consent }) {
  const { res, data } = await apiJson("/api/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      role,
      name,
      phone,
      language,
      family_contact: familyContact || "",
      consent_calls: !!consent,
      consent_recording: !!consent,
      consent_health: !!consent,
    }),
  });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}

async function fetchPeople(subscriberPhone) {
  const q = encodeURIComponent(subscriberPhone || "");
  const { res, data } = await apiJson("/api/people?subscriber_phone=" + q);
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data.people || [];
}

async function addPersonRemote(payload) {
  const { res, data } = await apiJson("/api/people", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data.user;
}

async function updateUserRemote(payload) {
  const { res, data } = await apiJson("/api/user/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data.user;
}

async function sendSos({ name, phone, language }) {
  const { res, data } = await apiJson("/api/user/sos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, phone, language }),
  });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}

async function requestOtp(phone) {
  const { res, data } = await apiJson("/api/auth/request-otp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone }),
  });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}

async function verifyOtp({ phone, otp, role, name }) {
  const { res, data } = await apiJson("/api/auth/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone, otp, role, name }),
  });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  if (data.token) localStorage.setItem("saathi_token", data.token);
  return data;
}

async function fetchUserHistory(phone) {
  const q = encodeURIComponent(phone || "");
  const { res, data } = await apiJson("/api/user/history?phone=" + q);
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data.weeks || [];
}

function callAudioUrl(phone, sessionId) {
  return apiBase() + "/api/user/calls/" + encodeURIComponent(sessionId) +
    "/audio?phone=" + encodeURIComponent(phone || "");
}

async function callAudioBlobUrl(phone, sessionId) {
  const res = await fetch(callAudioUrl(phone, sessionId), { headers: authHeaders() });
  if (!res.ok) return "";
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

async function fetchAuthMode() {
  const { res, data } = await apiJson("/api/auth/mode");
  return res.ok ? data : { test_otp_allowed: true };
}

async function activateTestPlan() {
  const { res, data } = await apiJson("/api/billing/test-activate", { method: "POST" });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}

async function cancelPlan() {
  const { res, data } = await apiJson("/api/billing/cancel", { method: "POST" });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}

async function deleteAccountRemote() {
  const { res, data } = await apiJson("/api/account/delete", { method: "POST" });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}

async function fetchMe() {
  const { res, data } = await apiJson("/api/me");
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}

async function fetchInvite(code) {
  const { res, data } = await apiJson("/api/invite/" + encodeURIComponent(code || ""));
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}

async function refreshInviteRemote(phone) {
  const { res, data } = await apiJson("/api/invite/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone }),
  });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data.user;
}

async function acceptInviteRemote(payload) {
  const { res, data } = await apiJson("/api/invite/accept", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  if (data.token) localStorage.setItem("saathi_token", data.token);
  return data;
}

async function fetchAdmin(path, pin) {
  const { res, data } = await apiJson(path, {
    headers: { "x-admin-pin": pin || localStorage.getItem("saathi_admin_pin") || "" },
  });
  if (!res.ok) throw new Error(data.error || "Failed (" + res.status + ")");
  return data;
}
