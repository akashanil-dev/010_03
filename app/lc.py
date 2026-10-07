"""Letter of credit compliance: check the document set against the LC's terms before it goes to the bank.

Follows the logic a bank applies under ICC UCP 600: the invoice amount must not
exceed the credit (plus any stated tolerance), shipment must not be later than
the latest shipment date, the invoice description must correspond with the
credit, ports and terms must match, the required documents must be present, and
documents must be presented within the presentation period and before expiry.
"""

import re
from datetime import date, timedelta

from rapidfuzz import fuzz

from . import normalize as N
from .rules import Check, Value, _by_type, _getter, _tokens
from .schemas import DOC_TYPES, ParsedDocument

TODAY = date.today

# Words in LC field 46A that name a document type TallyTime reads.
REQUIRED_WORDS = {
    "commercial_invoice": ["INVOICE"],
    "packing_list": ["PACKING LIST", "PACKING"],
    "certificate_of_origin": ["CERTIFICATE OF ORIGIN", "ORIGIN"],
    "health_certificate": ["HEALTH CERTIFICATE", "SANITARY", "QUALITY", "INSPECTION", "ANALYSIS"],
}
NOT_READ = {r"BILLS? OF LADING|\bB/L\b": "Bill of lading", r"INSURANCE": "Insurance certificate",
            r"WEIGHT CERTIFICATE|CERTIFICATE OF WEIGHT": "Weight certificate"}


def _val(doc: ParsedDocument, key: str, display=None, outlier=False) -> Value:
    f = doc.fields.get(key)
    return Value(doc_type=doc.doc_type, doc_name=DOC_TYPES[doc.doc_type], filename=doc.filename,
                 raw=f.raw if f else None, display=display if display is not None else (f.raw if f else None),
                 evidence=f.evidence if f else None, verified=bool(f and f.verified), outlier=outlier)


def _tolerance(raw: str | None) -> float:
    """'05/05' or '+/- 5 PCT' -> 0.05. No tolerance stated -> 0."""
    nums = re.findall(r"\d+(?:\.\d+)?", raw or "")
    return float(nums[-1]) / 100 if nums else 0.0


def check(docs: list[ParsedDocument]) -> list[Check]:
    lc = _by_type(docs, "letter_of_credit")
    if not lc:
        return []
    L = _getter(lc)
    inv = _by_type(docs, "commercial_invoice")
    sb = _by_type(docs, "shipping_bill")
    out: list[Check] = []

    def add(cid, title, status, message, values=(), suggestion=None, field=None):
        out.append(Check(id=f"lc:{cid}", category="letter of credit", title=title, status=status, message=message,
                         values=list(values), suggestion=suggestion, field=field))

    # 1. Amount within the credit (+ tolerance).
    lc_amt, tol = N.number(L("total_amount")), _tolerance(L("amount_tolerance"))
    if inv and lc_amt is not None and N.number(_getter(inv)("total_amount")) is not None:
        inv_amt = N.number(_getter(inv)("total_amount"))
        limit = lc_amt * (1 + tol)
        values = [_val(lc, "total_amount"), _val(inv, "total_amount", outlier=inv_amt > limit + 0.5)]
        if inv_amt > limit + 0.5:
            add("amount", "Invoice exceeds the credit amount", "error",
                f"Invoice total {inv_amt:,.2f} exceeds the LC amount {lc_amt:,.2f}"
                + (f" plus {tol:.0%} tolerance ({limit:,.2f})." if tol else "."),
                values, "Ask the buyer for an LC amendment or reduce the invoice; banks refuse an over-drawn invoice.")
        else:
            add("amount", "Invoice within the credit amount", "pass",
                f"Invoice total {inv_amt:,.2f} is within the LC amount {lc_amt:,.2f}"
                + (f" (tolerance {tol:.0%})." if tol else "."), values)

    # 2. Currency.
    if inv and L("currency") and _getter(inv)("currency"):
        same = N.currency(L("currency")) == N.currency(_getter(inv)("currency"))
        add("currency", "Invoice currency matches the LC" if same else "Invoice currency differs from the LC",
            "pass" if same else "error",
            f"LC currency {L('currency')}, invoice currency {_getter(inv)('currency')}.",
            [_val(lc, "currency"), _val(inv, "currency", outlier=not same)])

    # 3. Shipment no later than the latest shipment date (shipping bill date used as the export date).
    latest, ship = N.parse_date(L("latest_shipment_date")), N.parse_date(_getter(sb)("doc_date")) if sb else None
    if latest and ship:
        late = ship > latest
        values = [_val(lc, "latest_shipment_date"), _val(sb, "doc_date", outlier=late)]
        add("shipment_date", "Shipment after the LC's latest shipment date" if late else "Shipment within the LC's latest shipment date",
            "error" if late else "pass",
            f"Shipping bill dated {ship:%d %b %Y}; the LC requires shipment by {latest:%d %b %Y}."
            + (" Banks treat late shipment as a discrepancy." if late else ""),
            values, "Ask the buyer to amend the latest shipment date before presenting documents." if late else None,
            field="doc_date")

    # 4. Expiry and presentation period (UCP 600: 21 days after shipment if not stated, and never after expiry).
    expiry = N.parse_date(L("expiry_date"))
    if ship and expiry:
        days = N.count(L("presentation_days")) or 21
        deadline = min(ship + timedelta(days=days), expiry)
        today = TODAY()
        if deadline < today:
            add("presentation", "Presentation deadline has passed", "error",
                f"Documents had to reach the bank by {deadline:%d %b %Y} ({days} days after shipment, LC expiry "
                f"{expiry:%d %b %Y}).", [_val(lc, "expiry_date")], "Contact the buyer and bank about an extension or amendment.")
        else:
            add("presentation", "Present documents to the bank in time", "pass",
                f"Present by {deadline:%d %b %Y}: {days} days after shipment ({ship:%d %b %Y}) and before LC expiry "
                f"({expiry:%d %b %Y}). {(deadline - today).days} days left.", [_val(lc, "expiry_date")])

    # 5. Ports and Incoterms.
    for key, label, norm in (("port_of_loading", "Port of loading", N.port), ("port_of_discharge", "Port of discharge", N.port),
                             ("incoterms", "Incoterms", N.incoterm)):
        lc_v = norm(L(key))
        if not lc_v:
            continue
        values, bad = [_val(lc, key, lc_v)], []
        for d in (x for x in (inv, sb) if x):
            v = norm(_getter(d)(key))
            if v is None:
                continue
            values.append(_val(d, key, v, outlier=v != lc_v))
            if v != lc_v:
                bad.append(f"{DOC_TYPES[d.doc_type]} says {v}")
        if len(values) < 2:
            continue
        add(key, f"{label} {'differs from' if bad else 'matches'} the LC", "error" if bad else "pass",
            ("; ".join(bad) + f", but the LC requires {lc_v}.") if bad else f"{label} {lc_v} as required by the LC.",
            values, "Correct the document or ask for an LC amendment." if bad else None, field=key)

    # 6. Invoice description must correspond with the LC (UCP 600 art. 18(c)).
    if inv and L("description") and _getter(inv)("description"):
        lc_t, inv_t = _tokens(L("description")), _tokens(_getter(inv)("description"))
        missing = sorted(lc_t - inv_t)
        sizes_lc = set(re.findall(r"\b\d{1,3}/\d{1,3}\b", L("description")))
        sizes_inv = set(re.findall(r"\b\d{1,3}/\d{1,3}\b", _getter(inv)("description")))
        size_conflict = bool(sizes_lc and sizes_inv and not (sizes_lc & sizes_inv))
        score = fuzz.token_set_ratio(L("description"), _getter(inv)("description"))
        ok = not size_conflict and (score >= 85 or len(missing) <= 1)
        values = [_val(lc, "description"), _val(inv, "description", outlier=not ok)]
        if ok:
            add("description", "Invoice description corresponds with the LC", "pass",
                "The invoice describes the goods as the LC does.", values)
        else:
            detail = (f"size {', '.join(sorted(sizes_inv))} on the invoice vs {', '.join(sorted(sizes_lc))} in the LC"
                      if size_conflict else f"terms in the LC missing from the invoice: {', '.join(missing[:6])}")
            add("description", "Invoice description does not correspond with the LC", "error",
                f"Banks require the invoice description to correspond with the credit; {detail}.",
                values, "Align the invoice wording with the LC, or ask for an LC amendment if the goods differ.",
                field="description")

    # 7. Beneficiary and applicant.
    for lc_key, doc_key, label in (("beneficiary_name", "exporter_name", "Beneficiary"), ("applicant_name", "consignee_name", "Applicant")):
        a = N.company(L(lc_key))
        b = N.company(_getter(inv)(doc_key)) if inv else None
        if a and b:
            same = N.company_equal(a, b)
            add(lc_key, f"{label} {'matches' if same else 'differs from'} the invoice", "pass" if same else "warning",
                f"LC {label.lower()} {L(lc_key)}; invoice shows {_getter(inv)(doc_key)}.",
                [_val(lc, lc_key), _val(inv, doc_key, outlier=not same)])

    # 8. Documents required by the LC (field 46A).
    req = (L("documents_required") or "").upper()
    if req:
        present = {d.doc_type for d in docs}
        missing = [DOC_TYPES[t] for t, words in REQUIRED_WORDS.items() if any(w in req for w in words) and t not in present]
        not_read = [name for pattern, name in NOT_READ.items() if re.search(pattern, req)]
        if missing:
            add("documents", "Documents required by the LC are missing", "error",
                "The LC requires: " + ", ".join(missing) + ". They were not uploaded.", [_val(lc, "documents_required")],
                "Prepare and upload the missing documents before presentation.")
        else:
            add("documents", "Documents required by the LC are present", "pass",
                "Every document type TallyTime reads that the LC asks for is present.", [_val(lc, "documents_required")])
        if not_read:
            add("documents_unchecked", "LC documents TallyTime does not check", "warning",
                "The LC also requires: " + ", ".join(not_read) + ". TallyTime does not read these yet; check them by hand.",
                [_val(lc, "documents_required")], "Check these against the LC before presentation.")
    return out
