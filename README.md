# Tally: Export Document Verification

**KeralAI Grand Challenge 2026 · Team 10 · Challenge 3: Export Document Verification System**

Tally reads the documents of an export shipment (purchase order, commercial invoice, packing list, shipping bill, health certificate, certificate of origin), compares every shared fact across them and flags discrepancies **before** the shipment reaches customs or the buyer's bank. Every flag shows the exact source text it is based on, and a person confirms or overrides it.

> **AI reads, rules judge.** An AI model (IBM Granite, running locally) only *extracts* values. Every pass/fail decision comes from deterministic, inspectable rules.

**Contents:** [Features](#features) · [Quick start (setup)](#quick-start) · [How to use Tally, step by step](#how-to-use-tally-step-by-step) · [What it checks](#what-it-checks) · [How it works](#how-it-works) · [Results](#results-on-the-demo-shipment) · [Responsible AI](#responsible-ai-privacy-and-security) · [Limitations](#limitations)

## Features

- **Upload in any common format:** PDF (digital or scanned), photos (JPG, PNG, TIFF; tilted photos are straightened automatically), Excel, Word and CSV. Separate files or **one merged PDF** of the whole set, which is split into documents automatically.
- **Shipment Truth Matrix:** every shared field across every document on one screen; the likely wrong value is highlighted; click a value to see the exact text it was read from.
- **Issues with evidence:** plain-English explanation, suggested fix, each document's value and source text; **confirm or override** with a note (overrides require one), recorded in an **audit log**.
- **Export readiness checklist:** product detected from the HS code, destination from the port. Checks core documents, IEC, GSTIN, LUT reference and its financial year, MPEDA registration, and the EIC health certificate for seafood to the EU. Uncertain items are marked *check* rather than asserted.
- **Letter of credit compliance (UCP 600):** upload the LC and Tally checks the whole set against its terms before it goes to the bank: amount within the credit plus tolerance, shipment by the latest shipment date, presentation deadline, ports, Incoterms, invoice description corresponding with the credit, beneficiary/applicant, and the documents the LC requires. A set that agrees with itself can still break the LC; this catches that.
- **Lab result screening:** reads the results on quality / health certificates. A detected banned antibiotic (chloramphenicol, nitrofurans and their metabolites, malachite green) or ethylene oxide above the EU limit of 0.1 mg/kg is flagged as a blocking error. Plain rules, no AI.
- **Money and deadlines:** flags a shipping bill that claims no RoDTEP or drawback (the claim must be made on the shipping bill), and shows the 3-month amendment window and the 15-month export-proceeds deadline.
- **New rules for Kerala products:** EUDR due diligence for natural rubber to the EU (30 Dec 2026 / 30 Jun 2027) and farm traceability for seafood, shown as items to check.
- **Send fixes to the right team:** issues are grouped by who prepares the faulty document (warehouse, accounts, customs broker, documentation) with one-tap **WhatsApp**, email or copy.
- **Malayalam:** issue text and fix messages can be switched to Malayalam for warehouse and floor staff.
- **Summary dashboard:** shipments checked, ready / review / blocked, the most common issues, and **which document and team causes the most errors**. History is stored in SQLite.
- **Printable review report** and **delete uploaded files** for each shipment.
- **REST API** with interactive documentation at `/docs`, so an ERP or a customs broker's system could submit documents directly.

---

## Quick start

Tested on Linux (Arch) with Python 3.12, CPU only. A GPU is not needed.

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

### 5. Run

```bash
uvicorn app.main:app --port 8000
```

Open **http://localhost:8000** and click **"With planted errors"** to run the demo shipment, or drop your own documents. The API documentation is at **http://localhost:8000/docs**.

### 6. Run the tests

```bash
pytest -q
```

---

## How to use Tally (step by step)

### A. Starting Tally each time

After the one-time setup above, every session starts with three commands in a terminal, from the project folder:

```bash
ollama serve &                            # 1. start the local AI model (skip if Ollama runs as a service)
source .venv/bin/activate                 # 2. activate the Python environment
uvicorn app.main:app --port 8000          # 3. start Tally
```

Wait until the terminal prints `Application startup complete`, then open **http://localhost:8000** in a browser. Leave the terminal open; press `Ctrl+C` in it to stop Tally.

> The very first document after starting takes longer (the reading models load into memory). Run one demo first if you are about to present.

### B. Try it in one click (demo shipments)

The home page has a **Try a demo shipment** panel on the right. Each button loads a ready-made set of documents from `data/demo/`. They are synthetic, with fictitious companies.

| Button | What it shows | Expected result |
|---|---|---|
| **With planted errors** | Six PDFs with 8 hidden problems | BLOCKED: 8 errors, 1 warning |
| **Errors + scanned packing list** | Same, but the packing list is an image-only scan | Same result, read with OCR |
| **All 6 documents in one PDF** | One merged file holding the whole set | Split into six documents automatically; same result |
| **Mixed formats** | Excel invoice, phone-photo packing list, PDFs | Same result |
| **Clean set + letter of credit** | Documents that agree with each other, plus an LC they break | BLOCKED by 2 LC issues: late shipment, different size |
| **Lab certificate with a failed test** | A quality certificate reporting a banned antibiotic | BLOCKED, including "Banned antibiotic residue detected" |
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

Tally recognises a document by its title: purchase order, commercial invoice, packing list, shipping bill, quality / health / inspection certificate, certificate of origin, and letter of credit. A file it cannot recognise is listed as *Unrecognised* and left out of the comparison.

### D. Reading the results

**The verdict banner** (top) gives the overall answer:

- **BLOCKED**: errors that customs or the buyer's bank would likely query. Fix them before filing.
- **NEEDS REVIEW**: no errors, but warnings a person should decide on.
- **READY TO FILE**: every check passed (or every flag was reviewed and overridden).

Below it: number of errors and warnings, checks passed, flags reviewed and documents read. On the right are three buttons: **Print / save report**, **New shipment** and **Delete uploaded files**.

**Issue language**: the **English / മലയാളം** switch above the tabs changes the issue text and the fix messages to Malayalam.

The results are organised in tabs:

1. **Truth matrix**: one row per field (cartons, weights, HS code, ports, …), one column per document, ordered by the document hierarchy (purchase order first).
   - A **red cell marked "Likely wrong"** is the value that disagrees with the others.
   - "Not found in source" means the value could not be found word for word in the document; check it by hand.
   - **Click any value** to open a side panel showing the value as printed, how it was compared, the exact text it was read from (highlighted), and a link to open the original file. Press `Esc` or **Close** to close it.
2. **Issues**: one card per error (red) or warning (amber). Each card shows:
   - what is wrong, in plain English, and a **suggested fix**;
   - which team it goes to ("Goes to: Warehouse");
   - each document's value with its source text, the likely wrong one highlighted.

   **Reviewing an issue:** click **Confirm issue** if it is a real problem, or write a note and click **Override** if it is acceptable (a note is required to override). The decision, note and time are saved. Once every error is overridden and every warning reviewed, the verdict turns to READY. Click **Change** to revise a decision.
3. **Send fixes**: the open issues grouped by the team that prepares the faulty document (Warehouse, Accounts / sales, Customs broker, Export documentation). For each team:
   - **Share on WhatsApp** opens WhatsApp (web or app) with the fix list ready to send; choose the contact;
   - **Email** opens your mail app with the list in the body;
   - **Copy text** copies it to paste anywhere.

   Switch the issue language to മലയാളം first to send the list in Malayalam. Overridden issues are left out.
4. **Readiness**: the export readiness checklist. Tally detects the **product** from the HS code (seafood, spices, rubber, general) and the **destination** from the port, then lists:
   - **OK**: present or valid;
   - **MISSING**: required and absent (for example the LUT reference, or an EIC health certificate for seafood to the EU);
   - **CHECK**: a person should confirm (for example no RoDTEP claimed, farm traceability, EUDR for rubber);
   - **DATE**: key deadlines (shipping-bill amendment window, export-proceeds deadline).
5. **All checks**: every check Tally ran, grouped as *Across documents*, *Within a document*, *Compliance*, *Letter of credit* and *Lab results*, with PASS / ERROR / WARNING / SKIPPED. SKIPPED means a value needed for the check was not on the documents.
6. **Documents**: one card per document: type, how it was read, time taken, number of fields, any values to check by hand, the full list of extracted fields (click **Extracted fields**), and **Open original file**.
7. **Audit log**: every confirm and override, with the note and time.

### E. Report, delete and start again

- **Print / save report** opens a one-page report (verdict, documents, every issue with its review decision, checks passed) and the print dialog. Choose **Save as PDF** to keep or send it.
- **Delete uploaded files** permanently removes this shipment's files and results from the machine.
- **New shipment** returns to the upload page.

### F. Dashboard

Click **Dashboard** in the top bar to see every shipment checked:

- totals: shipments, documents read, issues caught, and how many were blocked, needed review or were ready;
- **Which document is wrong most often**, with the team that prepares it;
- **Most common issues**;
- **Recent shipments**: click a row to reopen its results.

History is stored in `data/tally.db` and survives restarts. Delete that file to start with an empty dashboard.

### G. Using the API instead of the web page

Everything the page does is available as a REST API, documented interactively at **http://localhost:8000/docs**. For example:

```bash
# 1. Upload documents; returns {"id": "..."}
curl -F "files=@invoice.pdf" -F "files=@packing_list.pdf" -F "files=@shipping_bill.pdf" \
     http://localhost:8000/api/shipments

# 2. Poll until "state" is "done"; the "report" field then holds the verdict, checks and matrix
curl http://localhost:8000/api/shipments/<id>

# 3. Record a review decision
curl -X POST http://localhost:8000/api/shipments/<id>/reviews -H "Content-Type: application/json" \
     -d '{"check_id": "cross:cartons", "decision": "confirmed", "note": "Recounting"}'

# 4. Dashboard statistics
curl http://localhost:8000/api/dashboard
```

### H. Regenerating the demo documents

```bash
python tools/make_demo_docs.py
```

This rewrites everything in `data/demo/`. The rewritten files are new to the cache, so the first demo run afterwards reads every document again (about a minute each).

### I. Troubleshooting

| Problem | Fix |
|---|---|
| Browser says the site can't be reached | Tally is not running. Start it with step A and keep the terminal open. |
| A document stays on *Reading…* or fails with "connection refused" | Ollama is not running. Run `ollama serve &` and check `curl http://localhost:11434/api/version`. |
| `model "granite4:micro" not found` | Run `ollama pull granite4:micro`. |
| `address already in use` when starting | Another Tally is running. Stop it, or start on another port: `uvicorn app.main:app --port 8001`. |
| A file is rejected as unsupported | Use PDF, JPG/PNG/TIFF, Excel, Word or CSV. iPhone HEIC photos: export as JPG first. |
| A document shows as *Unrecognised* | Its title is not one Tally knows. Check that the document's heading says what it is (for example "Packing List"). |
| A value is marked "check by hand" | It was not found word for word in the document (often OCR on a poor photo). Open the file from the side panel and compare. |
| The first document is very slow | Normal: models load on first use. Later documents are faster, and repeated documents are instant. |
| "This check was interrupted by a server restart" | Tally was restarted while reading. Upload the documents again. |

---

## What it checks

| Kind | Checks |
|---|---|
| **Across documents** | cartons, net and gross weight, HS code, exporter, consignee, IEC, GSTIN, ports of loading and discharge, Incoterms, container, FOB value, invoice and PO references, goods description (fuzzy match, warning only) |
| **Within a document** | invoice: quantity × rate = total, total − freight = FOB; packing list: cartons × weight per carton = total weight |
| **Compliance** | required documents present; LUT ARN on the invoice when the shipping bill declares export under LUT; date order (PO ≤ invoice ≤ shipping bill, invoice ≤ certificate of origin) |
| **Letter of credit** | amount and tolerance, currency, latest shipment date, presentation deadline and expiry, ports, Incoterms, invoice description, beneficiary and applicant, required documents |
| **Lab results** | banned antibiotics detected, ethylene oxide above the EU limit |

Format differences are **normalised first, not flagged**: `12.000 MTS` = `12,000 kg`, `1200 CTNS` = `1,200 cartons`, `Pvt. Ltd.` = `Private Limited`, `0306.17.20` = `03061720`.

### The document hierarchy

When documents disagree, Tally names the **likely outlier** using a majority vote, with ties broken by the document hierarchy:

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
| `app/store.py` | SQLite history and dashboard statistics |
| `app/extract.py` | LLM field extraction and source-text verification |
| `app/llm.py` | Provider switch: local Ollama (default) or IBM watsonx |
| `app/normalize.py` | Deterministic normalisers |
| `app/rules.py` | Rule engine and document hierarchy |
| `app/report.py` | Verdict and Truth Matrix |
| `app/pipeline.py` | Per-file pipeline; caches by file hash and by document text |
| `app/main.py` | FastAPI backend |
| `static/` | Web interface (plain HTML, CSS, JavaScript); `ml.js` holds the Malayalam wording |
| `tools/make_demo_docs.py` | Generates the synthetic demo shipment |
| `tests/` | Rule engine tests on recorded model output |

---

## Results on the demo shipment

The demo is a synthetic frozen-shrimp shipment from Kochi to Rotterdam: six documents written by the team, with fictitious companies. It comes in seven sets: `clean`, `errors` (8 planted issues), `scanned` (image-only packing list), `mixed` (Excel invoice and phone-photo packing list), `bundle` (all six in one PDF), `quality` (a lab certificate reporting a nitrofuran) and `lc` (the clean set plus a letter of credit it breaks). Measured on a laptop CPU (Intel i5-1240P, no GPU), granite4:micro via Ollama:

| Set | Result |
|---|---|
| Clean | Ready. 0 false flags (24 of 24 evaluated checks pass) |
| Errors | Blocked. **8 of 8** planted issues caught (7 errors + 1 warning), plus the packing-list arithmetic error that follows from the wrong carton count. The 3 format traps are not flagged. |
| Errors + scanned packing list | Same result as the errors set; OCR read the scan correctly |
| Mixed formats (Excel invoice, phone-photo packing list tilted 3.5°, PDFs) | Same result: **8 of 8** caught. Without automatic straightening the tilted photo lost the carton error; with it every field was read correctly. |
| All six documents in one merged PDF | Split into the six documents by page titles; same result |
| Extraction time | 35–109 s per new document (mean 73 s) on CPU. Documents seen before load instantly from the cache. |

These are synthetic documents written by the team, so this shows the pipeline works. It is **not** a measure of real-world accuracy.

To regenerate the demo PDFs: `python tools/make_demo_docs.py`

---

## Responsible AI, privacy and security

- **Evidence for every flag.** Each value shows the document text it came from; values not found word for word are marked "check by hand".
- **AI reads, rules judge.** The model never decides pass or fail. Rules are plain Python in `app/rules.py`.
- **Human in the loop.** Every flag can be confirmed or overridden. An override requires a note, and every decision is logged with a time.
- **Local by default.** Documents are parsed and read on the machine running Tally. Nothing is sent to an external service unless `LLM_PROVIDER=watsonx` is set.
- **Data minimisation.** Email addresses and phone numbers are masked before text is stored or sent to the model (in the spirit of India's DPDP Act 2023). Uploaded files can be deleted from the results screen.
- **Not legal advice.** Tally is decision support; a licensed customs broker makes the final call.

## Limitations

- Tested only on the team's synthetic documents; real-world accuracy is unmeasured.
- Six document types; the readiness checklist is most detailed for seafood.
- **Handwriting is not supported reliably:** the OCR is trained on printed text and the model reads text only. Values not found word for word are marked "check by hand", and every flag shows its source for a person to confirm.
- Very blurred or dark photos may be misread; photos are straightened, but not perspective-corrected.
- An Excel workbook with several documents on different sheets is read as one document.
- Extraction takes about a minute per document on a laptop CPU; a GPU or IBM watsonx would cut this to seconds.
- Single process with SQLite; a production deployment would add user accounts, Postgres and a job queue with several workers.

See [ATTRIBUTIONS.md](ATTRIBUTIONS.md) for third-party software, models and AI assistance.
