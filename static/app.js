// TallyTime front end: upload, progress, results. Plain JavaScript, no framework.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const DOC_SHORT = {
  purchase_order: "PO", commercial_invoice: "Invoice", packing_list: "Packing list",
  shipping_bill: "Shipping bill", health_certificate: "Quality / health cert.", certificate_of_origin: "Cert. of origin", letter_of_credit: "Letter of credit",
};
const STATUS_LABEL = { error: "ERROR", warning: "WARNING", pass: "PASS", skipped: "SKIPPED", info: "" };

const NUMERIC_ROWS = new Set(["cartons", "net_weight", "gross_weight", "fob_value", "hs_code"]);

const ACCEPTED = ["pdf", "png", "jpg", "jpeg", "tif", "tiff", "webp", "xlsx", "xls", "ods", "docx", "doc", "odt", "csv"];
let lang = "en";
let selected = [];
let current = null;   // latest shipment payload
let pollTimer = null;

/* ---------- views ---------- */
function show(view) {
  for (const v of ["upload", "processing", "results", "dashboard"]) $(`#view-${v}`).hidden = v !== view;
  $("#nav-new").classList.toggle("active", view === "upload");
  $("#nav-dashboard").classList.toggle("active", view === "dashboard");
  window.scrollTo(0, 0);
}

function goHome() {
  clearInterval(pollTimer);
  current = null;
  history.replaceState(null, "", location.pathname);
  show("upload");
}

/* ---------- upload ---------- */
function renderFileList() {
  $("#file-list").innerHTML = selected.map((f) => `<li><span>${esc(f.name)}</span><span>${(f.size / 1024).toFixed(0)} KB</span></li>`).join("");
  $("#btn-check").disabled = selected.length === 0;
  $("#btn-clear").hidden = selected.length === 0;
}

const MAX_FILE_MB = 10;
const MAX_FILES = 12;

function addFiles(files) {
  const problems = [];
  for (const f of files) {
    if (f.size > MAX_FILE_MB * 1024 * 1024) { problems.push(`${f.name} is ${(f.size / 1048576).toFixed(1)} MB; the limit is ${MAX_FILE_MB} MB per file.`); continue; }
    if (f.size === 0) { problems.push(`${f.name} is empty.`); continue; }
    if (selected.length >= MAX_FILES && !selected.some((s) => s.name === f.name)) { problems.push(`At most ${MAX_FILES} files per shipment; ${f.name} was not added.`); continue; }
    const ext = f.name.toLowerCase().split(".").pop();
    if (!ACCEPTED.includes(ext)) { problems.push(`${f.name}: unsupported file type. Use PDF, image, Excel, Word or CSV.`); continue; }
    if (!selected.some((s) => s.name === f.name)) selected.push(f);
  }
  if (problems.length) alert(problems.join("\n"));
  renderFileList();
}

async function submitUpload() {
  const form = new FormData();
  selected.forEach((f) => form.append("files", f));
  $("#btn-check").disabled = true;
  const res = await fetch("/api/shipments", { method: "POST", body: form });
  if (!res.ok) { alert((await res.json()).detail || "Upload failed"); $("#btn-check").disabled = false; return; }
  const { id } = await res.json();
  selected = [];
  renderFileList();
  track(id);
}

async function startDemo(name) {
  const res = await fetch(`/api/demo/${name}`, { method: "POST" });
  const { id } = await res.json();
  track(id);
}

/* ---------- polling ---------- */
function track(id, tab) {
  history.replaceState(null, "", `#${id}`);
  show("processing");
  clearInterval(pollTimer);
  const tick = async () => {
    const res = await fetch(`/api/shipments/${id}`);
    if (!res.ok) { clearInterval(pollTimer); alert("This shipment no longer exists."); goHome(); return; }
    current = await res.json();
    if (current.state === "interrupted") {
      clearInterval(pollTimer);
      alert("This check was interrupted by a server restart. Please upload the documents again.");
      goHome();
      return;
    }
    if (current.state === "done") {
      clearInterval(pollTimer);
      renderResults();
      show("results");
      if (tab) switchTab(tab);
    } else {
      renderProgress();
    }
  };
  tick();
  pollTimer = setInterval(tick, 1000);
}

function renderProgress() {
  $("#progress-list").innerHTML = current.files.map((f) => {
    let meta = "Waiting";
    if (f.state === "splitting") meta = "Checking whether this file holds several documents…";
    if (f.state === "reading") meta = `Reading… ${Math.round(f.elapsed || 0)} s`;
    if (f.state === "done") meta = `${esc(DOC_SHORT[f.doc_type] || "Unrecognised")}${f.source_format ? " · " + esc(f.source_format) : ""} · ${f.seconds < 1 ? "from cache" : f.seconds + " s"}`;
    if (f.state === "error") meta = `Could not read: ${esc(f.error)}`;
    const from = f.bundle ? `<br><span class="muted" style="font-size:12px">from ${esc(f.bundle)}, page ${f.pages.join("–")}</span>` : "";
    const icon = f.state === "splitting" ? "reading" : f.state;
    return `<li><span class="state-icon ${icon}"></span><span class="mono">${esc(f.filename)}${from}</span><span class="meta">${meta}</span></li>`;
  }).join("");
}

/* ---------- results ---------- */
function flags() {
  return current.report.checks.filter((c) => c.status === "error" || c.status === "warning");
}

function effectiveVerdict() {
  const reviews = current.reviews || {};
  const fl = flags();
  const openErrors = fl.filter((c) => c.status === "error" && reviews[c.id]?.decision !== "overridden");
  const openWarnings = fl.filter((c) => c.status === "warning" && !reviews[c.id]);
  const overridden = fl.filter((c) => reviews[c.id]?.decision === "overridden").length;
  const reviewed = fl.filter((c) => reviews[c.id]).length;
  let verdict = "ready";
  if (openErrors.length) verdict = "blocked";
  else if (openWarnings.length) verdict = "review";
  return { verdict, openErrors, openWarnings, overridden, reviewed, total: fl.length };
}

function renderResults() {
  renderVerdict();
  renderMatrix();
  renderIssues();
  renderFixes();
  renderReadiness();
  renderChecklist();
  renderDocuments();
  renderAudit();
}

function renderVerdict() {
  const r = current.report;
  const v = effectiveVerdict();
  const stampText = { blocked: "BLOCKED", review: "NEEDS REVIEW", ready: "READY TO FILE" }[v.verdict];
  let title, sub;
  if (v.verdict === "blocked") {
    title = `${v.openErrors.length} ${v.openErrors.length === 1 ? "error" : "errors"} to fix before filing`;
    sub = "Customs or the buyer's bank would likely query these documents.";
  } else if (v.verdict === "review") {
    title = `${v.openWarnings.length} ${v.openWarnings.length === 1 ? "warning needs" : "warnings need"} a decision`;
    sub = "No hard errors. A person should decide on the warnings.";
  } else {
    title = "All documents agree";
    sub = v.overridden ? `${v.overridden} flag(s) overridden by a reviewer. See the audit log.` : "Every check passed on these documents.";
  }
  $("#verdict").innerHTML = `
    <div class="stamp ${v.verdict}">${stampText}</div>
    <div>
      <h2>${esc(title)}</h2>
      <p class="sub">${esc(sub)}</p>
      <div class="stats">
        <div class="stat"><b>${r.counts.errors}</b><span>errors</span></div>
        <div class="stat"><b>${r.counts.warnings}</b><span>warnings</span></div>
        <div class="stat"><b>${r.counts.passed}/${r.counts.evaluated}</b><span>checks passed</span></div>
        <div class="stat"><b>${v.reviewed}/${v.total}</b><span>flags reviewed</span></div>
        <div class="stat"><b>${r.documents.length}</b><span>documents read</span></div>
      </div>
      <div class="coverage">${(r.coverage || []).map((c) => `<span class="cov ${c.present ? "ok" : c.required ? "missing" : "absent"}"
        title="${c.present ? "Uploaded" : c.required ? "Required: missing" : "Expected: not uploaded"}">${c.present ? "✓" : "✗"} ${esc(c.doc_name)}${c.present ? "" : c.required ? " · missing" : " · not uploaded"}</span>`).join("")}</div>
    </div>
    <div class="verdict-actions">
      <button class="btn small" id="btn-print">Print / save report</button>
      <button class="btn small" id="btn-new">New shipment</button>
      <button class="btn small danger" id="btn-delete">Delete uploaded files</button>
    </div>`;
  $("#btn-print").onclick = printReport;
  $("#btn-new").onclick = goHome;
  $("#btn-delete").onclick = deleteShipment;
  const open = v.openErrors.length + v.openWarnings.length;
  $("#issues-count").textContent = flags().length;
  $("#issues-count").className = "pill" + (open ? " red" : "");
  $("#audit-count").textContent = current.audit.length;
}

function renderMatrix() {
  const m = current.report.matrix;
  if (!m.rows.length) { $("#tab-matrix").innerHTML = `<div class="empty-state">No comparable fields were found.</div>`; return; }
  const head = m.columns.map((c) => `<th>${esc(c.doc_name)}<small>${esc(c.filename)}</small></th>`).join("");
  const rows = m.rows.map((row, ri) => {
    const cells = m.columns.map((c, ci) => {
      const cell = row.cells[c.doc_type];
      if (!cell) return `<td><span class="cell empty">—</span></td>`;
      const vague = cell.status === "mismatch" && row.status === "warning";   // warnings are "too vague", not wrong
      const cls = cell.status === "mismatch" ? (vague ? "vague" : "mismatch") : "";
      const shown = NUMERIC_ROWS.has(row.key) ? (cell.display ?? cell.raw) : cell.raw;
      const tag = cell.status === "mismatch" ? `<span class="tag">${vague ? "Too vague" : "Likely wrong"}</span>` : (!cell.verified ? `<span class="tag unverified">Not found in source</span>` : "");
      return `<td class="${cls ? "td-" + cls : ""}"><button class="cell ${cls}" data-r="${ri}" data-c="${ci}" title="${esc(cell.raw)}">${esc(shown)}${tag}</button></td>`;
    }).join("");
    const st = row.status;
    const label = { error: "Mismatch", warning: "Check wording", pass: "Agrees", skipped: "", info: "" }[st] || "";
    return `<tr><th class="field">${esc(row.label)}<span class="rowstatus ${st}">${label}</span></th>${cells}</tr>`;
  }).join("");
  $("#tab-matrix").innerHTML = `
    <div class="legend">
      <span><i style="background:var(--red-bg);box-shadow:inset 3px 0 0 var(--red)"></i>Likely wrong value</span>
      <span><i style="background:var(--amber-bg);box-shadow:inset 3px 0 0 var(--amber)"></i>Too vague (warning)</span>
      <span>Columns follow the document hierarchy: the purchase order is the source of truth.</span>
      <span>Click any value to see where it was read.</span>
    </div>
    <div class="matrix-wrap"><table class="matrix"><thead><tr><th class="field">Field</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
  $$("#tab-matrix .cell[data-r]").forEach((b) => b.onclick = () => openCell(+b.dataset.r, +b.dataset.c));
}

function highlight(snippet, raw) {
  const s = esc(snippet || "");
  if (!raw) return s;
  const r = esc(raw);
  const i = s.toLowerCase().indexOf(r.toLowerCase());
  return i < 0 ? s : s.slice(0, i) + "<mark>" + s.slice(i, i + r.length) + "</mark>" + s.slice(i + r.length);
}

function openCell(ri, ci) {
  const m = current.report.matrix;
  const row = m.rows[ri], col = m.columns[ci], cell = row.cells[col.doc_type];
  const check = current.report.checks.find((c) => c.id === row.check_id);
  $("#drawer-body").innerHTML = `
    <p class="eyebrow">${esc(row.label.toUpperCase())}</p>
    <h2>${esc(col.doc_name)}</h2>
    <dl class="kv">
      <dt>Value as printed</dt><dd>${esc(cell.raw)}</dd>
      <dt>Compared as</dt><dd>${esc(cell.display ?? "—")}</dd>
      <dt>Result</dt><dd>${cell.status === "mismatch" ? '<span class="warn-note" style="color:var(--red)">Disagrees with the reference value</span>' : "Consistent"}</dd>
    </dl>
    <h3>Where it was read</h3>
    ${cell.evidence ? `<div class="snippet">${highlight(cell.evidence, cell.raw)}</div>` : `<p class="muted">No matching text found.</p>`}
    <p style="margin-top:10px" class="${cell.verified ? "ok-note" : "warn-note"}">${cell.verified ? "Verified: this value appears in the document text." : "Not verified: the value was not found word for word in the document. Check it by hand."}</p>
    ${check && check.status !== "pass" ? `<h3 style="margin-top:20px">Issue</h3><p>${esc(check.message)}</p><button class="btn small" id="goto-issue">Review this issue</button>` : ""}
    <p style="margin-top:20px"><a class="btn small" target="_blank" href="/api/shipments/${current.id}/files/${encodeURIComponent(col.filename)}">Open ${esc(col.filename)}</a></p>`;
  const g = $("#goto-issue");
  if (g) g.onclick = () => { closeDrawer(); switchTab("issues"); document.getElementById(`issue-${check.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }); };
  $("#drawer").hidden = false;
}

function closeDrawer() { $("#drawer").hidden = true; }

function valuesTable(values) {
  if (!values?.length) return "";
  return `<table class="values"><thead><tr><th>Document</th><th>Value</th><th>Source text</th></tr></thead><tbody>${values.map((v) => `
    <tr class="${v.outlier ? "outlier" : ""}">
      <td>${esc(v.doc_name)}${v.outlier ? " <b>· likely outlier</b>" : ""}</td>
      <td class="v">${esc(v.display ?? v.raw ?? "—")}</td>
      <td class="evidence">${v.evidence ? highlight(v.evidence, v.raw) : "—"}${v.raw && !v.verified ? ' <span class="warn-note">(not found word for word)</span>' : ""}</td>
    </tr>`).join("")}</tbody></table>`;
}

function renderIssues() {
  const fl = flags();
  if (!fl.length) { $("#tab-issues").innerHTML = `<div class="empty-state"><b>No issues found.</b><br>Every cross-document, arithmetic and compliance check passed.</div>`; return; }
  const reviews = current.reviews || {};
  $("#tab-issues").innerHTML = `<div class="issues">${fl.map((c) => {
    const r = reviews[c.id];
    const review = r
      ? `<div class="review-box"><div class="review-done"><b class="${r.decision}">${r.decision === "confirmed" ? "Confirmed as a real problem" : "Overridden (accepted as is)"}</b> by ${esc(r.reviewer)} at ${esc(r.at.replace("T", " "))}${r.note ? ` · “${esc(r.note)}”` : ""}</div><button class="btn small ghost" data-change="${esc(c.id)}">Change</button></div>`
      : `<div class="review-box">
           <div class="review-head"><b>Your decision</b>
             <span class="muted">Confirm it as a real problem, or override it if it is acceptable. Both are saved to the audit log.</span></div>
           <label class="sr-only" for="note-${esc(c.id)}">Reason for your decision</label>
           <textarea maxlength="1000" placeholder="Why? (optional to confirm, required to override)" id="note-${esc(c.id)}"></textarea>
           <div class="review-actions">
             <button class="btn small primary" data-review="confirmed" data-id="${esc(c.id)}"
               title="This is a real problem. It stays open and keeps the shipment blocked until fixed.">Confirm issue</button>
             <button class="btn small" data-review="overridden" data-id="${esc(c.id)}"
               title="This is acceptable as it is. It stops counting against the verdict. A reason is required.">Override</button>
           </div>
         </div>`;
    return `<article class="issue ${c.status} ${r ? "reviewed" : ""}" id="issue-${esc(c.id)}">
      <div class="issue-head"><h3><span class="sev ${c.status}">${STATUS_LABEL[c.status]}</span>${esc(c.title)}</h3><span class="cat">${esc(c.category)}</span></div>
      ${lang === "ml" && mlMessage(c) ? `<p class="msg ml">${esc(mlMessage(c))}</p><p class="en-sub">${esc(c.message)}</p>` : `<p class="msg">${esc(c.message)}</p>`}
      ${c.suggestion ? `<p class="fix"><b>Suggested fix:</b> ${esc(c.suggestion)}</p>` : ""}
      ${c.owners?.length ? `<p class="cat">Goes to: ${esc(c.owners.join(", "))}</p>` : ""}
      ${valuesTable(c.values)}
      ${review}
    </article>`;
  }).join("")}</div>`;
  $$("[data-review]").forEach((b) => b.onclick = () => submitReview(b.dataset.id, b.dataset.review));
  $$("[data-change]").forEach((b) => b.onclick = () => { delete current.reviews[b.dataset.change]; renderIssues(); });
}

async function submitReview(checkId, decision) {
  const note = document.getElementById(`note-${checkId}`)?.value || "";
  if (decision === "overridden" && !note.trim()) { alert("Please write a note explaining why this flag is accepted."); return; }
  const res = await fetch(`/api/shipments/${current.id}/reviews`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ check_id: checkId, decision, note }),
  });
  if (!res.ok) { alert((await res.json()).detail || "Could not save the review"); return; }
  const fresh = await (await fetch(`/api/shipments/${current.id}`)).json();
  current = fresh;
  renderResults();
  switchTab("issues");
  document.getElementById(`issue-${checkId}`)?.scrollIntoView({ block: "center" });
}

function renderChecklist() {
  const groups = { "cross-document": "Across documents", arithmetic: "Within a document", compliance: "Compliance",
    "letter of credit": "Letter of credit (UCP 600)", "lab results": "Lab results" };
  $("#tab-checklist").innerHTML = Object.entries(groups).map(([cat, title]) => {
    const rows = current.report.checks.filter((c) => c.category === cat);
    return `<div class="check-group"><h3>${title}</h3>${rows.map((c) => `
      <div class="check-row"><span><span class="sev ${c.status}">${STATUS_LABEL[c.status]}</span></span>
        <div><div class="t">${esc(c.title)}</div><div class="m">${esc(c.message)}</div></div></div>`).join("")}</div>`;
  }).join("");
}

function renderDocuments() {
  $("#tab-documents").innerHTML = `<div class="docs">${current.report.documents.map((d) => `
    <div class="doc-card">
      <h3>${esc(d.doc_name)}</h3>
      <div class="mono muted" style="font-size:13px">${esc(d.filename)}</div>
      <div class="badges">
        <span class="badge ${d.ocr_used ? "warn" : ""}">${esc(d.source_format || (d.ocr_used ? "Scanned, OCR used" : "Digital PDF"))}</span>
        <span class="badge">${d.seconds ? `read in ${d.seconds} s` : "from cache"}</span>
        <span class="badge">${Object.values(d.fields).filter((f) => f.raw).length} fields extracted</span>
        ${d.unverified.length ? `<span class="badge warn">${d.unverified.length} not found word for word</span>` : `<span class="badge">all values verified in source</span>`}
      </div>
      ${d.unverified.length ? `<p class="warn-note" style="font-size:13px">Check by hand: ${esc(d.unverified.join(", "))}</p>` : ""}
      <details><summary>Extracted fields</summary>
        <table class="values"><thead><tr><th>Field</th><th>Value</th><th>Source</th></tr></thead><tbody>
        ${Object.values(d.fields).map((f) => `<tr><td>${esc(f.label)}</td><td class="v">${esc(f.raw ?? "—")}</td><td class="evidence">${f.raw ? (f.verified ? "✓ found" : "not found") : ""}</td></tr>`).join("")}
        </tbody></table>
      </details>
      <p style="margin-top:12px"><a class="btn small" target="_blank" href="/api/shipments/${current.id}/files/${encodeURIComponent(d.filename)}">Open original file</a></p>
    </div>`).join("")}</div>`;
}

function renderAudit() {
  const a = current.audit;
  $("#tab-audit").innerHTML = a.length
    ? `<ul class="audit">${a.map((e) => {
        const c = current.report.checks.find((x) => x.id === e.check_id);
        return `<li><span class="mono muted">${esc(e.at.replace("T", " "))}</span> · <b>${esc(e.reviewer)}</b> ${e.decision === "confirmed" ? "confirmed" : "overrode"} <b>${esc(c?.title || e.check_id)}</b>${e.note ? ` · “${esc(e.note)}”` : ""}</li>`;
      }).join("")}</ul>`
    : `<div class="empty-state">No review decisions yet. Every confirm or override is recorded here with its note and time.</div>`;
}

function switchTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.hidden = p.id !== `tab-${name}`);
}

async function deleteShipment() {
  if (!confirm("Delete the uploaded files for this shipment from this machine? This cannot be undone.")) return;
  await fetch(`/api/shipments/${current.id}`, { method: "DELETE" });
  alert("Uploaded files deleted.");
  goHome();
}

/* ---------- printable report ---------- */
function printReport() {
  const r = current.report, v = effectiveVerdict(), reviews = current.reviews || {};
  const stamp = { blocked: "BLOCKED", review: "NEEDS REVIEW", ready: "READY TO FILE" }[v.verdict];
  const issues = flags().map((c) => {
    const rv = reviews[c.id];
    return `<div class="i ${c.status}"><h3>${STATUS_LABEL[c.status]} · ${esc(c.title)}</h3><p>${esc(c.message)}</p>
      ${c.suggestion ? `<p><b>Suggested fix:</b> ${esc(c.suggestion)}</p>` : ""}
      ${(c.values || []).length ? `<table>${c.values.map((x) => `<tr${x.outlier ? ' class="o"' : ""}><td>${esc(x.doc_name)}</td><td>${esc(x.display ?? x.raw ?? "—")}</td></tr>`).join("")}</table>` : ""}
      <p class="rv">${rv ? `Review: ${rv.decision === "confirmed" ? "confirmed" : "overridden"} by ${esc(rv.reviewer)} at ${esc(rv.at.replace("T", " "))}${rv.note ? `, note: “${esc(rv.note)}”` : ""}` : "Review: pending"}</p></div>`;
  }).join("") || "<p>No issues found.</p>";
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>TallyTime review report</title><style>
    body{font:12px/1.45 "IBM Plex Sans",Arial,sans-serif;color:#0B1F33;margin:28px}
    h1{font-size:22px;margin:0} h2{font-size:15px;border-bottom:2px solid #0B1F33;padding-bottom:3px;margin-top:20px}
    h3{font-size:13px;margin:0 0 4px} .stamp{display:inline-block;border:3px solid #C41E33;color:#C41E33;font:700 16px monospace;letter-spacing:2px;padding:4px 10px;transform:rotate(-2deg);margin:8px 0}
    .stamp.ready{border-color:#1F7A50;color:#1F7A50} .stamp.review{border-color:#A8540A;color:#A8540A}
    .i{border-left:4px solid #C41E33;padding:6px 10px;margin:8px 0;page-break-inside:avoid} .i.warning{border-color:#A8540A}
    table{border-collapse:collapse;margin:4px 0} td{border:1px solid #ccc;padding:2px 6px;font-family:monospace} tr.o td{background:#FBE3E6;color:#C41E33}
    .rv{color:#555} .m{color:#555} li{margin:2px 0}</style></head><body>
    <h1>TallyTime · Export document review</h1>
    <p class="m">Generated ${new Date().toLocaleString()} · Shipment ${esc(current.id)}</p>
    <div class="stamp ${v.verdict}">${stamp}</div>
    <p>${r.counts.errors} errors · ${r.counts.warnings} warnings · ${r.counts.passed}/${r.counts.evaluated} checks passed · ${v.reviewed}/${v.total} flags reviewed</p>
    <h2>Documents</h2><ul>${r.documents.map((d) => `<li>${esc(d.doc_name)}: ${esc(d.filename)}${d.ocr_used ? " (scanned, OCR)" : ""}</li>`).join("")}</ul>
    <h2>Issues</h2>${issues}
    <h2>Checks passed</h2><ul>${r.checks.filter((c) => c.status === "pass").map((c) => `<li>${esc(c.title)}: ${esc(c.message)}</li>`).join("")}</ul>
    <p class="m" style="margin-top:20px">TallyTime is decision support, not legal or customs advice. A licensed customs broker makes the final call. Values were extracted by an AI model and checked by deterministic rules; each value's source text is shown in the app.</p>
    <script>window.onload=()=>window.print()<\/script></body></html>`;
  const w = window.open("", "_blank");
  w.document.write(html);
  w.document.close();
}

/* ---------- send fixes ---------- */
function openFlags() {
  const reviews = current.reviews || {};
  return flags().filter((c) => reviews[c.id]?.decision !== "overridden");
}

function fixText(owner, items) {
  const label = current.label || current.id;
  const lines = items.map((c, i) => {
    const text = lang === "ml" && mlMessage(c) ? mlMessage(c) : `${c.message}${c.suggestion ? " " + c.suggestion : ""}`;
    return `${i + 1}. ${c.status === "error" ? "[ERROR]" : "[WARNING]"} ${c.title}: ${text}`;
  });
  const head = lang === "ml" ? `${ML_UI.fixesFor} (${owner})\n${ML_UI.shipment}: ${label}` : `Document fixes needed (${owner})\nShipment: ${label}`;
  const foot = lang === "ml" ? ML_UI.footer : "Found by TallyTime before filing. Please correct and send the updated document.";
  return `${head}\n\n${lines.join("\n")}\n\n${foot}`;
}

function renderFixes() {
  const groups = {};
  for (const c of openFlags()) for (const o of c.owners || ["Export documentation"]) (groups[o] ||= []).push(c);
  const owners = Object.keys(groups);
  if (!owners.length) {
    $("#tab-fixes").innerHTML = `<div class="empty-state"><b>Nothing to send.</b><br>There are no open issues for this shipment.</div>`;
    return;
  }
  $("#tab-fixes").innerHTML = `<p class="muted">Each issue goes to the team that prepares the document at fault. Share the list on WhatsApp or by email; overridden flags are left out.</p>
    <div class="fix-grid">${owners.map((o, n) => {
      const items = groups[o];
      return `<div class="fix-card"><h3>${esc(o)}</h3><span class="cat">${items.length} ${items.length === 1 ? "item" : "items"} to fix</span>
        <ol>${items.map((c) => `<li class="${lang === "ml" ? "ml" : ""}"><b>${esc(c.title)}.</b> ${esc(lang === "ml" && mlMessage(c) ? mlMessage(c) : c.message)}</li>`).join("")}</ol>
        <div class="actions">
          <a class="btn small wa" target="_blank" rel="noopener" data-wa="${n}">Share on WhatsApp</a>
          <a class="btn small" data-mail="${n}">Email</a>
          <button class="btn small ghost" data-copy="${n}">Copy text</button>
        </div></div>`;
    }).join("")}</div>`;
  owners.forEach((o, n) => {
    const text = fixText(o, groups[o]);
    $(`[data-wa="${n}"]`).href = `https://wa.me/?text=${encodeURIComponent(text)}`;
    $(`[data-mail="${n}"]`).href = `mailto:?subject=${encodeURIComponent("Document fixes: " + (current.label || current.id))}&body=${encodeURIComponent(text)}`;
    $(`[data-copy="${n}"]`).onclick = async (e) => {
      try { await navigator.clipboard.writeText(text); e.target.textContent = "Copied"; } catch { prompt("Copy this text:", text); }
    };
  });
}

/* ---------- readiness ---------- */
function renderReadiness() {
  const r = current.report.readiness;
  if (!r) { $("#tab-readiness").innerHTML = ""; return; }
  const groups = [...new Set(r.items.map((i) => i.group))];
  const label = { ok: "OK", missing: "MISSING", check: "CHECK", info: "DATE" };
  $("#tab-readiness").innerHTML = `
    <div class="ready-head">
      <div><span class="muted">Product</span><br><b>${esc(r.product_name)}</b> <span class="muted">· from ${esc(r.product_basis)}</span></div>
      <div><span class="muted">Destination</span><br><b>${esc(r.destination_name)}</b> <span class="muted">· from ${esc(r.destination_basis)}</span></div>
      <div><span class="muted">Status</span><br><b>${r.counts.ok} ok · ${r.counts.missing} missing · ${r.counts.check} to check</b></div>
    </div>
    ${groups.map((g) => `<div class="check-group"><h3>${esc(g)}</h3>${r.items.filter((i) => i.group === g).map((i) => `
      <div class="check-row"><span><span class="rtag ${i.status}">${label[i.status]}</span></span>
        <div><div class="t">${esc(i.item)}</div><div class="m">${esc(i.detail)}</div></div></div>`).join("")}</div>`).join("")}
    <p class="muted" style="font-size:13px">Requirements depend on the buyer and the importing country. Items marked CHECK need a person to confirm; TallyTime does not assert rules it cannot verify.</p>`;
}

/* ---------- dashboard ---------- */
const VERDICT_TEXT = { blocked: "BLOCKED", review: "REVIEW", ready: "READY" };

function bars(items, hot) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return `<div class="bars">${items.map((i, n) => `
    <div class="bar-row"><div class="bar-label"><span>${esc(i.label)}</span>
      <div class="bar-track"><div class="bar-fill ${hot && n === 0 ? "hot" : ""}" style="width:${(100 * i.count) / max}%"></div></div></div>
      <b>${i.count}</b></div>`).join("")}</div>`;
}

async function openDashboard() {
  clearInterval(pollTimer);
  history.replaceState(null, "", "#dashboard");
  show("dashboard");
  const d = await (await fetch("/api/dashboard")).json();
  if (!d.shipments) {
    $("#dash-body").innerHTML = `<div class="empty-state" style="margin-top:18px">No shipments checked yet. Run a check and it will appear here.</div>`;
    return;
  }
  const top = d.by_document[0];
  $("#dash-body").innerHTML = `
    <div class="kpis">
      <div class="kpi"><b>${d.shipments}</b><span>shipments checked</span></div>
      <div class="kpi"><b>${d.documents}</b><span>documents read</span></div>
      <div class="kpi"><b>${d.flags}</b><span>issues caught before filing</span></div>
      <div class="kpi blocked"><b>${d.verdicts.blocked}</b><span>blocked</span></div>
      <div class="kpi review"><b>${d.verdicts.review}</b><span>needed review</span></div>
      <div class="kpi ready"><b>${d.verdicts.ready}</b><span>ready to file</span></div>
    </div>
    <div class="dash-grid">
      <div class="card"><h3>Which document is wrong most often</h3>
        <p class="muted">Counts the documents each issue points to as the likely outlier.${top ? ` Most issues come from the <b>${esc(top.owner)}</b>.` : ""}</p>
        ${d.by_document.length ? bars(d.by_document.map((x) => ({ label: `${DOC_SHORT[x.doc_type] || x.doc_type} · ${x.owner}`, count: x.count })), true) : '<p class="muted">No issues yet.</p>'}</div>
      <div class="card"><h3>Most common issues</h3>
        <p class="muted">Where the documentation process needs attention.</p>
        ${d.top_issues.length ? bars(d.top_issues.map(([label, count]) => ({ label, count })), false) : '<p class="muted">No issues yet.</p>'}</div>
    </div>
    <h3>Recent shipments</h3>
    <table class="recent"><thead><tr><th>Checked</th><th>Shipment</th><th>Result</th><th>Errors</th><th>Warnings</th><th>Documents</th><th>Flags reviewed</th></tr></thead><tbody>
    ${d.recent.map((s) => `<tr class="click" data-open="${esc(s.id)}">
      <td class="mono">${new Date(s.created * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</td>
      <td>${esc(s.label)}</td><td><span class="vtag ${s.verdict}">${VERDICT_TEXT[s.verdict]}</span></td>
      <td class="mono">${s.counts.errors}</td><td class="mono">${s.counts.warnings}</td><td class="mono">${s.documents}</td>
      <td class="mono">${s.reviewed}/${s.counts.errors + s.counts.warnings}</td></tr>`).join("")}
    </tbody></table>`;
  $$("[data-open]").forEach((r) => r.onclick = () => track(r.dataset.open));
}

/* ---------- wiring ---------- */
function init() {
  const dz = $("#dropzone");
  $("#file-input").onchange = (e) => { addFiles(e.target.files); e.target.value = ""; };
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("over"); };
  dz.ondragleave = () => dz.classList.remove("over");
  dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("over"); addFiles(e.dataTransfer.files); };
  $("#btn-check").onclick = submitUpload;
  $("#btn-clear").onclick = () => { selected = []; renderFileList(); };
  $$("[data-demo]").forEach((b) => b.onclick = () => startDemo(b.dataset.demo));
  $$(".tab").forEach((t) => t.onclick = () => switchTab(t.dataset.tab));
  $$(".lang").forEach((b) => b.onclick = () => {
    lang = b.dataset.lang;
    $$(".lang").forEach((x) => x.classList.toggle("active", x === b));
    if (current?.report) { renderIssues(); renderFixes(); }
  });
  $("#drawer-close").onclick = closeDrawer;
  $("#drawer").onclick = (e) => { if (e.target.id === "drawer") closeDrawer(); };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
  $("#home-link").onclick = goHome;
  $("#nav-new").onclick = goHome;
  $("#nav-dashboard").onclick = openDashboard;
  const [id, tab] = location.hash.slice(1).split(":");
  if (id === "dashboard") openDashboard();
  else if (id) track(id, tab);
  else show("upload");
}

init();
