"""Assemble the shipment report: verdict, checks and the Shipment Truth Matrix."""

from . import rules
from .schemas import DOC_TYPES, FIELDS, HIERARCHY, ParsedDocument

MATRIX_FIELDS = ["cartons", "net_weight", "gross_weight", "hs_code", "exporter_name", "consignee_name",
                 "port_of_loading", "port_of_discharge", "incoterms", "fob_value", "invoice_ref", "po_ref",
                 "container_no", "description", "doc_date"]


def build(docs: list[ParsedDocument]) -> dict:
    checks = rules.run_all(docs)
    errors = [c for c in checks if c["status"] == "error"]
    warnings = [c for c in checks if c["status"] == "warning"]
    passed = [c for c in checks if c["status"] == "pass"]
    evaluated = [c for c in checks if c["status"] != "skipped"]

    if errors:
        verdict = "blocked"
    elif warnings:
        verdict = "review"
    else:
        verdict = "ready"

    known = sorted([d for d in docs if d.doc_type], key=lambda d: HIERARCHY[d.doc_type])
    return {
        "verdict": verdict,
        "counts": {"errors": len(errors), "warnings": len(warnings), "passed": len(passed),
                   "evaluated": len(evaluated)},
        "checks": checks,
        "documents": [{
            "filename": d.filename, "doc_type": d.doc_type,
            "doc_name": DOC_TYPES.get(d.doc_type, "Unrecognised document"),
            "ocr_used": d.ocr_used, "seconds": d.seconds, "source_format": d.source_format,
            "unverified": [FIELDS[k][0] for k, f in d.fields.items() if f.raw and not f.verified],
            "fields": {k: {"label": FIELDS[k][0], "raw": f.raw, "evidence": f.evidence, "verified": f.verified}
                       for k, f in d.fields.items()},
        } for d in docs],
        "matrix": matrix(known, checks),
    }


def matrix(docs: list[ParsedDocument], checks: list[dict]) -> dict:
    """Rows = fields, columns = documents. Each cell: value, status, evidence."""
    by_field = {}
    for c in checks:
        if c.get("field") and c["category"] == "cross-document":
            by_field[c["field"]] = c
    rows = []
    for key in MATRIX_FIELDS:
        check = by_field.get(key)
        cells = {}
        for v in (check or {}).get("values", []):
            cells[v["doc_type"]] = {
                "raw": v["raw"], "display": v["display"], "evidence": v["evidence"], "verified": v["verified"],
                "status": "mismatch" if v["outlier"] else ("ok" if check["status"] == "pass" or not v["outlier"] else "ok"),
            }
        if key == "doc_date":
            for d in docs:
                f = d.fields.get("doc_date")
                if f and f.raw:
                    cells[d.doc_type] = {"raw": f.raw, "display": f.raw, "evidence": f.evidence,
                                         "verified": f.verified, "status": "info"}
            for c in checks:
                if c["id"].startswith("comp:date") and c["status"] == "error":
                    for v in c["values"]:
                        if v["outlier"] and v["doc_type"] in cells:
                            cells[v["doc_type"]]["status"] = "mismatch"
        if not cells:
            continue
        label = rules.CROSS_LABELS.get(key) or FIELDS[key][0]
        rows.append({"key": key, "label": label, "status": check["status"] if check else "info",
                     "check_id": check["id"] if check else None, "cells": cells})
    return {"columns": [{"doc_type": d.doc_type, "doc_name": DOC_TYPES[d.doc_type], "filename": d.filename}
                        for d in docs],
            "rows": rows}
