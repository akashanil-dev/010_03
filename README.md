# Tally: Export Document Verification

**KeralAI Grand Challenge 2026 · Team 10 · Challenge 3: Export Document Verification System**

Tally reads the documents of an export shipment (purchase order, commercial invoice, packing list, shipping bill, health certificate, certificate of origin), compares every shared fact across them and flags discrepancies **before** the shipment reaches customs or the buyer's bank. Every flag shows the exact source text it is based on, and a person confirms or overrides it.

> **AI reads, rules judge.** An AI model (IBM Granite, running locally) only *extracts* values. Every pass/fail decision comes from deterministic, inspectable rules.

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

Open **http://localhost:8000** and click **"With planted errors"** to run the demo shipment, or drop your own PDFs.

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
PDF ──► Docling (layout, tables, OCR only if the page has no text layer)
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
| `app/parsing.py` | Docling conversion, table compaction, contact masking, classification |
| `app/extract.py` | LLM field extraction and source-text verification |
| `app/llm.py` | Provider switch: local Ollama (default) or IBM watsonx |
| `app/normalize.py` | Deterministic normalisers |
| `app/rules.py` | Rule engine and document hierarchy |
| `app/report.py` | Verdict and Truth Matrix |
| `app/pipeline.py` | Per-file pipeline with a content-hash cache |
| `app/main.py` | FastAPI backend |
| `static/` | Web interface (plain HTML, CSS, JavaScript) |
| `tools/make_demo_docs.py` | Generates the synthetic demo shipment |
| `tests/` | Rule engine tests on recorded model output |

---

## Results on the demo shipment

The demo is a synthetic frozen-shrimp shipment from Kochi to Rotterdam: six documents written by the team, with fictitious companies. It comes in three sets: `clean`, `errors` (8 planted issues) and `scanned` (errors set with an image-only packing list). Measured on a laptop CPU (Intel i5-1240P, no GPU), granite4:micro via Ollama:

| Set | Result |
|---|---|
| Clean | Ready. 0 false flags (24 of 24 evaluated checks pass) |
| Errors | Blocked. **8 of 8** planted issues caught (7 errors + 1 warning), plus the packing-list arithmetic error that follows from the wrong carton count. The 3 format traps are not flagged. |
| Errors + scanned packing list | Same result as the errors set; OCR read the scan correctly |
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
- Six document types and a seafood-oriented rule set.
- Handwritten or very poor scans may be misread; low-confidence values are marked for manual checking.
- Extraction takes about a minute per document on a laptop CPU; a GPU or IBM watsonx would cut this to seconds.
- Shipments are kept in memory and are lost when the server restarts.

See [ATTRIBUTIONS.md](ATTRIBUTIONS.md) for third-party software, models and AI assistance.
