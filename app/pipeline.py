"""Parse -> classify -> extract for each uploaded file, with a cache keyed by file content."""

import json
import time
from pathlib import Path

from . import cache
from .cache import file_hash  # noqa: F401  (used by the bundle splitter's cache keys)
from .extract import extract_fields, reverify
from .parsing import classify, has_text_layer, source_format, to_markdown
from .formats import IMAGE_TYPES, OFFICE_TYPES
from .schemas import ExtractedField, ParsedDocument

CACHE = cache.ROOT


def _noop(stage: str, **info) -> None:
    pass


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_TYPES:
        return "ocr"
    if suffix in OFFICE_TYPES:
        return "office"
    return "text" if has_text_layer(path) else "ocr"


def _extract_cached(doc_type: str, text: str, cache_dir: Path, on_stage=_noop) -> dict[str, ExtractedField]:
    """Model extraction keyed by document text, so the same content in a different file is not re-read."""
    cached = cache_dir / f"fields_{cache.fields_key(doc_type, text)}.json"
    if cached.exists():
        fields = {k: ExtractedField.model_validate(v) for k, v in json.loads(cached.read_text()).items()}
        reverify(fields, text)
        return fields
    on_stage("extracting", doc_type=doc_type)
    fields = extract_fields(doc_type, text, on_chars=lambda n: on_stage("extracting", chars=n))
    cached.write_text(json.dumps({k: v.model_dump() for k, v in fields.items()}))
    return fields


def process_file(path: Path, filename: str | None = None, cache_key: str | None = None,
                 cache_dir: Path = CACHE, on_stage=_noop) -> ParsedDocument:
    """Read one document. Identical files (or identical bundle pages) are served from the cache.

    on_stage(stage, **info) reports progress: "converting" (with kind), then "extracting" (with doc_type,
    then the characters the model has written so far).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{cache_key or file_hash(path)}.json"
    if cached.exists():
        doc = ParsedDocument.model_validate_json(cached.read_text())
        reverify(doc.fields, doc.text)
        doc.filename = filename or path.name
        doc.source_format = doc.source_format or source_format(path, doc.ocr_used)
        return doc

    t0 = time.time()
    on_stage("converting", kind=_kind(path))
    text, ocr = to_markdown(path)
    doc_type = classify(text)
    fields = _extract_cached(doc_type, text, cache_dir, on_stage) if doc_type else {}
    doc = ParsedDocument(filename=filename or path.name, doc_type=doc_type, text=text, ocr_used=ocr,
                         source_format=source_format(path, ocr),
                         fields=fields, seconds=round(time.time() - t0, 1))
    cached.write_text(doc.model_dump_json())
    return doc


if __name__ == "__main__":
    # Pre-fill the demo cache: python -m app.pipeline data/demo/clean/*.pdf
    import sys

    for p in sys.argv[1:]:
        d = process_file(Path(p))
        print(json.dumps({"file": p, "type": d.doc_type, "ocr": d.ocr_used, "seconds": d.seconds}), flush=True)
