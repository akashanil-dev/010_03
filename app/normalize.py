"""Turn raw text values into comparable values. Plain deterministic code, no AI.

Every function returns None when it cannot make sense of the input, so the rule
engine can treat the value as missing rather than guessing.
"""

import re
from datetime import date, datetime
from typing import NamedTuple

from rapidfuzz import fuzz

INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]
KG_PER_UNIT = {"kg": 1, "kgs": 1, "kilogram": 1, "kilograms": 1, "kilo": 1,
               "mt": 1000, "mts": 1000, "t": 1000, "ton": 1000, "tons": 1000, "tonne": 1000, "tonnes": 1000,
               "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237, "g": 0.001, "gm": 0.001,
               "grams": 0.001}
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
    eu = re.search(r"\d{1,3}(?:\.\d{3})+,\d+", raw)   # European style: 12.000,50
    if eu:
        return float(eu.group().replace(".", "").replace(",", "."))
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


class Unit(NamedTuple):
    dim: str        # what is measured: weight, piece, pair, set, length, area, package
    factor: float   # size of one unit in the dimension's base unit (kg, piece, pair, set, metre, m², package)
    label: str      # how amounts in this unit are shown


UNIT_WORDS = {
    **{w: Unit("weight", 1, "kg") for w in ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms")},
    **{w: Unit("weight", 1000, "MT") for w in ("mt", "mts", "t", "ton", "tons", "tonne", "tonnes", "metric")},
    **{w: Unit("weight", 0.45359237, "lb") for w in ("lb", "lbs", "pound", "pounds")},
    **{w: Unit("weight", 0.001, "g") for w in ("g", "gm", "gms", "gram", "grams")},
    **{w: Unit("piece", 1, "pcs") for w in ("pc", "pcs", "piece", "pieces", "nos", "no", "number", "numbers",
                                             "unit", "units", "each", "ea")},
    **{w: Unit("piece", 12, "dozen") for w in ("doz", "dozen", "dozens", "dz")},
    **{w: Unit("pair", 1, "pairs") for w in ("pair", "pairs", "pr", "prs")},
    **{w: Unit("set", 1, "sets") for w in ("set", "sets")},
    **{w: Unit("length", 1, "m") for w in ("m", "mtr", "mtrs", "metre", "metres", "meter", "meters", "rmt")},
    **{w: Unit("area", 1, "m²") for w in ("sqm", "sqmt", "sqmtr", "m2")},
    **{w: Unit("area", 0.09290304, "sq ft") for w in ("sqft", "sft")},
    **{w: Unit("package", 1, "packages") for w in ("ctn", "ctns", "carton", "cartons", "box", "boxes", "bag",
                                                   "bags", "bale", "bales", "roll", "rolls", "drum", "drums",
                                                   "case", "cases", "pkg", "pkgs", "package", "packages")},
}


def unit(raw: str | None) -> Unit | None:
    """The unit a quantity or price is in: 'USD/MT' -> MT, 'per dozen' -> dozen, 'Sq. M' -> m². None if unknown."""
    if not raw:
        return None
    text = raw.lower().replace("²", "2")
    text = re.sub(r"\bsq\.?\s*(m|mt|mtr|metre|meter)s?\b", "sqm", text)
    text = re.sub(r"\bsq\.?\s*(ft|feet|foot)\b", "sqft", text)
    for word in re.findall(r"[a-z]+\d?", text):
        if word in UNIT_WORDS:
            return UNIT_WORDS[word]
    return None


def units_in(text: str) -> set[Unit]:
    """Every unit mentioned in a piece of text."""
    text = re.sub(r"\bsq\.?\s*(m|mt|mtr|metre|meter)s?\b", "sqm", text.lower().replace("²", "2"))
    text = re.sub(r"\bsq\.?\s*(ft|feet|foot)\b", "sqft", text)
    return {UNIT_WORDS[w] for w in re.findall(r"[a-z]+\d?", text) if w in UNIT_WORDS}


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
    return n >= 4 and a[:n] == b[:n]   # a certificate may carry only 4 or 6 digits


PLACEHOLDER_NAMES = {"BUYER", "CONSIGNEE", "SELLER", "EXPORTER", "SHIPPER", "IMPORTER", "APPLICANT", "BENEFICIARY",
                     "NOTIFY PARTY", "TO ORDER", "TO THE ORDER", "NA", "N/A", "NIL", "NONE", "SAME AS ABOVE", "-"}


def company(raw: str | None) -> str | None:
    """'Kayal Marine Exports Private Limited' and 'KAYAL MARINE EXPORTS PVT. LTD.' -> 'KAYAL MARINE EXPORTS PVT LTD'"""
    if not raw or raw.strip().upper().rstrip(":.") in PLACEHOLDER_NAMES:
        return None   # the model copied a label ("Buyer"), not a name
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
    """'KME/EXP/26-27/0093 dt 18-Sep-2026' -> 'KME/EXP/26-27/0093'; 'Invoice No.: X/1' -> 'X/1'"""
    if not raw:
        return None
    text = raw.split(":", 1)[1] if re.match(r"^\s*[A-Za-z .']+:", raw) else raw
    for token in text.split():
        if re.search(r"\d", token):
            return token.upper().rstrip(",;") or None
    return None


def container(raw: str | None) -> str | None:
    """'KYLU 482913-0 / EIA 0048213' -> 'KYLU4829130'"""
    m = re.search(r"([A-Z]{4})\s?(\d{6})\s?-?\s?(\d)", (raw or "").upper())
    return "".join(m.groups()) if m else None


def lut_arn(raw: str | None) -> str | None:
    m = re.search(r"\bAD[0-9A-Z]{10,}\b", (raw or "").upper())
    return m.group() if m else None


def iec(raw: str | None) -> str | None:
    """'IEC AAKCK7731M' -> 'AAKCK7731M' (10 characters)."""
    m = re.search(r"\b[A-Z0-9]{10}\b", (raw or "").upper().replace("IEC", " "))
    return m.group() if m else None


def gstin(raw: str | None) -> str | None:
    """'GSTIN 32AAKCK7731M1Z9' -> '32AAKCK7731M1Z9' (15 characters, starts with the state code)."""
    m = re.search(r"\b\d{2}[A-Z0-9]{13}\b", (raw or "").upper())
    return m.group() if m else None


CURRENCY_ALIASES = {"US$": "USD", "$": "USD", "US DOLLARS": "USD", "US DOLLAR": "USD", "€": "EUR", "EURO": "EUR",
                    "EUROS": "EUR", "₹": "INR", "RS": "INR", "RUPEES": "INR", "£": "GBP", "¥": "JPY", "YEN": "JPY"}


def currency(raw: str | None) -> str | None:
    if not raw:
        return None
    up = raw.strip().upper().rstrip(".")
    return CURRENCY_ALIASES.get(up, up)


def plain(raw: str | None) -> str | None:
    return re.sub(r"\s+", " ", raw).strip().upper() if raw else None
