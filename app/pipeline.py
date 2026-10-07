"""Parse -> classify -> extract for each uploaded file, with a cache keyed by file content."""

import hashlib
import json
import time
from pathlib import Path

from .extract import extract_fields
from .parsing import classify, source_format, to_markdown
from .schemas import ExtractedField, ParsedDocument

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:24]


def _extract_cached(doc_type: str, text: str) -> dict[str, ExtractedField]:
    """Model extraction keyed by document text, so the same content in a different file is not re-read."""
    key = hashlib.sha256(f"{doc_type}\n{text}".encode()).hexdigest()[:24]
    cached = CACHE / f"fields_{key}.json"
    if cached.exists():
        return {k: ExtractedField.model_validate(v) for k, v in json.loads(cached.read_text()).items()}
    fields = extract_fields(doc_type, text)
    cached.write_text(json.dumps({k: v.model_dump() for k, v in fields.items()}))
    return fields


def process_file(path: Path, filename: str | None = None, cache_key: str | None = None) -> ParsedDocument:
    """Read one document. Identical files (or identical bundle pages) are served from the cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{cache_key or file_hash(path)}.json"
    if cached.exists():
        doc = ParsedDocument.model_validate_json(cached.read_text())
        doc.filename = filename or path.name
        doc.source_format = doc.source_format or source_format(path, doc.ocr_used)
        return doc

    t0 = time.time()
    text, ocr = to_markdown(path)
    doc_type = classify(text)
    fields = _extract_cached(doc_type, text) if doc_type else {}
    doc = ParsedDocument(filename=filename or path.name, doc_type=doc_type, text=text, ocr_used=ocr,
                         source_format=source_format(path, ocr),
                         fields=fields, seconds=round(time.time() - t0, 1))
    cached.write_text(doc.model_dump_json())
    return doc


if __name__ == "__main__":
    # Pre-fill the cache: python -m app.pipeline data/demo/clean/*.pdf
    import sys

    for p in sys.argv[1:]:
        d = process_file(Path(p))
        print(json.dumps({"file": p, "type": d.doc_type, "ocr": d.ocr_used, "seconds": d.seconds}), flush=True)
