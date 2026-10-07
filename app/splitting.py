"""Split a merged PDF (one file holding several documents) into one PDF per document.

Each page's type comes from its title. A page without a recognisable title is
treated as a continuation of the previous document. Files holding only one
document type are left untouched.
"""

from pathlib import Path

import pymupdf

from .parsing import TITLE_KEYWORDS, to_markdown

HEAD_CHARS = 400


def _page_type(text: str) -> str | None:
    head = text[:HEAD_CHARS].upper()
    for doc_type, words in TITLE_KEYWORDS:
        if any(w in head for w in words):
            return doc_type
    return None


def _page_texts(path: Path, out_dir: Path) -> list[str]:
    """Text of each page: the PDF text layer if present, otherwise OCR of that page."""
    texts = []
    with pymupdf.open(path) as pdf:
        for i, page in enumerate(pdf):
            text = page.get_text().strip()
            if len(text) < 30:  # scanned page: OCR just this page
                single = out_dir / f".page_{i}.pdf"
                one = pymupdf.open()
                one.insert_pdf(pdf, from_page=i, to_page=i)
                one.save(single)
                one.close()
                text, _ = to_markdown(single)
                single.unlink(missing_ok=True)
            texts.append(text.lstrip("# "))
    return texts


def split_bundle(path: Path, out_dir: Path) -> list[dict] | None:
    """Return [{"filename", "path", "pages", "doc_type"}] for each document, or None if not a bundle."""
    with pymupdf.open(path) as pdf:
        if pdf.page_count < 2:
            return None
    texts = _page_texts(path, out_dir)

    groups: list[dict] = []
    for i, text in enumerate(texts):
        t = _page_type(text)
        if groups and (t is None or t == groups[-1]["doc_type"]):
            groups[-1]["pages"].append(i)
        else:
            groups.append({"doc_type": t, "pages": [i]})

    if len({g["doc_type"] for g in groups}) < 2:
        return None

    parts = []
    with pymupdf.open(path) as pdf:
        for n, g in enumerate(groups, 1):
            first, last = g["pages"][0], g["pages"][-1]
            pages = f"p{first + 1}" if first == last else f"p{first + 1}-{last + 1}"
            name = f"{path.stem}_{n:02d}_{g['doc_type'] or 'unknown'}_{pages}.pdf"
            part = pymupdf.open()
            part.insert_pdf(pdf, from_page=first, to_page=last)
            part.save(out_dir / name)
            part.close()
            parts.append({"filename": name, "path": str(out_dir / name), "pages": [p + 1 for p in g["pages"]],
                          "doc_type": g["doc_type"]})
    return parts
