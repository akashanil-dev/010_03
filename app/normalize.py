"""Turn raw text values into comparable values. Plain deterministic code, no AI.

Every function returns None when it cannot make sense of the input, so the rule
engine can treat the value as missing rather than guessing.
"""

import re
from datetime import date, datetime

from rapidfuzz import fuzz

INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]
KG_PER_UNIT = {"kg": 1, "kgs": 1, "kilogram": 1, "kilograms": 1, "kilo": 1,
               "mt": 1000, "mts": 1000, "t": 1000, "ton": 1000, "tons": 1000, "tonne": 1000, "tonnes": 1000}
PORT_ALIASES = {"KOCHI": "COCHIN", "BOMBAY": "MUMBAI", "MADRAS": "CHENNAI"}
DATE_FORMATS = ["%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y",
                "%d-%B-%Y", "%d-%b-%y", "%d/%m/%y"]
COMPANY_SUFFIXES = [
    (r"\bPRIVATE\b", "PVT"), (r"\bLIMITED\b", "LTD"), (r"\bCOMPANY\b", "CO"), (r"\bCORPORATION\b", "CORP"),
    (r"\bINCORPORATED\b", "INC"),
]


def number(raw: str | None) -> float | None:
    """'1,200' -> 1200.0, '84,94,300.00' -> 8494300.0, '1200 CTNS' -> 1200.0"""
    if not raw:
        return None
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", raw)
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def count(raw: str | None) -> int | None:
    n = number(raw)
    return int(round(n)) if n is not None else None


def weight_kg(raw: str | None, unit: str | None) -> float | None:
    """Convert to kilograms. Unit may also be embedded in the raw value ('13,440.000 KGS')."""
    n = number(raw)
    if n is None:
        return None
    unit_text = (unit or "") + " " + re.sub(r"[\d,.\s]+", " ", raw or "")
    for word in re.findall(r"[a-zA-Z]+", unit_text.lower()):
        if word in KG_PER_UNIT:
            return round(n * KG_PER_UNIT[word], 3)
    return round(n, 3)  # no unit given: assume kilograms


def parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    text = re.sub(r"\s+", " ", raw.strip())
    candidates = [text] + re.findall(r"\d{1,2}[-/. ][A-Za-z]{3,9}[-/. ]\d{2,4}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}-\d{2}-\d{2}", text)
    for c in candidates:
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(c, fmt).date()
            except ValueError:
                continue
    return None


def hs_code(raw: str | None) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) >= 4 else None


def hs_equal(a: str, b: str) -> bool:
    """Equal when they agree on all the digits both carry (a certificate may only show 6 digits)."""
    n = min(len(a), len(b))
    return n >= 6 and a[:n] == b[:n]


def company(raw: str | None) -> str | None:
    """'Kayal Marine Exports Private Limited' and 'KAYAL MARINE EXPORTS PVT. LTD.' -> 'KAYAL MARINE EXPORTS PVT LTD'"""
    if not raw:
        return None
    name = raw.split(",")[0].upper()
    name = re.sub(r"[.\-&]", " ", name)
    for pattern, short in COMPANY_SUFFIXES:
        name = re.sub(pattern, short, name)
    name = re.sub(r"\bB V\b", "BV", name)
    return re.sub(r"\s+", " ", name).strip() or None


def company_equal(a: str, b: str) -> bool:
    return a == b or fuzz.token_sort_ratio(a, b) >= 92


def port(raw: str | None) -> str | None:
    """'Rotterdam (NLRTM)' -> 'ROTTERDAM', 'ANTWERP (BEANR)' -> 'ANTWERP'"""
    if not raw:
        return None
    word = re.findall(r"[A-Za-z]+", raw)
    if not word:
        return None
    city = word[0].upper()
    return PORT_ALIASES.get(city, city)


def incoterm(raw: str | None) -> str | None:
    if not raw:
        return None
    for term in INCOTERMS:
        if re.search(rf"\b{term}\b", raw.upper()):
            return term
    return None


def reference(raw: str | None) -> str | None:
    """'KME/EXP/26-27/0093 dt 18-Sep-2026' -> 'KME/EXP/26-27/0093'"""
    if not raw:
        return None
    token = raw.strip().split()[0]
    return token.upper().rstrip(",;") or None


def container(raw: str | None) -> str | None:
    """'KYLU 482913-0 / EIA 0048213' -> 'KYLU4829130'"""
    m = re.search(r"([A-Z]{4})\s?(\d{6})\s?-?\s?(\d)", (raw or "").upper())
    return "".join(m.groups()) if m else None


def lut_arn(raw: str | None) -> str | None:
    m = re.search(r"\bAD[0-9A-Z]{10,}\b", (raw or "").upper())
    return m.group() if m else None


def plain(raw: str | None) -> str | None:
    return re.sub(r"\s+", " ", raw).strip().upper() if raw else None
