"""Parse -> classify -> extract for each uploaded file, with a cache keyed by file content."""

import hashlib
import json
import time
from pathlib import Path

from .extract import extract_fields
from .parsing import classify, to_markdown
from .schemas import ParsedDocument

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:24]


def process_file(path: Path, filename: str | None = None) -> ParsedDocument:
    """Read one document. Identical files are served from the cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{file_hash(path)}.json"
    if cached.exists():
        doc = ParsedDocument.model_validate_json(cached.read_text())
        doc.filename = filename or path.name
        return doc

    t0 = time.time()
    text, ocr = to_markdown(path)
    doc_type = classify(text)
    fields = extract_fields(doc_type, text) if doc_type else {}
    doc = ParsedDocument(filename=filename or path.name, doc_type=doc_type, text=text, ocr_used=ocr,
                         fields=fields, seconds=round(time.time() - t0, 1))
    cached.write_text(doc.model_dump_json())
    return doc


if __name__ == "__main__":
    # Pre-fill the cache: python -m app.pipeline data/demo/clean/*.pdf
    import sys

    for p in sys.argv[1:]:
        d = process_file(Path(p))
        print(json.dumps({"file": p, "type": d.doc_type, "ocr": d.ocr_used, "seconds": d.seconds}), flush=True)
