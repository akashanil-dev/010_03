"""Debug helper: parse, classify and extract one or more PDFs and print the fields.

Usage: python -m tools.extract_cli data/demo/errors/*.pdf
"""

import sys
import time
from pathlib import Path

from app.extract import extract_fields
from app.parsing import classify, to_markdown


def main(paths: list[str]) -> None:
    for p in paths:
        t0 = time.time()
        text, ocr = to_markdown(Path(p))
        t1 = time.time()
        doc_type = classify(text)
        print(f"\n=== {Path(p).name}: {doc_type} (ocr={ocr}, parse {t1 - t0:.1f}s)")
        if not doc_type:
            print(text[:500])
            continue
        fields = extract_fields(doc_type, text)
        for f in fields.values():
            mark = "ok " if f.verified else "?? "
            print(f"  {mark}{f.key:18} {f.raw!r}")
        print(f"  extract {time.time() - t1:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1:])
