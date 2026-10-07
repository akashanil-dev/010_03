"""Assemble the shipment report: verdict, checks and the Shipment Truth Matrix."""

from . import readiness, rules
from .schemas import DOC_TYPES, FIELDS, HIERARCHY, OWNERS, ParsedDocument

MATRIX_FIELDS = ["cartons", "net_weight", "gross_weight", "hs_code", "exporter_name", "consignee_name",
                 "port_of_loading", "port_of_discharge", "incoterms", "fob_value", "invoice_ref", "po_ref",
                 "container_no", "description", "doc_date"]


def build(docs: list[ParsedDocument], failed: list[tuple[str, str]] = ()) -> dict:
    checks = rules.run_all(docs)
    for name, err in failed:
        reason = ("the AI model is not running or not reachable" if "connect" in err.lower() or "refused" in err.lower()
                  else err[:160])
        checks.insert(0, {"id": f"intake:read_failed:{name}", "category": "compliance", "status": "error",
                          "title": "A file could not be read", "field": None, "values": [], "owners": [],
                          "message": f"{name} could not be read: {reason}. It is missing from every check, so the "
                                     "result below is incomplete.",
                          "suggestion": "Fix the cause (for example start Ollama) and run the check again."})
    for c in checks:
        blamed = sorted({v["doc_type"] for v in c.get("values", []) if v.get("outlier")})
        c["owners"] = [OWNERS[t] for t in blamed] or (["Export documentation"] if c["status"] in ("error", "warning") else [])
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

    column_order = list(DOC_TYPES)   # PO, invoice, packing list, shipping bill, certificate, origin
    known = sorted([d for d in docs if d.doc_type and d.doc_type != "letter_of_credit"],
                   key=lambda d: (HIERARCHY[d.doc_type], column_order.index(d.doc_type)))
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
        "readiness": readiness.build(docs),
        "coverage": coverage(docs),
    }


def final_verdict(report: dict, reviews: dict) -> dict:
    """The verdict after human review: overridden errors stop blocking; warnings need a decision.

    Same rule as the page uses, so the shipment page and the dashboard always agree.
    """
    flags = [c for c in report["checks"] if c["status"] in ("error", "warning")]
    overridden = [c for c in flags if reviews.get(c["id"], {}).get("decision") == "overridden"]
    open_errors = [c for c in flags if c["status"] == "error" and c not in overridden]
    open_warnings = [c for c in flags if c["status"] == "warning" and c["id"] not in reviews]
    verdict = "blocked" if open_errors else "review" if open_warnings else "ready"
    return {"verdict": verdict, "open_errors": len(open_errors), "open_warnings": len(open_warnings),
            "overridden_errors": sum(c["status"] == "error" for c in overridden),
            "overridden_warnings": sum(c["status"] == "warning" for c in overridden),
            "reviewed": sum(c["id"] in reviews for c in flags), "flags": len(flags)}


def coverage(docs: list[ParsedDocument]) -> list[dict]:
    """Which expected document types are present: required ones block filing, the others are expected."""
    present = {d.doc_type for d in docs if d.doc_type}
    order = ["purchase_order", "commercial_invoice", "packing_list", "shipping_bill", "health_certificate",
             "certificate_of_origin"]
    out = [{"doc_type": t, "doc_name": DOC_TYPES[t], "present": t in present, "required": t in rules.REQUIRED}
           for t in order]
    if "letter_of_credit" in present:
        out.append({"doc_type": "letter_of_credit", "doc_name": DOC_TYPES["letter_of_credit"], "present": True,
                    "required": False})
    return out


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
