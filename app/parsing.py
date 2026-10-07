"""Documents to text with Docling.

PDFs: OCR only runs for pages without a text layer.
Images (photos, scans): wrapped in a PDF and OCR'd.
Excel, Word, CSV: read directly, so the text is exact and no OCR is needed.
"""

import re
from functools import lru_cache
from pathlib import Path

import pymupdf
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from .schemas import DOC_TYPES

# Title keywords, checked in this order (certificate of origin before generic certificates).
TITLE_KEYWORDS = [
    ("certificate_of_origin", ["CERTIFICATE OF ORIGIN"]),
    ("health_certificate", ["HEALTH CERTIFICATE", "SANITARY CERTIFICATE", "PHYTOSANITARY CERTIFICATE",
                            "QUALITY CERTIFICATE", "CERTIFICATE OF QUALITY", "CERTIFICATE OF ANALYSIS",
                            "INSPECTION CERTIFICATE", "CERTIFICATE OF INSPECTION", "TEST CERTIFICATE",
                            "LABORATORY TEST REPORT", "TEST REPORT"]),
    ("shipping_bill", ["SHIPPING BILL"]),
    ("packing_list", ["PACKING LIST"]),
    ("commercial_invoice", ["COMMERCIAL INVOICE", "EXPORT INVOICE", "TAX INVOICE"]),
    ("purchase_order", ["PURCHASE ORDER", "BUYER'S ORDER"]),
]


@lru_cache(maxsize=2)
def _converter(ocr: bool) -> DocumentConverter:
    opts = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def has_text_layer(path: Path) -> bool:
    with pymupdf.open(path) as pdf:
        return sum(len(page.get_text().strip()) for page in pdf) > 50


IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
OFFICE_TYPES = {".xlsx", ".xls", ".ods", ".docx", ".doc", ".odt", ".csv"}
SUPPORTED = {".pdf"} | IMAGE_TYPES | OFFICE_TYPES
FORMAT_LABEL = {".xlsx": "Excel", ".xls": "Excel", ".ods": "Spreadsheet", ".docx": "Word", ".doc": "Word",
                ".odt": "Document", ".csv": "CSV"}


def skew_angle(img) -> float:
    """Estimate how far a photographed page is rotated (degrees).

    Rotates a small greyscale copy through candidate angles and keeps the one
    where text lines are most horizontal, i.e. the row-darkness profile is sharpest.
    """
    import numpy as np
    from PIL import Image

    small = img.convert("L")
    small.thumbnail((900, 900))
    best, best_score = 0.0, -1.0
    for angle in np.arange(-6.0, 6.01, 0.25):
        rotated = np.asarray(small.rotate(float(angle), resample=Image.BILINEAR, fillcolor=255), dtype=float)
        profile = (255 - rotated).sum(axis=1)
        score = float(np.var(np.diff(profile)))
        if score > best_score:
            best, best_score = float(angle), score
    return best


def image_to_pdf(path: Path) -> Path:
    """Straighten a photo or scanned image and wrap it in a one-page PDF for the OCR path."""
    import io

    from PIL import Image, ImageOps

    out = path.with_name(path.name + ".pdf")
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    angle = skew_angle(img)
    if abs(angle) >= 0.5:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    with pymupdf.open(stream=buf.getvalue(), filetype="png") as pic:
        pdf_bytes = pic.convert_to_pdf()
    with pymupdf.open("pdf", pdf_bytes) as pdf:
        pdf.save(out)
    return out


def to_markdown(path: Path) -> tuple[str, bool]:
    """Return (markdown, ocr_used) for any supported file."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_TYPES:
        pdf = image_to_pdf(path)
        try:
            result = _converter(True).convert(str(pdf))
        finally:
            pdf.unlink(missing_ok=True)
        ocr = True
    elif suffix in OFFICE_TYPES:
        result = _converter(False).convert(str(path))
        ocr = False
    else:
        ocr = not has_text_layer(path)
        result = _converter(ocr).convert(str(path))
    return mask_contacts(compact(result.document.export_to_markdown())), ocr


def source_format(path: Path, ocr: bool) -> str:
    """How the document arrived, shown to the reviewer as a hint of how reliable the reading is."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_TYPES:
        return "Photo / image, OCR used"
    if suffix in FORMAT_LABEL:
        return f"{FORMAT_LABEL[suffix]} file, read directly"
    return "Scanned PDF, OCR used" if ocr else "Digital PDF, text layer"


EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:(?:tel|phone|mob|mobile|ph|fax)\.?\s*:?\s*|\+)\d[\d\s()-]{7,}\d", re.IGNORECASE)


def mask_contacts(text: str) -> str:
    """Hide personal contact details before the text is stored or sent to the model (DPDP Act 2023)."""
    return PHONE.sub("[phone hidden]", EMAIL.sub("[email hidden]", text))


def _cells(line: str) -> list[str]:
    return [c.strip().replace("&#124;", "|") for c in line.strip().strip("|").split("|")]


def compact(markdown: str) -> str:
    """Rewrite markdown tables as 'Header: value' lines.

    Docling pads table cells with spaces and repeats merged cells, which doubles
    the token count and makes small models mix up columns. Key/value lines are
    shorter and unambiguous.
    """
    out, table = [], []

    def flush():
        if not table:
            return
        rows = [_cells(r) for r in table if not set(r.replace("|", "").strip()) <= set("-: ")]
        if rows and len(rows[0]) == 2:                      # key/value table
            out.extend(f"{k}: {v}" for k, v in rows if k or v)
        elif rows:
            header = rows[0]
            for row in rows[1:]:
                uniq = list(dict.fromkeys(c for c in row if c))
                if len(uniq) <= 2 and len(row) > 2:          # merged label row, e.g. "Total | ... | 102,000"
                    out.append(": ".join(uniq))
                    continue
                pairs = [f"{h or 'col'}: {c}" for h, c in zip(header, row) if c]
                out.append("; ".join(pairs))
        out.append("")
        table.clear()

    for line in markdown.splitlines():
        if line.lstrip().startswith("|"):
            table.append(line)
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(l for i, l in enumerate(out) if l.strip() or (i and out[i - 1].strip()))


def classify(text: str) -> str | None:
    """Pick the document type from title keywords near the top of the document."""
    head = text[:600].upper()
    for doc_type, words in TITLE_KEYWORDS:
        if any(w in head for w in words):
            return doc_type
    whole = text.upper()
    for doc_type, words in TITLE_KEYWORDS:
        if any(w in whole for w in words):
            return doc_type
    return None


def warm_up() -> None:
    """Load the Docling models once so the first real upload is not slow."""
    _converter(False)


assert set(t for t, _ in TITLE_KEYWORDS) == set(DOC_TYPES)
