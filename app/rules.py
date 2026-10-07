"""The rule engine: deterministic checks over the extracted documents.

Three kinds of checks:
  cross-document  the same fact must agree on every document that carries it
  arithmetic      numbers inside one document must add up
  compliance      required documents, LUT, date order

When documents disagree, the document hierarchy (PO -> invoice -> packing list
-> shipping bill / certificates) plus a majority vote decides which value is the
reference and which document is the likely outlier.
"""

import re
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field

from . import normalize as N
from .schemas import DOC_TYPES, FIELDS, HIERARCHY, ParsedDocument

STOPWORDS = {"and", "the", "per", "for", "with", "size", "x", "kg", "of", "in"}


@dataclass
class Value:
    doc_type: str
    doc_name: str
    filename: str
    raw: str | None
    display: str | None
    evidence: str | None
    verified: bool
    outlier: bool = False


@dataclass
class Check:
    id: str
    category: str          # cross-document | arithmetic | compliance
    title: str
    status: str            # pass | error | warning | skipped
    message: str
    field: str | None = None
    suggestion: str | None = None
    values: list[Value] = dc_field(default_factory=list)


# field -> (normaliser, comparer, display formatter, severity when they disagree)
def _eq(a, b):
    return a == b


def _num_eq(a, b):
    return abs(a - b) <= max(0.5, 0.0005 * max(abs(a), abs(b)))


def _fmt_num(v):
    return f"{v:,.2f}".rstrip("0").rstrip(".") if v is not None else None


def _fmt_kg(v):
    return f"{_fmt_num(v)} kg" if v is not None else None


CROSS_FIELDS = {
    "cartons": (lambda d, f: N.count(f("cartons")), _eq, lambda v: f"{v:,}", "error"),
    "net_weight": (lambda d, f: N.weight_kg(f("net_weight"), f("net_weight_unit")), _num_eq, _fmt_kg, "error"),
    "gross_weight": (lambda d, f: N.weight_kg(f("gross_weight"), f("gross_weight_unit")), _num_eq, _fmt_kg, "error"),
    "hs_code": (lambda d, f: N.hs_code(f("hs_code")), N.hs_equal, str, "error"),
    "exporter_name": (lambda d, f: N.company(f("exporter_name")), N.company_equal, str, "error"),
    "consignee_name": (lambda d, f: N.company(f("consignee_name")), N.company_equal, str, "error"),
    "iec": (lambda d, f: N.iec(f("iec")), _eq, str, "error"),
    "gstin": (lambda d, f: N.gstin(f("gstin")), _eq, str, "error"),
    "port_of_loading": (lambda d, f: N.port(f("port_of_loading")), _eq, str, "error"),
    "port_of_discharge": (lambda d, f: N.port(f("port_of_discharge")), _eq, str, "error"),
    "incoterms": (lambda d, f: N.incoterm(f("incoterms")), _eq, str, "error"),
    "container_no": (lambda d, f: N.container(f("container_no")), _eq, str, "error"),
    "fob_value": (lambda d, f: N.number(f("fob_value")), _num_eq, _fmt_num, "error"),
    # References: the invoice's own number vs the invoice number quoted elsewhere, same for the PO.
    "invoice_ref": (lambda d, f: N.reference(f("doc_number") if d == "commercial_invoice" else f("invoice_number")),
                    _eq, str, "error"),
    "po_ref": (lambda d, f: N.reference(f("doc_number") if d == "purchase_order" else f("po_number")),
               _eq, str, "error"),
}
CROSS_LABELS = {"invoice_ref": "Invoice number", "po_ref": "PO number"}
CROSS_SOURCE_FIELD = {"invoice_ref": "invoice_number", "po_ref": "po_number"}


def _getter(doc: ParsedDocument):
    def get(key):
        f = doc.fields.get(key)
        return f.raw if f else None
    return get


def _value(doc: ParsedDocument, key: str, display) -> Value:
    src_key = key
    if key == "invoice_ref":
        src_key = "doc_number" if doc.doc_type == "commercial_invoice" else "invoice_number"
    elif key == "po_ref":
        src_key = "doc_number" if doc.doc_type == "purchase_order" else "po_number"
    f = doc.fields.get(src_key)
    return Value(doc_type=doc.doc_type, doc_name=DOC_TYPES[doc.doc_type], filename=doc.filename,
                 raw=f.raw if f else None, display=display, evidence=f.evidence if f else None,
                 verified=bool(f and f.verified))


def _label(key: str) -> str:
    return CROSS_LABELS.get(key) or FIELDS[key][0]


def _names(values: list[Value]) -> str:
    names = [v.doc_name for v in values]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def cross_document(docs: list[ParsedDocument]) -> list[Check]:
    checks = []
    for key, (norm, same, fmt, severity) in CROSS_FIELDS.items():
        entries = []
        for d in docs:
            v = norm(d.doc_type, _getter(d))
            if v is not None:
                entries.append((d, v))
        label = _label(key)
        if len(entries) < 2:
            checks.append(Check(id=f"cross:{key}", category="cross-document", title=f"{label} matches", field=key,
                                status="skipped", message=f"{label} appears on fewer than two documents."))
            continue

        # Group equal values together.
        groups: list[list] = []
        for d, v in entries:
            for g in groups:
                if same(g[0][1], v):
                    g.append((d, v))
                    break
            else:
                groups.append([(d, v)])

        values = [_value(d, key, fmt(v)) for d, v in entries]
        if len(groups) == 1:
            checks.append(Check(id=f"cross:{key}", category="cross-document", title=f"{label} matches", field=key,
                                status="pass", values=values,
                                message=f"{label} agrees on {len(entries)} documents."))
            continue

        # Reference = biggest group; on a tie, values verified in the source text beat unverified ones,
        # then the group holding the highest-ranked document wins.
        def verified(g):
            return sum(_value(d, key, None).verified for d, _ in g)
        groups.sort(key=lambda g: (-len(g), -verified(g), min(HIERARCHY[d.doc_type] for d, _ in g)))
        ref, outliers = groups[0], [x for g in groups[1:] for x in g]
        outlier_types = {d.doc_type for d, _ in outliers}
        for v in values:
            v.outlier = v.doc_type in outlier_types
        ref_vals = [v for v in values if not v.outlier]
        out_vals = [v for v in values if v.outlier]
        ref_display = fmt(ref[0][1])
        says = "; ".join(f"{v.doc_name} says {v.display}" for v in out_vals)
        if len(ref) > 1:
            message = f"{says}, but {_names(ref_vals)} say {ref_display}."
        else:
            message = f"{says}, but {_names(ref_vals)} says {ref_display}."
        suggestion = (f"{_names(out_vals)} is the likely outlier. Check it against the source and correct it "
                      f"to {ref_display}, or confirm the other documents are wrong.")
        checks.append(Check(id=f"cross:{key}", category="cross-document", title=f"{label} mismatch", field=key,
                            status=severity, message=message, suggestion=suggestion, values=values))
    checks.append(description_check(docs))
    _explain_swapped_references(checks)
    return checks


def _explain_swapped_references(checks: list[Check]) -> None:
    """If a document's invoice number equals everyone else's PO number and vice versa, say they look swapped."""
    by_id = {c.id: c for c in checks}
    inv, po = by_id.get("cross:invoice_ref"), by_id.get("cross:po_ref")
    if not inv or not po or inv.status == "pass" or po.status == "pass":
        return
    ref_inv = next((v.display for v in inv.values if not v.outlier), None)
    ref_po = next((v.display for v in po.values if not v.outlier), None)
    for v in inv.values:
        if not v.outlier:
            continue
        w = next((x for x in po.values if x.doc_type == v.doc_type and x.outlier), None)
        if w and v.display == ref_po and w.display == ref_inv:
            note = (f"On the {v.doc_name} the invoice number and PO number look swapped: its invoice-number field "
                    f"holds the PO number ({ref_po}) and its PO field holds the invoice number ({ref_inv}).")
            for c in (inv, po):
                c.message = note
                c.suggestion = f"Swap the two references on the {v.doc_name}."


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9/\-]+", text.lower()) if len(t) > 1 and t not in STOPWORDS}


def description_check(docs: list[ParsedDocument]) -> Check:
    """Fuzzy check of goods descriptions against the most authoritative one. Only ever a warning."""
    with_desc = [d for d in docs if d.fields.get("description") and d.fields["description"].raw]
    if len(with_desc) < 2:
        return Check(id="cross:description", category="cross-document", title="Goods description consistent",
                     field="description", status="skipped", message="Fewer than two documents describe the goods.")
    with_desc.sort(key=lambda d: HIERARCHY[d.doc_type])
    ref_doc = with_desc[0]
    ref_tokens = _tokens(ref_doc.fields["description"].raw)
    values, vague = [], []
    for d in with_desc:
        raw = d.fields["description"].raw
        cover = len(_tokens(raw) & ref_tokens) / max(1, len(ref_tokens))
        v = _value(d, "description", raw)
        if d is not ref_doc and cover < 0.4:
            v.outlier = True
            vague.append((v, cover))
        values.append(v)
    if not vague:
        return Check(id="cross:description", category="cross-document", title="Goods description consistent",
                     field="description", status="pass", values=values,
                     message=f"Descriptions on {len(values)} documents match the {DOC_TYPES[ref_doc.doc_type]}.")
    parts = [f"{v.doc_name} only says \"{v.raw}\" ({cover:.0%} of the key terms)" for v, cover in vague]
    return Check(id="cross:description", category="cross-document", title="Goods description too vague or different",
                 field="description", status="warning", values=values,
                 message="; ".join(parts) + f". The {DOC_TYPES[ref_doc.doc_type]} describes \"{ref_doc.fields['description'].raw}\".",
                 suggestion="A person should decide whether this is acceptable. Banks and customs can query vague descriptions.")


def _by_type(docs, doc_type):
    return next((d for d in docs if d.doc_type == doc_type), None)


def arithmetic(docs: list[ParsedDocument]) -> list[Check]:
    checks = []
    inv = _by_type(docs, "commercial_invoice")
    if inv:
        g = _getter(inv)
        qty, rate, total = N.weight_kg(g("net_weight"), g("net_weight_unit")), N.number(g("unit_price")), N.number(g("total_amount"))
        freight, fob = N.number(g("freight")), N.number(g("fob_value"))
        values = [_value(inv, k, g(k)) for k in ("net_weight", "unit_price", "total_amount", "freight", "fob_value")]
        hs_codes = set(re.findall(r"\b\d{8}\b", inv.text or ""))
        if len(hs_codes) > 1:
            checks.append(Check(id="math:invoice", category="arithmetic", title="Invoice totals add up",
                                status="skipped", message=f"The invoice has several product lines ({len(hs_codes)} HS codes); "
                                "line-by-line totals are not recomputed yet."))
        elif None in (qty, rate, total):
            checks.append(Check(id="math:invoice", category="arithmetic", title="Invoice totals add up",
                                status="skipped", message="Quantity, rate or total could not be read."))
        else:
            expected = qty * rate
            problems = []
            if not _num_eq(expected, total):
                problems.append(f"{_fmt_num(qty)} kg × {_fmt_num(rate)} = {_fmt_num(expected)}, but the invoice total is {_fmt_num(total)}")
            if freight is not None and fob is not None and not _num_eq(total - freight, fob):
                problems.append(f"total {_fmt_num(total)} − freight {_fmt_num(freight)} = {_fmt_num(total - freight)}, "
                                f"but the FOB value is {_fmt_num(fob)}")
            if problems:
                for v, k in zip(values, ("net_weight", "unit_price", "total_amount", "freight", "fob_value")):
                    v.outlier = k in ("total_amount", "fob_value")
                checks.append(Check(id="math:invoice", category="arithmetic", title="Invoice totals don't add up",
                                    field="total_amount", status="error", values=values,
                                    message="; ".join(problems) + ".",
                                    suggestion="Recalculate the invoice amounts before the shipping bill is filed."))
            else:
                checks.append(Check(id="math:invoice", category="arithmetic", title="Invoice totals add up",
                                    status="pass", values=values,
                                    message=f"{_fmt_num(qty)} kg × {_fmt_num(rate)} = {_fmt_num(total)}"
                                            + (f"; minus freight = FOB {_fmt_num(fob)}." if fob is not None else ".")))

    pl = _by_type(docs, "packing_list")
    if pl:
        g = _getter(pl)
        cartons = N.count(g("cartons"))
        keys = ("cartons", "net_per_carton", "net_weight", "gross_per_carton", "gross_weight")
        values = [_value(pl, k, g(k)) for k in keys]
        ok, problems = [], []
        for kind in ("net", "gross"):
            per, total = N.number(g(f"{kind}_per_carton")), N.weight_kg(g(f"{kind}_weight"), g(f"{kind}_weight_unit"))
            if None in (cartons, per, total):
                continue
            line = f"{cartons:,} cartons × {_fmt_num(per)} kg = {_fmt_kg(cartons * per)}"
            if _num_eq(cartons * per, total):
                ok.append(line)
            else:
                problems.append(f"{line}, but the total {kind} weight is {_fmt_kg(total)}")
        if problems:
            for v in values:
                v.outlier = True
            checks.append(Check(id="math:packing", category="arithmetic", title="Packing list weights don't add up",
                                field="net_weight", status="error", values=values,
                                message="; ".join(problems) + ".",
                                suggestion="Either the carton count or the weights are wrong. Recount the cartons."))
        elif ok:
            checks.append(Check(id="math:packing", category="arithmetic", title="Packing list weights add up",
                                status="pass", values=values, message="; ".join(ok) + "."))
        else:
            checks.append(Check(id="math:packing", category="arithmetic", title="Packing list weights add up",
                                status="skipped", message="Cartons or weights per carton could not be read."))
    return checks


REQUIRED = ["commercial_invoice", "packing_list", "shipping_bill"]
RECOMMENDED = ["purchase_order", "health_certificate", "certificate_of_origin"]


def compliance(docs: list[ParsedDocument]) -> list[Check]:
    checks = []
    present = {d.doc_type for d in docs}
    missing_req = [DOC_TYPES[t] for t in REQUIRED if t not in present]
    missing_rec = [DOC_TYPES[t] for t in RECOMMENDED if t not in present]
    if missing_req:
        checks.append(Check(id="comp:required_docs", category="compliance", title="Required documents missing",
                            status="error", message="Missing: " + ", ".join(missing_req) + ".",
                            suggestion="Upload the missing documents."))
    else:
        checks.append(Check(id="comp:required_docs", category="compliance", title="Required documents present",
                            status="pass", message="Commercial invoice, packing list and shipping bill are present."))
    if missing_rec:
        checks.append(Check(id="comp:recommended_docs", category="compliance", title="Supporting documents missing",
                            status="warning", message="Not uploaded: " + ", ".join(missing_rec) + ".",
                            suggestion="Seafood to the EU needs an EIC health certificate; buyers often ask for a certificate of origin."))
    else:
        checks.append(Check(id="comp:recommended_docs", category="compliance", title="Supporting documents present",
                            status="pass", message="Purchase order, health certificate and certificate of origin are present."))

    # LUT: if the shipping bill declares export under LUT, the invoice must carry the LUT reference.
    inv, sb = _by_type(docs, "commercial_invoice"), _by_type(docs, "shipping_bill")
    if inv and sb:
        sb_g, inv_g = _getter(sb), _getter(inv)
        sb_lut = "LUT" in (sb_g("igst_status") or "").upper() or N.lut_arn(sb_g("lut_arn"))
        inv_arn, sb_arn = N.lut_arn(inv_g("lut_arn")), N.lut_arn(sb_g("lut_arn"))
        values = [_value(inv, "lut_arn", inv_arn), _value(sb, "lut_arn", sb_arn)]
        if not sb_lut:
            checks.append(Check(id="comp:lut", category="compliance", title="LUT declaration", status="skipped",
                                message="The shipping bill does not declare export under LUT."))
        elif not inv_arn:
            values[0].outlier = True
            checks.append(Check(id="comp:lut", category="compliance", title="LUT reference missing on invoice",
                                field="lut_arn", status="error", values=values,
                                message="The shipping bill declares export under LUT (IGST not paid), but the commercial "
                                        "invoice carries no LUT ARN.",
                                suggestion="Add the line 'Supply meant for export under LUT without payment of IGST' "
                                           "with the LUT ARN to the invoice, or customs may raise an IGST demand."))
        elif sb_arn and inv_arn != sb_arn:
            checks.append(Check(id="comp:lut", category="compliance", title="LUT reference differs", field="lut_arn",
                                status="error", values=values,
                                message=f"Invoice LUT ARN {inv_arn} differs from shipping bill LUT ARN {sb_arn}.",
                                suggestion="Use the LUT ARN valid for this financial year on both documents."))
        else:
            checks.append(Check(id="comp:lut", category="compliance", title="LUT reference present", status="pass",
                                values=values, message=f"Invoice carries LUT ARN {inv_arn}."))

    # Date order: PO <= invoice <= shipping bill, invoice <= certificate of origin.
    dates = {d.doc_type: N.parse_date(_getter(d)("doc_date")) for d in docs}
    for earlier, later in [("purchase_order", "commercial_invoice"), ("commercial_invoice", "shipping_bill"),
                           ("commercial_invoice", "certificate_of_origin")]:
        if earlier not in present or later not in present:
            continue
        a, b = dates.get(earlier), dates.get(later)
        cid = f"comp:date:{earlier}:{later}"
        e_doc, l_doc = _by_type(docs, earlier), _by_type(docs, later)
        values = [_value(e_doc, "doc_date", str(a) if a else None), _value(l_doc, "doc_date", str(b) if b else None)]
        title = f"{DOC_TYPES[earlier]} dated before {DOC_TYPES[later]}"
        if not a or not b:
            checks.append(Check(id=cid, category="compliance", title=title, status="skipped",
                                message="A date could not be read."))
        elif a <= b:
            checks.append(Check(id=cid, category="compliance", title=title, status="pass", values=values,
                                message=f"{a:%d %b %Y} → {b:%d %b %Y}."))
        else:
            values[1].outlier = True
            checks.append(Check(id=cid, category="compliance", title=f"{DOC_TYPES[later]} dated before {DOC_TYPES[earlier]}",
                                field="doc_date", status="error", values=values,
                                message=f"The {DOC_TYPES[later]} is dated {b:%d %b %Y}, before the "
                                        f"{DOC_TYPES[earlier]} it depends on ({a:%d %b %Y}).",
                                suggestion=f"Check the {DOC_TYPES[later]} date."))
    return checks


def first_of_each_type(docs: list[ParsedDocument]) -> list[ParsedDocument]:
    """Keep the first document of each type; a second invoice would otherwise be mixed into the comparison."""
    seen, kept = set(), []
    for d in docs:
        if d.doc_type not in seen:
            seen.add(d.doc_type)
            kept.append(d)
    return kept


def intake_checks(docs: list[ParsedDocument]) -> list[Check]:
    """Files that are not export documents, and document types uploaded more than once."""
    checks = []
    from .parsing import other_document

    unknown = [d for d in docs if not d.doc_type]
    known_other = [(d, other_document(d.text)) for d in unknown]
    for d, name in known_other:
        if name:
            checks.append(Check(
                id=f"intake:unsupported:{d.filename}", category="compliance", status="warning",
                title=f"{name} not checked yet",
                message=f"{d.filename} looks like a {name}. TallyTime does not check this document type yet, so it was "
                        "not compared with the others.",
                suggestion=f"Check the {name.lower()} against the invoice and packing list by hand."))
    unknown = [d for d, name in known_other if not name]
    if unknown:
        names = ", ".join(d.filename for d in unknown)
        checks.append(Check(
            id="intake:unrecognised", category="compliance", status="warning",
            title="File not recognised as an export document",
            message=f"{names} {'does' if len(unknown) == 1 else 'do'} not look like any export document TallyTime checks "
                    "(no purchase order, invoice, packing list, shipping bill, certificate or letter of credit title "
                    "found). It was not checked and was not sent to the AI model.",
            suggestion="Remove unrelated files, or make sure the document's title is visible on its first page."))
    by_type: dict[str, list[str]] = {}
    for d in docs:
        if d.doc_type:
            by_type.setdefault(d.doc_type, []).append(d.filename)
    for t, files in by_type.items():
        if len(files) > 1:
            checks.append(Check(
                id=f"intake:duplicate:{t}", category="compliance", status="warning",
                title=f"More than one {DOC_TYPES[t]} uploaded",
                message=f"{len(files)} files look like a {DOC_TYPES[t]}: {', '.join(files)}. Only the first, "
                        f"{files[0]}, was compared.",
                suggestion="Upload one document of each type per shipment; remove old or duplicate versions."))
    if not checks:
        checks.append(Check(id="intake:files", category="compliance", status="pass", title="All files recognised",
                            message=f"Each of the {len(docs)} files was recognised as a different export document."))
    return checks


def run_all(docs: list[ParsedDocument]) -> list[dict]:
    from . import labtests, lc, readiness

    intake = intake_checks(docs)
    docs = first_of_each_type([d for d in docs if d.doc_type])
    shipment = [d for d in docs if d.doc_type != "letter_of_credit"]   # the LC is checked against, not compared with
    product, _ = readiness.detect_product(shipment)
    destination, _ = readiness.detect_destination(shipment)
    checks = (intake + cross_document(shipment) + arithmetic(shipment) + compliance(shipment) + lc.check(docs)
              + labtests.check(shipment, product, destination))
    order = {"error": 0, "warning": 1, "pass": 2, "skipped": 3}
    checks.sort(key=lambda c: order[c.status])
    return [asdict(c) for c in checks]
