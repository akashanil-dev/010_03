// TallyTime accounts, workspaces, the live queue and notifications. Loaded before app.js.

let me = null;              // the signed-in person (GET /api/me)
let publicConfig = {};      // limits and keys the sign-in page needs
let queueState = { jobs: [], waiting: 0, busy: false };
let events = null;          // EventSource for live queue updates
let pushActive = false;     // this browser receives Web Push notifications
const lastJobState = new Map();
const ACTIVE = ["queued", "running"];

/* ---------- API ---------- */
class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, opts); } catch { throw new ApiError(0, "Could not reach TallyTime. Check your connection and try again."); }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  const detail = data?.detail || "Something went wrong. Please try again.";
  if (res.status === 401 && !path.startsWith("/api/auth/")) { signedOut(); throw new ApiError(401, detail); }
  if (res.status === 403 && /Confirm your email|accept the updated/.test(detail)) { await refreshMe(); route(); }
  if (!res.ok) throw new ApiError(res.status, detail);
  return data;
}

function toast(message, { action, onAction, kind = "" } = {}) {
  const t = $("#toast");
  t.className = `toast ${kind}`;
  t.innerHTML = `<span>${esc(message)}</span>${action ? `<button class="btn small" id="toast-action">${esc(action)}</button>` : ""}<button class="toast-x" aria-label="Dismiss">×</button>`;
  t.hidden = false;
  if (action) $("#toast-action").onclick = () => { t.hidden = true; onAction(); };
  t.querySelector(".toast-x").onclick = () => { t.hidden = true; };
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, action ? 15000 : 6000);
}

const fmtDur = (s) => {
  s = Math.max(0, Math.round(s || 0));
  if (s < 50) return "under a minute";
  const m = Math.round(s / 60);
  if (m < 60) return `about ${m} min`;
  return `about ${Math.floor(m / 60)} h ${m % 60} min`;
};
const fmtDate = (ts) => new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/* ---------- session ---------- */
async function refreshMe() {
  try {
    const res = await fetch("/api/me");
    me = res.ok ? await res.json() : null;
  } catch { me = null; }
  if (me) renderAccountBar();
  return me;
}

function signedOut() {
  me = null;
  if (events) { events.close(); events = null; }
  renderAuth("login");
}

let pendingInvite = null;
function rememberInvite(token) {
  pendingInvite = token;
  try { sessionStorage.setItem("tallytime-invite", token); } catch { /* private mode */ }
}
function forgetInvite() {
  pendingInvite = null;
  try { sessionStorage.removeItem("tallytime-invite"); } catch { /* private mode */ }
}

async function boot() {
  syncThemeColor();
  try { publicConfig = await (await fetch("/api/public-config")).json(); } catch { publicConfig = {}; }
  $("#auth-quota").textContent = publicConfig.daily_shipments ?? 5;
  $("#auth-retention").textContent = publicConfig.retention_days ?? 7;
  try { pendingInvite = sessionStorage.getItem("tallytime-invite"); } catch { /* private mode */ }

  const [key, value] = location.hash.slice(1).split("=");
  const clearHash = () => history.replaceState(null, "", location.pathname);
  if (key === "verify" && value) {
    clearHash();
    try { await api("/api/auth/verify", { method: "POST", body: { token: value } }); toast("Email confirmed. Welcome to TallyTime!"); }
    catch (e) { await refreshMe(); return me ? route() : renderAuth("login", { error: e.message }); }
  }
  if (key === "reset" && value) { clearHash(); return renderAuth("reset", { token: value }); }
  if (key === "invite" && value) { clearHash(); rememberInvite(value); }

  await refreshMe();
  if (!me) {
    const mode = key === "forgot" ? "forgot" : key === "signup" || pendingInvite ? "signup" : "login";
    if (["login", "signup", "forgot"].includes(key)) clearHash();
    return renderAuth(mode);
  }
  route();
}

function route() {
  if (!me) return renderAuth("login");
  if (!me.verified) return renderAuth("verify-wait");
  if (me.needs_terms) return renderAuth("terms");
  if (pendingInvite) return renderInvite();
  enterApp();
}

/* ---------- sign in, sign up and friends ---------- */
let turnstileWidget = null;

function loadTurnstile() {
  if (!publicConfig.turnstile_site_key) return Promise.resolve(false);
  if (window.turnstile) return Promise.resolve(true);
  return new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    s.async = true;
    s.onload = () => resolve(true);
    s.onerror = () => resolve(false);
    document.head.appendChild(s);
  });
}

async function mountTurnstile() {
  turnstileWidget = null;
  const box = $("#turnstile");
  if (!box || !(await loadTurnstile())) return;
  turnstileWidget = window.turnstile.render(box, { sitekey: publicConfig.turnstile_site_key });
}

const turnstileToken = () => (turnstileWidget !== null && window.turnstile ? window.turnstile.getResponse(turnstileWidget) : null);

function authShell(title, inner, footer = "") {
  return `<h2>${esc(title)}</h2><div id="auth-error" class="form-error" role="alert" hidden></div>${inner}${footer ? `<div class="auth-links">${footer}</div>` : ""}`;
}

function authError(message) {
  const box = $("#auth-error");
  box.textContent = message;
  box.hidden = !message;
}

async function submitting(form, work) {
  const btn = form.querySelector("button[type=submit]");
  btn.disabled = true;
  authError("");
  try { await work(); } catch (e) { authError(e.message); if (turnstileWidget !== null) window.turnstile?.reset(turnstileWidget); } finally { btn.disabled = false; }
}

function renderAuth(mode, opts = {}) {
  show("auth");
  const card = $("#auth-card");
  const links = {
    login: `<a href="#" data-mode="signup">Create an account</a> · <a href="#" data-mode="forgot">Forgot password?</a>`,
    signup: `Already have an account? <a href="#" data-mode="login">Log in</a>`,
    forgot: `<a href="#" data-mode="login">Back to log in</a>`,
  };
  if (mode === "login") {
    card.innerHTML = authShell("Log in", `
      <form id="auth-form" class="form">
        <label>Email<input type="email" name="email" autocomplete="email" required></label>
        <label>Password<input type="password" name="password" autocomplete="current-password" required></label>
        <button class="btn primary" type="submit">Log in</button>
      </form>`, links.login);
    $("#auth-form").onsubmit = (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      submitting(e.target, async () => {
        await api("/api/auth/login", { method: "POST", body: { email: f.get("email"), password: f.get("password") } });
        await refreshMe();
        route();
      });
    };
  } else if (mode === "signup") {
    card.innerHTML = authShell("Create your free account", `
      <form id="auth-form" class="form">
        <label>Your name<input name="name" autocomplete="name" maxlength="60" required></label>
        <label>Work email<input type="email" name="email" autocomplete="email" required></label>
        <label>Password <span class="muted small">(at least 10 characters)</span><input type="password" name="password" autocomplete="new-password" minlength="10" required></label>
        <label class="check"><input type="checkbox" name="accept" required> I agree to the <a href="/terms.html" target="_blank">Terms of Use</a> and the <a href="/privacy.html" target="_blank">Privacy Policy</a>.</label>
        <div id="turnstile"></div>
        <button class="btn primary" type="submit">Create account</button>
      </form>`, links.signup);
    mountTurnstile();
    $("#auth-form").onsubmit = (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      submitting(e.target, async () => {
        const r = await api("/api/auth/signup", { method: "POST", body: {
          name: f.get("name"), email: f.get("email"), password: f.get("password"),
          accept_terms: f.get("accept") === "on", turnstile: turnstileToken() } });
        card.innerHTML = authShell("Check your email", `<p>${esc(r.message)}</p>
          <p class="muted">No email after a few minutes? Check your spam folder, or log in to send it again.</p>`, links.signup);
        wireAuthLinks();
      });
    };
  } else if (mode === "forgot") {
    card.innerHTML = authShell("Reset your password", `
      <form id="auth-form" class="form">
        <label>Email<input type="email" name="email" autocomplete="email" required></label>
        <div id="turnstile"></div>
        <button class="btn primary" type="submit">Send reset link</button>
      </form>`, links.forgot);
    mountTurnstile();
    $("#auth-form").onsubmit = (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      submitting(e.target, async () => {
        const r = await api("/api/auth/forgot", { method: "POST", body: { email: f.get("email"), turnstile: turnstileToken() } });
        card.innerHTML = authShell("Check your email", `<p>${esc(r.message)}</p>`, links.forgot);
        wireAuthLinks();
      });
    };
  } else if (mode === "reset") {
    card.innerHTML = authShell("Choose a new password", `
      <form id="auth-form" class="form">
        <label>New password <span class="muted small">(at least 10 characters)</span><input type="password" name="password" autocomplete="new-password" minlength="10" required></label>
        <button class="btn primary" type="submit">Save password and log in</button>
      </form>`, links.forgot);
    $("#auth-form").onsubmit = (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      submitting(e.target, async () => {
        await api("/api/auth/reset", { method: "POST", body: { token: opts.token, password: f.get("password") } });
        toast("Password changed. You are logged in.");
        await refreshMe();
        route();
      });
    };
  } else if (mode === "verify-wait") {
    card.innerHTML = authShell("Confirm your email", `
      <p>We sent a confirmation link to <b>${esc(me.email)}</b>. Open it to start checking documents.</p>
      <div class="row-actions"><button class="btn" id="resend">Send the link again</button>
        <button class="btn ghost" id="auth-logout">Log out</button></div>`);
    $("#resend").onclick = async () => {
      try { await api("/api/auth/resend-verification", { method: "POST" }); toast("Sent. Check your inbox and spam folder."); }
      catch (e) { authError(e.message); }
    };
    $("#auth-logout").onclick = logout;
  } else if (mode === "terms") {
    card.innerHTML = authShell("We updated our terms", `
      <p>Please read the updated <a href="/terms.html" target="_blank">Terms of Use</a> and
        <a href="/privacy.html" target="_blank">Privacy Policy</a> to keep using TallyTime.</p>
      <div class="row-actions"><button class="btn primary" id="accept-terms">I agree</button>
        <button class="btn ghost" id="auth-logout">Log out</button></div>`);
    $("#accept-terms").onclick = async () => { await api("/api/me/accept-terms", { method: "POST" }); await refreshMe(); route(); };
    $("#auth-logout").onclick = logout;
  }
  if (opts.error) authError(opts.error);
  wireAuthLinks();
  card.querySelector("input")?.focus();
}

function wireAuthLinks() {
  $$("[data-mode]").forEach((a) => a.onclick = (e) => { e.preventDefault(); renderAuth(a.dataset.mode); });
}

async function renderInvite() {
  show("auth");
  const card = $("#auth-card");
  let inv;
  try { inv = await api("/api/workspaces/invite-details", { method: "POST", body: { token: pendingInvite } }); }
  catch (e) { forgetInvite(); toast(e.message, { kind: "error" }); return enterApp(); }
  card.innerHTML = authShell("Join a shared workspace", `
    <p><b>${esc(inv.invited_by || "Someone")}</b> invited <b>${esc(inv.email)}</b> to <b>${esc(inv.workspace)}</b>.</p>
    <p class="muted">Members of a workspace see and review all of its shipments together.</p>
    <div class="row-actions"><button class="btn primary" id="join">Join workspace</button><button class="btn ghost" id="decline">Not now</button></div>`);
  $("#join").onclick = async () => {
    try { await api("/api/workspaces/join", { method: "POST", body: { token: pendingInvite } }); forgetInvite(); await refreshMe(); toast(`You joined ${inv.workspace}.`); enterApp(); }
    catch (e) { authError(e.message); }
  };
  $("#decline").onclick = () => { forgetInvite(); enterApp(); };
}

async function logout() {
  await fetch("/api/auth/logout", { method: "POST" });
  signedOut();
}

/* ---------- top bar ---------- */
function renderAccountBar() {
  const sel = $("#ws-switch");
  sel.innerHTML = me.workspaces.map((w) => `<option value="${esc(w.id)}" ${w.id === me.workspace.id ? "selected" : ""}>${esc(w.name)}${w.members > 1 ? ` · ${w.members} people` : ""}</option>`).join("");
  sel.hidden = me.workspaces.length < 2;
  sel.onchange = async () => {
    await api("/api/workspaces/switch", { method: "POST", body: { workspace_id: sel.value } });
    await refreshMe();
    goHome();
  };
  renderQuota();
}

function renderQuota() {
  const note = $("#quota-note");
  if (!me || !note) return;
  const q = me.quota;
  note.textContent = q.left
    ? `${q.left} of ${q.limit} checks left today`
    : `No checks left today. Resets at ${fmtTime(q.resets_at)}. Demos still work.`;
  note.classList.toggle("empty", !q.left);
  $("#btn-check").title = q.left ? "" : "Today's checks are used up";
}

function enterApp() {
  $("#mainnav").hidden = false;
  $("#account-bar").hidden = false;
  api("/api/system").then(renderSystem).catch(() => {});   // first reading at once, then live updates
  startEvents();
  ensurePush();
  openFromHash();
}

/* ---------- server resources (top bar) ---------- */
function setMeter(id, percent, tip) {
  const m = $(id);
  const pct = Math.max(0, Math.min(100, percent ?? 0));
  m.querySelector(".meter-fill").style.width = `${pct}%`;
  m.classList.toggle("warn", pct >= 70 && pct < 90);
  m.classList.toggle("high", pct >= 90);
  m.dataset.tip = tip;
  m.setAttribute("aria-label", tip.replace(/\n/g, ". "));
}

function renderSystem(s) {
  if (!s) return;
  $("#sysmon").hidden = false;
  const c = s.cpu, r = s.ram, g = s.gpu;
  const otherCpu = Math.max(0, c.percent - c.tallytime - c.model).toFixed(0);
  const otherRam = Math.max(0, r.used_gb - r.tallytime_gb - r.model_gb).toFixed(1);
  setMeter("#meter-cpu", c.percent,
    `CPU ${c.percent.toFixed(0)}% of ${c.cores} cores\nTallyTime ${c.tallytime.toFixed(0)}% · AI model ${c.model.toFixed(0)}% · other ${otherCpu}%`);
  setMeter("#meter-ram", r.percent,
    `RAM ${r.used_gb} of ${r.total_gb} GB (${r.percent.toFixed(0)}%)\nTallyTime ${r.tallytime_gb} GB · AI model ${r.model_gb} GB · other ${otherRam} GB`);
  $("#meter-gpu").classList.toggle("off", !g);
  if (g) setMeter("#meter-gpu", g.percent, `${g.name}\nGPU ${g.percent.toFixed(0)}% · memory ${g.used_gb} of ${g.total_gb} GB`);
  else setMeter("#meter-gpu", 0, "No GPU on this server\nDocuments are read on the CPU");
}

/* ---------- live queue ---------- */
function startEvents() {
  if (events || !window.EventSource) return;
  events = new EventSource("/api/events");
  events.onmessage = (e) => onQueue(JSON.parse(e.data));
  events.addEventListener("system", (e) => renderSystem(JSON.parse(e.data)));
  events.onerror = () => { /* the browser reconnects by itself */ };
}

function onQueue(state) {
  const first = lastJobState.size === 0;
  for (const j of state.jobs) {
    const before = lastJobState.get(j.shipment_id);
    if (!first && before && ACTIVE.includes(before) && !ACTIVE.includes(j.state)) jobFinished(j);
    lastJobState.set(j.shipment_id, j.state);
  }
  queueState = state;
  renderQueue();
}

const JOB_TEXT = {
  done: "Finished", timed_out: "Stopped: took too long", cancelled: "Cancelled", failed: "Failed",
};

function jobTitle(j) {
  return j.label || `Shipment started at ${fmtTime(j.queued_at)}`;
}

function jobFinished(j) {
  if (j.state === "cancelled" && !j.reason.startsWith("Cancelled automatically")) return;   // they did it themselves
  const msg = j.state === "done" ? `Check finished: ${jobTitle(j)}` : `${JOB_TEXT[j.state] || "Check ended"}: ${jobTitle(j)}`;
  flashTitle(j.state === "done" ? "✓ Check ready" : "Check ended");
  if (current?.id !== j.shipment_id) toast(msg, { action: "Open", onAction: () => track(j.shipment_id) });
  if (document.hidden && !pushActive && window.Notification?.permission === "granted") {
    const n = new Notification("TallyTime", { body: msg, tag: j.shipment_id, icon: "/favicon.svg" });
    n.onclick = () => { window.focus(); track(j.shipment_id); n.close(); };
  }
  if (j.state !== "done") refreshMe();   // a refunded check shows up in the quota
}

function flashTitle(text) {
  const base = "TallyTime · Export Document Verification";
  if (!document.hidden) return;
  let on = true;
  clearInterval(flashTitle.timer);
  flashTitle.timer = setInterval(() => { document.title = on ? text : base; on = !on; }, 1200);
  document.addEventListener("visibilitychange", () => { clearInterval(flashTitle.timer); document.title = base; }, { once: true });
}

function renderQueue() {
  const active = queueState.jobs.filter((j) => ACTIVE.includes(j.state));
  // The top-bar chip exists only while something is running or waiting
  const chip = $("#nav-queue");
  chip.hidden = !active.length;
  $("#queue-count").textContent = `${active.length} in progress`;
  chip.title = `${active.length} ${active.length === 1 ? "check is" : "checks are"} running or waiting. Show the queue.`;
  const section = $("#queue");
  section.hidden = !queueState.jobs.length;
  if (!queueState.jobs.length) return;
  $("#queue-body").innerHTML = `
    <p class="muted small">${queueState.busy ? `The reader is busy · ${queueState.waiting} ${queueState.waiting === 1 ? "check" : "checks"} waiting in total` : "The reader is free"}</p>
    <ul class="queue-list">${queueState.jobs.map((j) => {
      let status = "", bar = "";
      if (j.state === "queued") status = `Waiting · ${j.ahead} ${j.ahead === 1 ? "check" : "checks"} ahead · starts in ${fmtDur(j.starts_in)}`;
      else if (j.state === "running") { status = j.cancelling ? "Stopping…" : `Reading · ${j.percent}% · ${fmtDur(j.eta)} left`; bar = progressBar(j.percent); }
      else status = `${JOB_TEXT[j.state] || j.state} at ${fmtTime(j.finished_at)}${j.reason ? ` · ${j.reason}` : ""}`;
      return `<li class="queue-item ${j.state}">
        <div class="q-main"><b>${esc(jobTitle(j))}</b><span class="muted small">${j.by ? `by ${esc(j.by)} · ` : ""}${esc(status)}</span>${bar}</div>
        <div class="q-actions">
          ${["done", "timed_out"].includes(j.state) || ACTIVE.includes(j.state) ? `<button class="btn small" data-q-open="${esc(j.shipment_id)}">Open</button>` : ""}
          ${ACTIVE.includes(j.state) && !j.cancelling ? `<button class="btn small danger" data-q-cancel="${esc(j.shipment_id)}">Cancel</button>` : ""}
        </div></li>`;
    }).join("")}</ul>`;
  $$("[data-q-open]").forEach((b) => b.onclick = () => track(b.dataset.qOpen));
  $$("[data-q-cancel]").forEach((b) => b.onclick = () => cancelCheck(b.dataset.qCancel));
}

function progressBar(pct) {
  return `<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div style="width:${pct}%"></div></div>`;
}

async function cancelCheck(id) {
  if (!confirm("Cancel this check? If it is already running, the documents read so far are kept but no report is made.")) return;
  try { const r = await api(`/api/shipments/${id}/cancel`, { method: "POST" }); toast(r.state === "cancelled" ? "Cancelled. Today's check was given back." : "Stopping…"); await refreshMe(); }
  catch (e) { toast(e.message, { kind: "error" }); }
}

/* ---------- notifications ---------- */
function b64ToBytes(b64) {
  const s = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}

async function subscribePush() {
  if (!me?.vapid_public_key || !("serviceWorker" in navigator) || !("PushManager" in window)) return false;
  const reg = await navigator.serviceWorker.register("/sw.js");
  let sub = await reg.pushManager.getSubscription();
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(me.vapid_public_key) });
  await api("/api/me/push", { method: "POST", body: sub.toJSON() });
  pushActive = true;
  return true;
}

async function ensurePush() {
  if (window.Notification?.permission === "granted") { try { await subscribePush(); } catch { pushActive = false; } }
}

/* Asked once, when someone starts their first check (not on page load). */
async function offerNotifications() {
  if (!window.Notification || Notification.permission !== "default" || load("tallytime-notify-asked", false)) return;
  save("tallytime-notify-asked", true);
  toast("Get a notification when your check is finished?", { action: "Turn on", onAction: enableNotifications });
}

async function enableNotifications() {
  if (!window.Notification) { toast("This browser does not support notifications.", { kind: "error" }); return false; }
  const perm = await Notification.requestPermission();
  if (perm !== "granted") { toast("Notifications are blocked. You can allow them in your browser's site settings.", { kind: "error" }); return false; }
  try { await subscribePush(); } catch { /* in-page notifications still work while the tab is open */ }
  toast(pushActive ? "Notifications on. You will be told when each check finishes, even if this tab is closed." : "Notifications on while this tab is open.");
  if (!$("#view-account").hidden) renderAccount();
  return true;
}

async function disablePush() {
  const reg = await navigator.serviceWorker?.getRegistration("/sw.js");
  const sub = await reg?.pushManager.getSubscription();
  if (sub) { await api("/api/me/push/remove", { method: "POST", body: sub.toJSON() }); await sub.unsubscribe(); }
  pushActive = false;
}

/* ---------- appearance ---------- */
// The device's light or dark setting is followed by CSS; a choice made here overrides it for this browser.
function themeChoice() {
  try { return localStorage.getItem("tallytime-theme") || "system"; } catch { return "system"; }
}

function setTheme(choice) {
  try {
    if (choice === "system") localStorage.removeItem("tallytime-theme");
    else localStorage.setItem("tallytime-theme", choice);
  } catch { /* storage blocked: applies until the page is reloaded */ }
  if (choice === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", choice);
  syncThemeColor();
}

function syncThemeColor() {
  // The browser bar colour on phones: by device setting, or the chosen theme
  const chosen = document.documentElement.getAttribute("data-theme");
  $$('meta[name="theme-color"]').forEach((m) => {
    const dark = chosen ? chosen === "dark" : m.media.includes("dark");
    m.content = dark ? "#1b1e22" : "#ffffff";
  });
}

/* ---------- account page ---------- */
function openAccount() {
  history.replaceState(null, "", "#account");
  show("account");
  renderAccount();
}

function renderAccount() {
  const ws = me.workspace, owner = ws.role === "owner";
  const perm = window.Notification?.permission;
  $("#account-body").innerHTML = `
    <div class="card"><h3>Profile</h3>
      <form id="f-name" class="form inline"><label>Name<input name="name" maxlength="60" value="${esc(me.name)}" required></label><button class="btn" type="submit">Save</button></form>
      <p class="muted small">Email: <b>${esc(me.email)}</b></p>
      <p class="muted small">Today: ${me.quota.used} of ${me.quota.limit} checks used. Resets at ${fmtTime(me.quota.resets_at)} (India time). Demo shipments do not count.</p>
    </div>

    <div class="card"><h3>Notifications</h3>
      <p>Browser notifications: <b>${pushActive ? "on, even when TallyTime is closed" : perm === "granted" ? "on while a TallyTime tab is open" : perm === "denied" ? "blocked in this browser's settings" : "off"}</b></p>
      ${pushActive ? `<button class="btn small" id="push-off">Turn off on this device</button>` : perm !== "denied" ? `<button class="btn small" id="push-on">Turn on</button>` : ""}
      <label class="check"><input type="checkbox" id="notify-email" ${me.notify_email ? "checked" : ""}> Also email me when a check finishes</label>
    </div>

    <div class="card"><h3>Appearance</h3>
      <p class="muted small">TallyTime follows your device's light or dark setting. You can fix it for this browser instead.</p>
      <div class="segmented" role="radiogroup" aria-label="Theme">
        ${[["system", "Same as device"], ["light", "Light"], ["dark", "Dark"]].map(([v, label]) =>
          `<label><input type="radio" name="theme" value="${v}" ${themeChoice() === v ? "checked" : ""}> ${label}</label>`).join("")}
      </div>
    </div>

    <div class="card"><h3>Password and sessions</h3>
      <form id="f-password" class="form">
        <label>Current password<input type="password" name="current" autocomplete="current-password" required></label>
        <label>New password <span class="muted small">(at least 10 characters)</span><input type="password" name="new" autocomplete="new-password" minlength="10" required></label>
        <button class="btn" type="submit">Change password</button>
      </form>
      <div class="row-actions"><button class="btn small" id="logout">Log out</button><button class="btn small" id="logout-all">Log out on every device</button></div>
    </div>

    <div class="card wide"><h3>Workspace: ${esc(ws.name)}</h3>
      <p class="muted">Everyone in a workspace sees and reviews all of its shipments. ${owner ? "You own this workspace." : "You are a member of this workspace."}</p>
      ${owner ? `<form id="f-rename" class="form inline"><label>Workspace name<input name="name" maxlength="60" value="${esc(ws.name)}" required></label><button class="btn" type="submit">Rename</button></form>` : ""}
      <table class="recent members-table"><thead><tr><th>Member</th><th>Email</th><th>Role</th><th></th></tr></thead><tbody>
        ${ws.members.map((m) => `<tr><td>${esc(m.name)}${m.id === me.id ? " (you)" : ""}</td><td>${esc(m.email)}</td><td>${m.role === "owner" ? "Owner" : "Member"}</td>
          <td>${m.role !== "owner" && (owner || m.id === me.id) ? `<button class="btn small danger" data-remove-member="${esc(m.id)}">${m.id === me.id ? "Leave" : "Remove"}</button>` : ""}</td></tr>`).join("")}
        ${ws.invites.map((i) => `<tr><td class="muted">Invited</td><td>${esc(i.email)}</td><td class="muted">Expires ${fmtDate(i.expires)}</td>
          <td><button class="btn small" data-cancel-invite="${esc(i.email)}">Cancel</button></td></tr>`).join("")}
      </tbody></table>
      ${owner ? `<form id="f-invite" class="form inline"><label>Invite a colleague by email<input type="email" name="email" placeholder="colleague@company.com" required></label><button class="btn primary" type="submit">Send invitation</button></form>` : ""}
      ${me.workspaces.length > 1 ? `<p class="muted small">You can switch workspaces with the selector at the top of the page.</p>` : ""}
    </div>

    <div class="card wide danger-zone"><h3>Delete account</h3>
      <p class="muted">Deletes your account, your workspace and every shipment in it straight away. Workspaces you joined are not affected.</p>
      <form id="f-delete" class="form inline"><label>Password<input type="password" name="password" autocomplete="current-password" required></label><button class="btn danger" type="submit">Delete my account</button></form>
    </div>

    <p class="muted small wide"><a href="/about.html">About TallyTime</a> · <a href="/privacy.html">Privacy Policy</a> · <a href="/terms.html">Terms of Use</a></p>`;

  const run = async (work, ok) => { try { await work(); if (ok) toast(ok); await refreshMe(); renderAccount(); } catch (e) { toast(e.message, { kind: "error" }); } };
  const form = (id, fn) => { $(id).onsubmit = (e) => { e.preventDefault(); fn(new FormData(e.target)); }; };
  form("#f-name", (f) => run(() => api("/api/me", { method: "PATCH", body: { name: f.get("name") } }), "Name saved."));
  $("#notify-email").onchange = (e) => run(() => api("/api/me", { method: "PATCH", body: { notify_email: e.target.checked } }),
    e.target.checked ? "You will get an email when a check finishes." : "Emails turned off.");
  $("#push-on")?.addEventListener("click", enableNotifications);
  $$('input[name="theme"]').forEach((r) => r.onchange = () => setTheme(r.value));
  $("#push-off")?.addEventListener("click", () => run(disablePush, "Notifications turned off on this device."));
  if (owner) {
    form("#f-rename", (f) => run(() => api("/api/workspaces/rename", { method: "POST", body: { name: f.get("name") } }), "Workspace renamed."));
    form("#f-invite", (f) => run(() => api("/api/workspaces/invites", { method: "POST", body: { email: f.get("email") } }), `Invitation sent to ${f.get("email")}.`));
  }
  $$("[data-cancel-invite]").forEach((b) => b.onclick = () => run(() => api("/api/workspaces/invites/cancel", { method: "POST", body: { email: b.dataset.cancelInvite } }), "Invitation cancelled."));
  $$("[data-remove-member]").forEach((b) => b.onclick = () => {
    const self = b.dataset.removeMember === me.id;
    if (!confirm(self ? "Leave this workspace? You will no longer see its shipments." : "Remove this member? They will no longer see this workspace's shipments.")) return;
    run(() => api("/api/workspaces/remove-member", { method: "POST", body: { user_id: b.dataset.removeMember } }), self ? "You left the workspace." : "Member removed.");
  });
  form("#f-password", (f) => run(() => api("/api/me/password", { method: "POST", body: { current: f.get("current"), new: f.get("new") } }),
    "Password changed. Other devices were logged out."));
  $("#logout").onclick = logout;
  $("#logout-all").onclick = async () => { await api("/api/me/logout-everywhere", { method: "POST" }); signedOut(); };
  form("#f-delete", async (f) => {
    if (!confirm("Delete your account and all of your workspace's shipments now? This cannot be undone.")) return;
    try { await api("/api/me/delete", { method: "POST", body: { password: f.get("password") } }); signedOut(); toast("Your account and its data were deleted."); }
    catch (e) { toast(e.message, { kind: "error" }); }
  });
}
