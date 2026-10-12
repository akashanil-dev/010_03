"""Field extraction with the LLM, then verification of every value against the source text."""

import re

from rapidfuzz import fuzz

from . import llm
from . import normalize as N
from .schemas import DOC_FIELDS, DOC_TYPES, FIELDS, ExtractedField

PROMPT = """You read export shipping documents. Below is a {doc_name} converted to markdown.

Extract these fields. Copy each value EXACTLY as printed in the document (same digits, commas, spelling).
Use null when the field is not present. Do not calculate or convert anything.

Fields:
{field_list}

Document:
\"\"\"
{text}
\"\"\"
"""


def build_schema(keys: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {k: {"type": ["string", "null"]} for k in keys},
        "required": keys,
    }


def extract_fields(doc_type: str, text: str, on_chars=None) -> dict[str, ExtractedField]:
    keys = DOC_FIELDS[doc_type]
    field_list = "\n".join(f"- {k}: {FIELDS[k][1]}" for k in keys)
    prompt = PROMPT.format(doc_name=DOC_TYPES[doc_type], field_list=field_list, text=text[:12000])
    data = llm.complete_json(prompt, build_schema(keys), on_chars)

    out = {}
    for key in keys:
        raw = data.get(key)
        raw = str(raw).strip() if raw not in (None, "", "null") else None
        evidence, verified = locate(raw, text, unit=key in UNIT_KEYS) if raw else (None, False)
        out[key] = ExtractedField(key=key, raw=raw, evidence=evidence, verified=verified)
    return out


def _squash(s: str) -> str:
    return re.sub(r"[\s|*_]+", " ", s).strip().lower()


UNIT_KEYS = {"net_weight_unit", "gross_weight_unit", "quantity_unit", "price_unit"}
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def locate(raw: str, text: str, unit: bool = False) -> tuple[str | None, bool]:
    """Find the line of `text` that contains `raw`. Returns (snippet, verified).

    Verified means the value really appears in the document, so the model did not
    invent it. Unverified values are shown to the reviewer as low confidence.
    A number also counts as found when the same value is printed in another format
    ('7680' for '7,680.00'), and a unit when the document uses that unit ('USD/kg' for 'KGS').
    """
    needle = _squash(raw)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        if needle in _squash(ln):
            return _trim(ln, needle), True
    if re.fullmatch(r"[\d,.\s]+", raw.strip()) and (value := N.number(raw)) is not None:
        for ln in lines:
            printed = next((m for m in NUMBER.findall(ln) if N.number(m) == value), None)
            if printed:
                return _trim(ln, _squash(printed)), True
    if unit and (target := N.unit(raw)):
        for ln in lines:
            if target in N.units_in(ln):
                return _trim(ln, needle), True
    # Fuzzy fallback for OCR noise or small formatting differences.
    best, score = None, 0
    for ln in lines:
        s = fuzz.partial_ratio(needle, _squash(ln))
        if s > score:
            best, score = ln, s
    if best and score >= 90:
        return _trim(best, needle), True
    return (_trim(best, needle) if best and score >= 70 else None), False


def _trim(line: str, needle: str, width: int = 160) -> str:
    clean = re.sub(r"\s*\|\s*", " | ", line.strip().strip("|")).strip()
    if len(clean) <= width:
        return clean
    pos = _squash(clean).find(needle)
    start = max(0, pos - width // 3) if pos >= 0 else 0
    return ("…" if start else "") + clean[start:start + width] + "…"


def reverify(fields: dict[str, ExtractedField], text: str) -> None:
    """Check again any value not found in the source text (readings cached before the checks improved)."""
    for key, f in fields.items():
        if f.raw and not f.verified:
            evidence, verified = locate(f.raw, text, unit=key in UNIT_KEYS)
            if verified:
                f.evidence, f.verified = evidence, True
