"""Upload limits and file validation.

Keeps random or oversized files out before anything is parsed or sent to the
model: size, count and page limits, and a check that each file's content really
is the type its extension claims (a .txt renamed to .pdf is rejected).
"""

from pathlib import Path

import pymupdf

MAX_FILE_MB = 10
MAX_FILES = 12
MAX_PDF_PAGES = 25
CHUNK = 1024 * 1024

# Leading bytes ("magic numbers") each file type must start with.
SIGNATURES = {
    ".pdf": [b"%PDF"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"], ".jpeg": [b"\xff\xd8\xff"],
    ".tif": [b"II*\x00", b"MM\x00*"], ".tiff": [b"II*\x00", b"MM\x00*"],
    ".bmp": [b"BM"],
    ".webp": [b"RIFF"],
    ".xlsx": [b"PK\x03\x04"], ".docx": [b"PK\x03\x04"], ".ods": [b"PK\x03\x04"], ".odt": [b"PK\x03\x04"],
    ".xls": [b"\xd0\xcf\x11\xe0"], ".doc": [b"\xd0\xcf\x11\xe0"],
}


class UploadError(ValueError):
    pass


async def save_limited(upload, dest: Path) -> None:
    """Stream an upload to disk, stopping as soon as it passes the size limit."""
    limit, size = MAX_FILE_MB * 1024 * 1024, 0
    with open(dest, "wb") as out:
        while chunk := await upload.read(CHUNK):
            size += len(chunk)
            if size > limit:
                raise UploadError(f"{upload.filename}: larger than {MAX_FILE_MB} MB. Compress it or split it into smaller files.")
            out.write(chunk)
    if size == 0:
        raise UploadError(f"{upload.filename}: the file is empty.")


def check_content(path: Path, filename: str) -> None:
    """Raise UploadError if the file's content does not match its extension, or a PDF is unusable."""
    suffix = path.suffix.lower()
    head = path.read_bytes()[:16]
    if suffix == ".csv":
        if b"\x00" in path.read_bytes()[:4096]:
            raise UploadError(f"{filename}: this is not a text CSV file.")
        return
    if not any(head.startswith(sig) for sig in SIGNATURES.get(suffix, [])):
        raise UploadError(f"{filename}: the content is not a real {suffix[1:].upper()} file "
                          "(the extension may have been changed).")
    if suffix == ".webp" and head[8:12] != b"WEBP":
        raise UploadError(f"{filename}: the content is not a real WEBP image.")
    if suffix == ".pdf":
        try:
            with pymupdf.open(path) as pdf:
                if pdf.needs_pass:
                    raise UploadError(f"{filename}: the PDF is password-protected. Remove the password and upload again.")
                if pdf.page_count > MAX_PDF_PAGES:
                    raise UploadError(f"{filename}: {pdf.page_count} pages; the limit is {MAX_PDF_PAGES} pages per file.")
        except UploadError:
            raise
        except Exception:
            raise UploadError(f"{filename}: the PDF is damaged and cannot be opened.")


def page_count(path: Path) -> int:
    """Pages in a PDF (for time estimates); other files count as one."""
    if path.suffix.lower() != ".pdf":
        return 1
    try:
        with pymupdf.open(path) as pdf:
            return pdf.page_count
    except Exception:
        return 1
