# Tally: Export Document Verification

**KeralAI Grand Challenge 2026 · Team 10 · Challenge 3: Export Document Verification System**

Tally reads the documents of an export shipment (purchase order, commercial invoice, packing list, shipping bill, health certificate, certificate of origin), compares every shared fact across them and flags discrepancies **before** the shipment reaches customs or the buyer's bank. Every flag shows the exact source text it is based on, and a person confirms or overrides it.

> **AI reads, rules judge.** An AI model (IBM Granite, running locally) only *extracts* values. Every pass/fail decision comes from deterministic, inspectable rules.

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
