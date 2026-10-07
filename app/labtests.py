"""Screen the test results printed on quality / health certificates.

Documents can agree with each other and still be rejected at the border because
of what the lab found. This reads result lines with plain rules (no AI):
  - banned antibiotics in seafood (chloramphenicol, nitrofurans and their
    metabolites, malachite green): any detection is flagged;
  - ethylene oxide in spices: above the EU limit of 0.1 mg/kg is flagged.
"""

import re

from .rules import Check, Value
from .schemas import DOC_TYPES, ParsedDocument

ANTIBIOTICS = re.compile(r"chloramphenicol|nitrofuran|\bAOZ\b|\bAMOZ\b|\bAHD\b|\bSEM\b|malachite", re.I)
ETO = re.compile(r"ethylene oxide|\bEtO\b|2-chloroethanol", re.I)
NEGATIVE = re.compile(r"not detected|\bN\.?D\.?\b|absent|negative|\bnil\b|below (?:the )?(?:limit|LOQ|LOD)|<\s*LOQ", re.I)
POSITIVE = re.compile(r"\bdetected\b|positive|present", re.I)
EU_ETO_LIMIT = 0.1  # mg/kg


def _lines(doc: ParsedDocument, pattern) -> list[str]:
    return [ln.strip() for ln in (doc.text or "").splitlines() if pattern.search(ln)]


def _result_part(line: str, test: re.Pattern) -> str:
    """The result of a test line, without the test name or the limit column.

    Tables arrive as 'Parameter: Nitrofurans; Result: Detected 1.6 ug/kg; Limit: Not detected'.
    """
    cells = [c.strip() for c in line.split(";")]
    for c in cells:
        if re.match(r"(result|value|finding|observation)s?\b", c, re.I):
            return c.split(":", 1)[-1]
    kept = [c for c in cells if not re.match(r"(limit|mrl|max|specification|requirement|standard|parameter)", c, re.I)]
    text = "; ".join(kept)
    return test.split(text, maxsplit=1)[-1]


def _value(doc, line, outlier):
    return Value(doc_type=doc.doc_type, doc_name=DOC_TYPES[doc.doc_type], filename=doc.filename, raw=line,
                 display=line, evidence=line, verified=True, outlier=outlier)


def _mg_per_kg(line: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mg/kg|ppm|µg/kg|ug/kg|ppb)", line, re.I)
    if not m:
        return None
    v = float(m.group(1))
    return v / 1000 if m.group(2).lower() in ("µg/kg", "ug/kg", "ppb") else v


def check(docs: list[ParsedDocument], product: str, destination: str) -> list[Check]:
    certs = [d for d in docs if d.doc_type == "health_certificate"]
    out = []
    for doc in certs:
        for line in _lines(doc, ANTIBIOTICS):
            # The part after the test name is the result, e.g. "Nitrofurans (AOZ): Detected, 1.6 µg/kg".
            result = _result_part(line, ANTIBIOTICS)
            if NEGATIVE.search(result):
                out.append(Check(id=f"lab:antibiotic:{len(out)}", category="lab results", title="Banned antibiotics not detected",
                                 status="pass", message=f"{DOC_TYPES[doc.doc_type]}: {line}", values=[_value(doc, line, False)]))
            elif POSITIVE.search(result) or _mg_per_kg(result):
                out.append(Check(id=f"lab:antibiotic:{len(out)}", category="lab results",
                                 title="Banned antibiotic residue detected", status="error", field="lab",
                                 message=f"The certificate reports a banned antibiotic: \"{line}\". Chloramphenicol and "
                                         "nitrofurans are banned in Indian aquaculture and are the main reason shrimp "
                                         "consignments are rejected in the EU, US and Japan.",
                                 suggestion="Do not ship this lot. Hold it, trace the farm, and re-test.",
                                 values=[_value(doc, line, True)]))
        for line in _lines(doc, ETO):
            result = _result_part(line, ETO)
            v = _mg_per_kg(result)
            if NEGATIVE.search(result) or (v is not None and v <= EU_ETO_LIMIT):
                out.append(Check(id=f"lab:eto:{len(out)}", category="lab results", title="Ethylene oxide within the EU limit",
                                 status="pass", message=f"{DOC_TYPES[doc.doc_type]}: {line}", values=[_value(doc, line, False)]))
            elif v is not None:
                out.append(Check(id=f"lab:eto:{len(out)}", category="lab results", field="lab",
                                 title="Ethylene oxide above the EU limit", status="error" if destination == "eu" else "warning",
                                 message=f"The certificate reports ethylene oxide at {v:g} mg/kg; the EU limit is "
                                         f"{EU_ETO_LIMIT} mg/kg. \"{line}\"",
                                 suggestion="Do not ship this lot to the EU; re-test or divert it.",
                                 values=[_value(doc, line, True)]))
    return out


def readiness_items(docs: list[ParsedDocument], product: str, destination: str) -> list[tuple[str, str, str, str]]:
    """(group, item, status, detail) for tests the destination expects but no certificate shows."""
    certs = [d for d in docs if d.doc_type == "health_certificate"]
    text = "\n".join(d.text or "" for d in certs)
    items = []
    if product == "seafood":
        found = bool(ANTIBIOTICS.search(text))
        items.append(("Lab results", "Antibiotic residue test (chloramphenicol, nitrofurans)", "ok" if found else "check",
                      "A result is shown on the certificate." if found else
                      "No antibiotic residue result found on the certificates. Banned antibiotics are the main cause "
                      "of shrimp rejections abroad; keep the lab report for this lot ready."))
    if product == "spices":
        found = bool(ETO.search(text))
        items.append(("Lab results", "Ethylene oxide test", "ok" if found else ("missing" if destination == "eu" else "check"),
                      "A result is shown on the certificate." if found else
                      "No ethylene oxide result found. Testing is mandatory for spices exported to the EU (Spices Board)."))
    return items
