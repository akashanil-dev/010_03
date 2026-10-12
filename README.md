# TallyTime: Export Document Verification

**KeralAI Grand Challenge 2026 · Team 10 · Challenge 3: Export Document Verification System**

TallyTime reads the documents of an export shipment (purchase order, commercial invoice, packing list, shipping bill, quality / health certificate, certificate of origin and, optionally, the letter of credit), compares every shared fact across them and flags discrepancies **before** the shipment reaches customs or the buyer's bank. Every flag shows the exact source text it is based on, and a person confirms or overrides it.

> **AI reads, rules judge.** An AI model (IBM Granite, running locally) only *extracts* values. Every pass/fail decision comes from deterministic, inspectable rules.

**Contents:** [Features](#features) · [Quick start (setup)](#quick-start) · [How to use TallyTime, step by step](#how-to-use-tallytime-step-by-step) · [What it checks](#what-it-checks) · [How it works](#how-it-works) · [Configuration](#configuration) · [Public deployment](#public-deployment) · [Results](#results-on-the-demo-shipment) · [Responsible AI](#responsible-ai-privacy-and-security) · [Limitations](#limitations)

## Features

- **Upload in any common format:** PDF (digital or scanned), photos (JPG, PNG, TIFF; tilted photos are straightened automatically), Excel, Word and CSV. Separate files or **one merged PDF** of the whole set, which is split into documents automatically.
- **Shipment Truth Matrix:** every shared field across every document on one screen; the likely wrong value is highlighted; click a value to see the exact text it was read from.
- **Issues with evidence:** plain-English explanation, suggested fix, each document's value and source text; **confirm or override** with a note (overrides require one), recorded in an **audit log**.
- **Export readiness checklist:** product detected from the HS code, destination from the port. Checks core documents, IEC, GSTIN, LUT reference and its financial year, MPEDA registration, and the EIC health certificate for seafood to the EU. Uncertain items are marked *check* rather than asserted.
- **Letter of credit compliance (UCP 600):** upload the LC and TallyTime checks the whole set against its terms before it goes to the bank: amount within the credit plus tolerance, shipment by the latest shipment date, presentation deadline, ports, Incoterms, invoice description corresponding with the credit, beneficiary/applicant, and the documents the LC requires. A set that agrees with itself can still break the LC; this catches that.
- **Lab result screening:** reads the results on quality / health certificates. A detected banned antibiotic (chloramphenicol, nitrofurans and their metabolites, malachite green) or ethylene oxide above the EU limit of 0.1 mg/kg is flagged as a blocking error. Plain rules, no AI.
- **Money and deadlines:** flags a shipping bill that claims no RoDTEP or drawback (the claim must be made on the shipping bill), and shows the 3-month amendment window and the 15-month export-proceeds deadline.
- **New rules for Kerala products:** EUDR due diligence for natural rubber to the EU (30 Dec 2026 / 30 Jun 2027) and farm traceability for seafood, shown as items to check.
- **Send fixes to the right team:** issues are grouped by who prepares the faulty document (warehouse, accounts, customs broker, documentation) with one-tap **WhatsApp**, email or copy.
- **Malayalam:** issue text, fix messages and the exported report can be in Malayalam for warehouse and floor staff (the original English stays alongside each issue).
- **Summary dashboard:** shipments checked, ready / needs review / fix before filing, the most common issues, and **which document and team causes the most errors**, for your workspace. History is stored in SQLite.
- **Accounts and shared workspaces:** sign up with email and password (confirmed by email). Each account has a private workspace; invite colleagues by email to review the same shipments together. Nobody outside a workspace can see its shipments.
- **Review team and final verdict:** workspace members appear in the reviewer dropdown on each issue, and you can add other names by hand (or switch names off). Overrides need a reason; the final verdict after review is shown on the shipment, the dashboard and the report.
- **Queue with live progress:** checks run one at a time in arrival order. You see your place in the queue, each document's progress in percent and the estimated time left, and can cancel. A **notification** (browser push, optionally email) says when a check is done, even with the tab closed.
- **Fair limits:** 5 checks per account per day (demos are free), at most 3 running or waiting at once. A document is stopped after 5 minutes, a check after 30 minutes, and a check waiting more than 2 hours is cancelled with the day's check given back.
- **Deleted after 7 days:** uploaded files, results, reviews and the audit log are erased automatically, with a [privacy policy](static/privacy.html) and [terms of use](static/terms.html).
- **Upload safety:** at most 12 files, 10 MB each and 25 pages per PDF; each file's real content is checked against its extension. Unrelated files, duplicates and documents TallyTime does not check yet (such as a bill of lading) are flagged, and unrelated files never reach the AI model.
- **Printable review report** ending with the final verdict, an **export bar under every results tab**, and **delete uploaded files** for each shipment.
- **REST API** with interactive documentation at `/docs`, so an ERP or a customs broker's system could submit documents directly.
- **Server resource meters** in the top bar, as in Google Colab: CPU, RAM and GPU of the server, with how much TallyTime and the AI model use on hover. GPU is greyed out when the server has none.
- **Interface** styled after the Wikimedia Codex design language, with the AI model in use named in the header.

---

## Quick start

Tested on Linux (Arch) with Python 3.12, CPU only. A GPU is not needed.

**You need:** about 8 GB of free RAM, about 6 GB of disk for the Python packages and models, and an internet connection for the one-time setup. After setup, TallyTime runs fully offline.

### 1. Install the prerequisites

```bash
# uv (Python package manager). Skip if you already have it.
curl -LsSf https://astral.sh/uv/install.sh | sh

# Ollama (local model runtime). See https://ollama.com/download for macOS/Windows.
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Get the code and install dependencies

```bash
git clone https://github.com/akashanil-dev/010_03.git
cd 010_03
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match -r requirements.txt
```

### 3. Download the models (one time, about 3.5 GB in total)

```bash
docling-tools models download      # document layout, table and OCR models
ollama serve &                     # skip if Ollama already runs as a service
ollama pull granite4:micro         # IBM Granite 4 (3B), runs on CPU
```

### 4. Configure

```bash
cp .env.example .env               # defaults use the local Ollama model; no API keys needed
```

Without email settings (`SMTP_HOST` empty), TallyTime prints each email, including the sign-up confirmation link, in the web app's terminal instead of sending it.

### 5. Run

```bash
./run.sh
```

This starts both parts of TallyTime, the web app and the worker that reads documents, in one terminal (their output is labelled `[web]` and `[worker]`). `Ctrl+C` stops both. Use `PORT=8001 ./run.sh` for another port. To run them separately instead: `uvicorn app.main:app --port 8000` in one terminal and `python -m app.worker` in another.

Open **http://localhost:8000**, create an account and open the confirmation link printed in the terminal (the line containing `#verify=`). Then click **"With planted errors"** to run the demo shipment, or drop your own documents. The API documentation is at **http://localhost:8000/docs** (after logging in).

### 6. Run the tests

```bash
pytest -q
```

---

## How to use TallyTime (step by step)

### A. Starting TallyTime each time

After the one-time setup above, every session is one command from the project folder (start Ollama first if it does not run as a service: `ollama serve &`):

```bash
./run.sh
```

Wait for `[worker] … Worker ready`, then open **http://localhost:8000** in a browser and log in. Leave the terminal open; press `Ctrl+C` to stop TallyTime.

> The very first document after starting takes longer (the reading models load into memory). Run one demo first if you are about to present.

### B. Try it in one click (demo shipments)

The home page has a **Try a demo shipment** panel on the right. Each button loads a ready-made set of documents from `data/demo/`. They are synthetic, with fictitious companies.

| Button | What it shows | Expected result |
|---|---|---|
| **With planted errors** | Six PDFs with 8 hidden problems | FIX BEFORE FILING: 8 errors, 1 warning |
| **Errors + scanned packing list** | Same, but the packing list is an image-only scan | Same result, read with OCR |
| **All 6 documents in one PDF** | One merged file holding the whole set | Split into six documents automatically; same result |
| **Mixed formats** | Excel invoice, phone-photo packing list, PDFs | Same result |
| **Clean set + letter of credit** | Documents that agree with each other, plus an LC they break | FIX BEFORE FILING, from 2 LC issues: late shipment, different size |
| **Lab certificate with a failed test** | A quality certificate reporting a banned antibiotic | FIX BEFORE FILING, including "Banned antibiotic residue detected" |
| **Clean shipment** | Everything consistent | READY TO FILE: no issues |

A demo that has run once before loads instantly from the cache. Reading a set for the very first time takes about a minute per document on a laptop CPU.

### C. Checking your own shipment

1. Click **New check** in the top bar (or open http://localhost:8000).
2. **Add the documents.** Drag files onto the **Drop documents here** box, or click the box to choose files. You can add:
   - PDFs (digital or scanned), photos (JPG, PNG, TIFF), Excel (.xlsx, .xls), Word (.docx) or CSV;
   - separate files, one per document, **or** one merged PDF containing the whole set.
3. The chosen files are listed under the box. Click **Clear** to start over.
4. Click **Check documents**.
5. **Wait on the progress screen.** Each file shows its state: *Checking whether this file holds several documents* (merged PDFs only), *Reading… N s*, then the detected document type and how it was read (for example *Excel file, read directly* or *Photo / image, OCR used*). When every file is done, the results open automatically.

**Upload limits:** up to **12 files** per shipment, **10 MB** per file, **25 pages** per PDF. Each file's content must really be the type its extension says (a text file renamed to `.pdf` is rejected), and empty or password-protected files are refused. Problems are listed before anything is read.

**What happens with missing, unrelated or duplicate files:**

- **Missing documents** show in the verdict banner as a checklist (✓ uploaded, ✗ missing). A missing commercial invoice, packing list or shipping bill is an **error**; a missing purchase order, certificate or certificate of origin is a **warning**.
- A file that is **not an export document** (no recognised title) is flagged with a warning and skipped. It is never sent to the AI model, so it costs almost no time.
- If the **same type is uploaded twice** (for example an old and a new invoice), only the first is compared and a warning names both files.

TallyTime recognises a document by its title: purchase order, commercial invoice, packing list, shipping bill, quality / health / inspection / analysis / phytosanitary certificate, certificate of origin, and letter of credit. A bill of lading, insurance or fumigation certificate is named as "not checked yet"; any other file is listed as *Unrecognised*. Neither is compared.

The upload page lists which documents are **required** (commercial invoice, packing list, shipping bill), **recommended** (purchase order, quality / health certificate, certificate of origin) and **optional** (letter of credit).

### D. Reading the results

**The verdict banner** (top) gives the overall answer:

- **FIX BEFORE FILING**: errors that customs or the buyer's bank would likely query. Fix them (or override them with a reason) before filing.
- **NEEDS REVIEW**: no errors, but warnings a person should decide on.
- **READY TO FILE**: every check passed (or every flag was reviewed and overridden).

Below it: number of errors and warnings (with how many were overridden), checks passed, flags reviewed and documents read, then a **document checklist** (✓ uploaded, ✗ missing). On the right are three buttons: **Print / save report**, **New shipment** and **Delete uploaded files**. Every results tab also ends with an **Export report (PDF)** bar.

The badge at the top right names the AI model reading the documents, for example *IBM Granite 4.0 Micro (3B) · on this machine*.

**Issue language**: the **English / മലയാളം** switch above the tabs changes the issue text and the fix messages to Malayalam.

The results are organised in tabs:

1. **Truth matrix**: one row per field (cartons, weights, HS code, ports, …), one column per document, ordered by the document hierarchy (purchase order first).
   - A **red cell marked "Likely wrong"** is the value that disagrees with the others.
   - An **amber cell marked "Too vague"** is a warning, for example a goods description with too few details.
   - "Not found in source" means the value could not be found word for word in the document; check it by hand.
   - *not stated* means that document does not show that field. This is often normal: a packing list rarely carries an HS code.
   - **Click any value** to open a side panel showing the value as printed, how it was compared, the exact text it was read from (highlighted), and a link to open the original file. Press `Esc` or **Close** to close it.
2. **Issues**: one card per error (red) or warning (amber). Each card shows:
   - what is wrong, in plain English, and a **suggested fix**;
   - which team it goes to ("Goes to: Warehouse");
   - each document's value with its source text, the likely wrong one highlighted.

   **Review team:** at the top of the Issues tab, add the people reviewing (for example "Anjali, Accounts") once; they are remembered in this browser. Each issue then has a **Reviewed by** dropdown. Untick **Record who made each decision** to review without names (logged as "Name not recorded").

   **Reviewing an issue:** pick the reviewer, then click **Confirm issue** if it is a real problem, or write a note and click **Override** if it is acceptable (a note is required to override). The decision, note and time are saved. Once every error is overridden and every warning reviewed, the verdict turns to READY. Click **Change** to revise a decision.
3. **Send fixes**: the open issues grouped by the team that prepares the faulty document (Warehouse, Accounts / sales, Customs broker, Export documentation). For each team:
   - **Share on WhatsApp** opens WhatsApp (web or app) with the fix list ready to send; choose the contact;
   - **Email** opens your mail app with the list in the body;
   - **Copy text** copies it to paste anywhere.

   Switch the issue language to മലയാളം first to send the list in Malayalam. Overridden issues are left out.
4. **Readiness**: the export readiness checklist. TallyTime detects the **product** from the HS code (seafood, spices, rubber, general) and the **destination** from the port, then lists:
   - **OK**: present or valid;
   - **MISSING**: required and absent (for example the LUT reference, or an EIC health certificate for seafood to the EU);
   - **CHECK**: a person should confirm (for example no RoDTEP claimed, farm traceability, EUDR for rubber);
   - **DATE**: key deadlines (shipping-bill amendment window, export-proceeds deadline).
5. **All checks**: every check TallyTime ran, grouped as *Across documents*, *Within a document*, *Compliance*, *Letter of credit* and *Lab results*, with PASS / ERROR / WARNING / SKIPPED. SKIPPED means a value needed for the check was not on the documents.
6. **Documents**: one card per document: type, how it was read, time taken, number of fields, any values to check by hand, the full list of extracted fields (click **Extracted fields**), and **Open original file**.
7. **Audit log**: every confirm and override, with the reviewer, the note and the time.

### E. Report, delete and start again

- **Print / save report** (or **Export report (PDF)** under any tab) first asks for the report language (**English** or **മലയാളം**), then opens a report with the verdict, documents, every issue with its review decision, the checks passed and, at the end, the **final verdict** with what is still open. Choose **Save as PDF** in the print dialog. Every page carries a TallyTime header with the shipment, and a footer with the date and "Page N of M"; these replace the browser's own URL and date line.
- **Delete uploaded files** permanently removes this shipment's files and results for everyone in the workspace. Otherwise they are deleted automatically 7 days after upload; the date is shown under the verdict.
- **New shipment** returns to the upload page.

### F. Dashboard

The dashboard is on the home page, below the upload area and the queue; **Dashboard** in the top bar scrolls to it. It shows every shipment checked in your current workspace (in the last 7 days):

- totals: shipments, documents read, issues caught, and how many must be fixed before filing, needed review or were ready;
- **Which document is wrong most often**, with the team that prepares it;
- **Most common issues**;
- **Recent shipments**, with the verdict after review: click a row to reopen its results.

History is stored in `data/tally.db` and survives restarts. Shipments older than 7 days are erased by the worker's hourly sweep.

### G. Using the API instead of the web page

Everything the page does is available as a REST API, documented interactively at **http://localhost:8000/docs** (log in first). Requests use the session cookie from logging in:

```bash
# 0. Log in once; the session cookie is saved in cookies.txt
curl -c cookies.txt -H "Content-Type: application/json" \
     -d '{"email": "you@example.com", "password": "your password"}' http://localhost:8000/api/auth/login

# 1. Upload documents; returns {"id": "..."} and puts the check in the queue
curl -b cookies.txt -F "files=@invoice.pdf" -F "files=@packing_list.pdf" -F "files=@shipping_bill.pdf" \
     http://localhost:8000/api/shipments

# 2. Poll until "state" is "done"; "job" shows the queue position, progress and time left,
#    and "report" then holds the verdict, checks and matrix
curl -b cookies.txt http://localhost:8000/api/shipments/<id>

# 3. Record a review decision
curl -b cookies.txt -X POST http://localhost:8000/api/shipments/<id>/reviews -H "Content-Type: application/json" \
     -d '{"check_id": "cross:cartons", "decision": "confirmed", "note": "Recounting", "reviewer": "Anjali, Accounts"}'

# 4. Your checks in the queue, and dashboard statistics for your workspace
curl -b cookies.txt http://localhost:8000/api/queue
curl -b cookies.txt http://localhost:8000/api/dashboard

# 5. Cancel a check, or delete a shipment and its uploaded files
curl -b cookies.txt -X POST http://localhost:8000/api/shipments/<id>/cancel
curl -b cookies.txt -X DELETE http://localhost:8000/api/shipments/<id>
```

### H. Regenerating the demo documents

```bash
python tools/make_demo_docs.py
```

This rewrites everything in `data/demo/`. The rewritten files are new to the cache, so the first demo run afterwards reads every document again (about a minute each).

### I. Troubleshooting

| Problem | Fix |
|---|---|
| Browser says the site can't be reached | TallyTime is not running. Start it with step A and keep the terminal open. |
| A check stays on *Waiting in the queue* | The worker is not running. Start TallyTime with `./run.sh`, which runs the worker too (step A). |
| No confirmation email arrives (local) | Without `SMTP_HOST`, emails are printed in the terminal (`[web]` lines): open the `#verify=` link from there. |
| "You have used all 5 checks for today" | The daily limit resets at midnight (India time). Demo shipments still work. On a server, `python -m app.admin set-limit EMAIL N` raises it for one account. |
| A document stays on *Reading…* or fails with "connection refused" | Ollama is not running. Run `ollama serve &` and check `curl http://localhost:11434/api/version`. |
| `model "granite4:micro" not found` | Run `ollama pull granite4:micro`. |
| `address already in use` when starting | Another TallyTime is running. Stop it, or start on another port: `uvicorn app.main:app --port 8001`. |
| A file is rejected as unsupported | Use PDF, JPG/PNG/TIFF, Excel, Word or CSV. iPhone HEIC photos: export as JPG first. |
| "larger than 10 MB" | Compress the PDF or photo, or split it. Phone photos can usually be saved at a lower resolution. |
| "the content is not a real PDF file" | The file was renamed rather than exported. Open it in its own program and export or "Save as" PDF. |
| "password-protected" | Remove the password (open it, then print or save a copy without protection) and upload again. |
| "Too many files" | Check at most 12 files per shipment; leave out duplicates and unrelated files. |
| A document shows as *Unrecognised* | Its title is not one TallyTime knows. Check that the document's heading says what it is (for example "Packing List"). |
| A value is marked "check by hand" | It was not found word for word in the document (often OCR on a poor photo). Open the file from the side panel and compare. |
| The first document is very slow | Normal: models load on first use. Later documents are faster, and repeated documents are instant. |
| "This check was interrupted" | It was running before TallyTime had a queue. Upload the documents again. Checks interrupted now resume by themselves when the worker restarts. |
| "… could not be read: the AI model is not running or not reachable" | Start Ollama (`ollama serve &`) and run the check again. The other documents were still checked, but the result is incomplete. |
| "Add reviewer names in the Review team panel above" | Add at least one name at the top of the Issues tab, or untick **Record who made each decision**. |
| The saved PDF shows a URL or "about:blank" | Your browser does not support custom print headers (older than Chrome / Edge 131). Untick **Headers and footers** in the print dialog's *More settings*. |
| The page looks unchanged after an update | Press `Ctrl+Shift+R` to reload without the browser cache. |

---

## What it checks

| Kind | Checks |
|---|---|
| **Across documents** | cartons, net and gross weight, HS code, exporter, consignee, IEC, GSTIN, ports of loading and discharge, Incoterms, container, FOB value, invoice and PO references, goods description (fuzzy match, warning only) |
| **Within a document** | invoice: quantity × rate = total, total − freight = FOB; packing list: cartons × weight per carton = total weight |
| **Compliance** | required documents present; LUT ARN on the invoice when the shipping bill declares export under LUT; date order (PO ≤ invoice ≤ shipping bill, invoice ≤ certificate of origin) |
| **Letter of credit** | amount and tolerance, currency, latest shipment date, presentation deadline and expiry, ports, Incoterms, invoice description, beneficiary and applicant, required documents |
| **Lab results** | banned antibiotics detected, ethylene oxide above the EU limit |
| **Intake** | unrecognised files, duplicate document types, known documents not checked yet, files that could not be read |

Format differences are **normalised first, not flagged**: `12.000 MTS` = `12,000 kg`, `26,455 LBS` in kg, `1200 CTNS` = `1,200 cartons`, `Pvt. Ltd.` = `Private Limited`, `0306.17.20` = `03061720` (a 4- or 6-digit code on a certificate matches its 8-digit code), `12.000,50` (European style) = `12,000.50`, `US$` = `USD`. A label copied instead of a value (such as "Buyer") counts as not stated. When a document's invoice and PO numbers are swapped, TallyTime says so instead of reporting two mismatches.

### The document hierarchy

When documents disagree, TallyTime names the **likely outlier** using a majority vote. On a tie, a value found word for word in its document beats one that was not, and then the document hierarchy decides:

```
Purchase order  →  Commercial invoice  →  Packing list  →  Shipping bill / certificates
(what was ordered)  (what is billed)       (what was packed)  (what was declared / certified)
```

Example: PO, invoice, shipping bill and certificates say 1,200 cartons, the packing list says 1,180, so the packing list is flagged as the outlier.

---

## How it works

```
file ──► merged PDF? split into documents by page titles
     ──► photo? straighten, then OCR │ Excel/Word/CSV? read directly │ PDF: OCR only if no text layer
PDF ──► Docling (layout, tables, OCR)
    ──► tables rewritten as "Header: value" lines, contacts masked
    ──► document type from title keywords
    ──► Granite extracts a fixed field list per document type, copied exactly as printed
    ──► every value is searched for in the source text → "verified" or "check by hand"
    ──► normalisation (units, numbers, dates, company names, HS codes, ports)
    ──► rule engine (cross-document, arithmetic, compliance) + hierarchy
    ──► verdict, Truth Matrix, issues with evidence, human review, audit log, printable report
```

| Path | What it does |
|---|---|
| `app/parsing.py` | Docling conversion for all formats, photo straightening, table compaction, contact masking, classification |
| `app/splitting.py` | Splits a merged PDF into one document per type |
| `app/readiness.py` | Export readiness checklist by product and destination, incentives and key dates |
| `app/lc.py` | Letter of credit compliance checks |
| `app/labtests.py` | Lab result screening on certificates |
| `app/store.py` | SQLite storage (the single source of truth, with numbered migrations) and dashboard statistics |
| `app/accounts.py`, `app/auth.py` | Accounts, sessions, email links, workspaces and invitations; the sign-in and account API |
| `app/jobs.py`, `app/worker.py` | The queue with daily quotas, and the worker: one check at a time, a killable reader process, timeouts |
| `app/progress.py` | Progress and time estimates, learned from how long each stage takes on this machine |
| `app/notify.py`, `app/mailer.py` | Web Push and email notifications; Brevo SMTP and the Turnstile bot check |
| `app/retention.py`, `app/cache.py` | 7-day erasure of shipments and per-workspace reading caches |
| `app/system.py` | Server CPU, RAM and GPU use for the top-bar meters, split into TallyTime, the AI model and the rest |
| `app/limits.py`, `app/config.py`, `app/admin.py` | Request rate limits, settings from `.env`, and the server admin command |
| `app/uploads.py` | Upload limits and file-content validation |
| `app/extract.py` | LLM field extraction and source-text verification |
| `app/llm.py` | Provider switch: local Ollama (default) or IBM watsonx; names the model for the header badge |
| `app/normalize.py` | Deterministic normalisers |
| `app/rules.py` | Rule engine and document hierarchy |
| `app/report.py` | Verdict, final verdict after review, Truth Matrix, document checklist |
| `app/pipeline.py` | Per-file pipeline; caches by file hash and by document text |
| `app/main.py` | FastAPI backend: uploads, results, reviews, the live queue (server-sent events), security headers |
| `static/` | Web interface (plain HTML, CSS, JavaScript, Codex-style theme); `session.js` handles accounts, the queue and notifications, `sw.js` shows push notifications, `ml.js` holds the Malayalam wording; `privacy.html`, `terms.html` |
| `deploy/`, `DEPLOY.md` | Server setup for the public site: Caddy, systemd services, backups |
| `tools/make_demo_docs.py` | Generates the synthetic demo shipment |
| `tests/` | 62 tests: rules, normalisation, LC, lab results, uploads and final verdict on recorded model output; storage, accounts, data isolation, workspaces, limits, the queue, the worker's timeouts, retention and the resource meters |
| `data/demo/` | The synthetic demo shipments (seven sets) |
| `data/cache/`, `data/uploads/`, `data/tally.db` | Created at run time: reading cache, uploaded files and shipment history. Not in the repository. |

---

## Configuration

Settings live in `.env` (copy it from `.env.example`). The defaults need no changes.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` to read documents on this machine, or `watsonx` to use IBM watsonx in the cloud |
| `OLLAMA_HOST` | `http://localhost:11434` | Where Ollama is running |
| `OLLAMA_MODEL` | `granite4:micro` | The local model. All measurements in this README use `granite4:micro`; other Ollama models can be set here but were not tested. |
| `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`, `WATSONX_MODEL` | (placeholders) | Only used when `LLM_PROVIDER=watsonx`. Document text is then sent to IBM's cloud, and the header badge says so. |

The public deployment adds settings for the site address, limits, email, the bot check and push notifications. They are all listed, with their defaults, in `.env.example`:

| Variable | Default | Meaning |
|---|---|---|
| `PUBLIC_URL` | `http://localhost:8000` | Address used in email links; `https://` turns on secure cookies |
| `DAILY_SHIPMENTS` | `5` | Checks per account per day (demos do not count) |
| `MAX_ACTIVE_PER_USER` | `3` | Checks one account can have running or waiting at once |
| `DOC_TIMEOUT`, `SHIPMENT_TIMEOUT`, `QUEUE_TIMEOUT` | `300`, `1800`, `7200` | Seconds before a document, a running check, or a waiting check is stopped |
| `RETENTION_DAYS` | `7` | Days before uploads, results, reviews and the audit log are erased |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | empty | Brevo SMTP relay. Empty: emails are printed to the log |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET` | empty | Cloudflare Turnstile on sign-up and password reset. Empty: no bot check |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` | empty | Web Push keys from `python -m app.notify keys`. Empty: notifications only while a tab is open |

Restart TallyTime (both processes) after changing `.env`.

---

## Public deployment

TallyTime is set up to run publicly at **https://tallytime.akashanil.dev** on an Oracle Cloud Always Free Ampere VM (4 ARM cores, 24 GB RAM): Caddy for HTTPS,
the web app, one worker and Ollama on the same machine, with SQLite. [DEPLOY.md](DEPLOY.md) has the full steps, from DNS and Brevo to backups.

---

## Results on the demo shipment

The demo is a synthetic frozen-shrimp shipment from Kochi to Rotterdam: six documents written by the team, with fictitious companies. It comes in seven sets: `clean`, `errors` (8 planted issues), `scanned` (image-only packing list), `mixed` (Excel invoice and phone-photo packing list), `bundle` (all six in one PDF), `quality` (a lab certificate reporting a nitrofuran) and `lc` (the clean set plus a letter of credit it breaks). Measured on a laptop CPU (Intel i5-1240P, no GPU), granite4:micro via Ollama:

| Set | Result |
|---|---|
| Clean | Ready. 0 false flags (25 of 25 evaluated checks pass) |
| Errors | Fix before filing. **8 of 8** planted issues caught (7 errors + 1 warning), plus the packing-list arithmetic error that follows from the wrong carton count. The 3 format traps are not flagged. |
| Errors + scanned packing list | Same result as the errors set; OCR read the scan correctly |
| Mixed formats (Excel invoice, phone-photo packing list tilted 3.5°, PDFs) | Same result: **8 of 8** caught. Without automatic straightening the tilted photo lost the carton error; with it every field was read correctly. |
| All six documents in one merged PDF | Split into the six documents by page titles; same result |
| Clean set + letter of credit | Documents agree with each other, yet **both planted LC breaches are caught**: shipment after the LC's latest date, and size 26/30 in the LC vs 31/40 on the invoice |
| Lab certificate reporting a nitrofuran | Errors-set issues plus **"Banned antibiotic residue detected"**; the "not detected" chloramphenicol line correctly passes |
| Fresh install | A clean clone following this README caught the same 8 of 8 with no cache |
| Automated tests | `pytest -q`: 17 passed |
| Extraction time | 35–109 s per new document (mean 73 s) on CPU. Documents seen before load instantly from the cache. |

These are synthetic documents written by the team, so this shows the pipeline works. It is **not** a measure of real-world accuracy.

To regenerate the demo PDFs: `python tools/make_demo_docs.py`

---

## Responsible AI, privacy and security

- **Evidence for every flag.** Each value shows the document text it came from; values not found word for word are marked "check by hand".
- **AI reads, rules judge.** The model never decides pass or fail. Rules are plain Python in `app/rules.py`.
- **Human in the loop.** Every flag can be confirmed or overridden. An override requires a note, and every decision is logged with the reviewer's name (unless names are switched off) and the time. The report and dashboard show the verdict after review, never hiding what was overridden.
- **Local by default.** Documents are parsed and read on the machine running TallyTime. Nothing is sent to an external service unless `LLM_PROVIDER=watsonx` is set.
- **Data minimisation.** Email addresses and phone numbers are masked before text is stored or sent to the model (in the spirit of India's DPDP Act 2023). Uploaded files, results, reviews and the audit log are erased after 7 days, or at once from the results screen; deleting an account erases its workspace's shipments immediately. Backups hold account details only.
- **Private by workspace.** Every request checks that the person belongs to the shipment's workspace, and anyone else gets the same "not found" as for a shipment that does not exist. Reading caches are kept per workspace, so one customer's upload is never served to another. Passwords are hashed with Argon2; emailed links are single-use, expire, and carry their token after `#` so it never reaches server logs.
- **Safe uploads.** File size, count and page limits; each file's content is checked against its type; file names are cleaned, and only the shipment's own files can be opened.
- **Not legal advice.** TallyTime is decision support; a licensed customs broker makes the final call.

## Limitations

- Tested only on the team's synthetic documents; real-world accuracy is unmeasured.
- Six document types; the readiness checklist is most detailed for seafood.
- **Handwriting is not supported reliably:** the OCR is trained on printed text and the model reads text only. Values not found word for word are marked "check by hand", and every flag shows its source for a person to confirm.
- Very blurred or dark photos may be misread; photos are straightened, but not perspective-corrected.
- An Excel workbook with several documents on different sheets is read as one document.
- Extraction takes about a minute per document on a laptop CPU; a GPU or IBM watsonx would cut this to seconds.
- One worker on one machine, with SQLite. Several workers on other machines (for example GPU servers) would need Postgres in place of SQLite; the storage code is all in `app/store.py`.
- Names typed into the review team (people who are not workspace members) are remembered per browser.
- Dates like `03/04/2026` are read the Indian way (3 April). An invoice with several product lines is checked on its totals, not line by line. In a merged PDF, a page without a title is treated as part of the document before it.

See [ATTRIBUTIONS.md](ATTRIBUTIONS.md) for third-party software, models and AI assistance.
