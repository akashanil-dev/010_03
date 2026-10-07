"""Export readiness checklist for one shipment, based on product and destination.

Only well-established requirements are stated as requirements. Anything that
depends on the buyer or the importing country is marked "check" so a person
confirms it, rather than the tool asserting a rule it cannot verify.
"""

import re

from . import normalize as N
from .schemas import ParsedDocument

EU_WORDS = ["NETHERLANDS", "ROTTERDAM", "BELGIUM", "ANTWERP", "GERMANY", "HAMBURG", "FRANCE", "LE HAVRE", "ITALY",
            "GENOA", "SPAIN", "VALENCIA", "PORTUGAL", "LISBON", "GREECE", "PIRAEUS", "POLAND", "GDANSK", "DENMARK",
            "IRELAND", "SWEDEN", "FINLAND", "AUSTRIA", "CROATIA", "SLOVENIA", "KOPER", "ESTONIA", "LATVIA",
            "LITHUANIA", "MALTA", "CYPRUS", "BULGARIA", "ROMANIA", "CZECH", "SLOVAKIA", "HUNGARY", "LUXEMBOURG"]
US_WORDS = ["UNITED STATES", "USA", "U.S.A", "NEW YORK", "LOS ANGELES", "LONG BEACH", "SAVANNAH", "HOUSTON",
            "NORFOLK", "OAKLAND", "SEATTLE", "MIAMI", "NEWARK"]

PRODUCTS = {"seafood": "Seafood (marine products)", "spices": "Spices", "rubber": "Natural rubber",
            "general": "General goods"}
DESTINATIONS = {"eu": "European Union", "us": "United States", "other": "Other / not detected"}


def _by_type(docs, t):
    return next((d for d in docs if d.doc_type == t), None)


def _raw(doc, key):
    f = doc.fields.get(key) if doc else None
    return f.raw if f else None


def detect_product(docs: list[ParsedDocument]) -> tuple[str, str]:
    for d in docs:
        hs = N.hs_code(_raw(d, "hs_code"))
        if not hs:
            continue
        if hs.startswith("03") or hs.startswith("1604") or hs.startswith("1605"):
            return "seafood", f"HS code {hs}"
        if hs.startswith("09"):
            return "spices", f"HS code {hs}"
        if hs.startswith("4001"):
            return "rubber", f"HS code {hs}"
        return "general", f"HS code {hs}"
    return "general", "no HS code found"


def detect_destination(docs: list[ParsedDocument]) -> tuple[str, str]:
    for key in ("port_of_discharge", "consignee_name"):
        for d in sorted(docs, key=lambda d: d.doc_type != "commercial_invoice"):
            raw = _raw(d, key)
            if not raw:
                continue
            up = raw.upper()
            if any(w in up for w in EU_WORDS):
                return "eu", raw
            if any(re.search(rf"\b{re.escape(w)}\b", up) for w in US_WORDS):
                return "us", raw
    return "other", "port of discharge not recognised"


def _financial_year(d):
    """Indian financial year (April to March) of a date, e.g. 2026-27."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def build(docs: list[ParsedDocument]) -> dict:
    docs = [d for d in docs if d.doc_type and d.doc_type != "letter_of_credit"]
    present = {d.doc_type for d in docs}
    inv, sb = _by_type(docs, "commercial_invoice"), _by_type(docs, "shipping_bill")
    product, product_basis = detect_product(docs)
    dest, dest_basis = detect_destination(docs)
    items = []

    def add(group, item, status, detail):
        items.append({"group": group, "item": item, "status": status, "detail": detail})

    # Core documents for any export from India.
    for t, name in (("commercial_invoice", "Commercial invoice"), ("packing_list", "Packing list"),
                    ("shipping_bill", "Shipping bill")):
        add("Core documents", name, "ok" if t in present else "missing",
            "Uploaded." if t in present else "Not uploaded. Needed for customs clearance.")
    add("Core documents", "Purchase order / contract", "ok" if "purchase_order" in present else "check",
        "Uploaded; used as the reference for what was ordered." if "purchase_order" in present
        else "Not uploaded. Without it Tally cannot check the invoice against the contract.")

    # Registrations.
    iec = N.iec(_raw(inv, "iec")) or N.iec(_raw(sb, "iec"))
    add("Registrations", "IEC (Importer-Exporter Code)", "ok" if iec else "missing",
        f"IEC {iec} found." if iec else "No IEC found on the invoice or shipping bill. Every exporter needs one from DGFT.")
    gstin = N.gstin(_raw(inv, "gstin")) or N.gstin(_raw(sb, "gstin"))
    add("Registrations", "Exporter GSTIN", "ok" if gstin else "check",
        f"GSTIN {gstin} found." if gstin else "No GSTIN found on the invoice or shipping bill.")

    # LUT: zero-rated export without paying IGST.
    sb_lut = sb and ("LUT" in (_raw(sb, "igst_status") or "").upper() or N.lut_arn(_raw(sb, "lut_arn")))
    if sb_lut:
        arn = N.lut_arn(_raw(inv, "lut_arn"))
        if not arn:
            add("Tax (GST)", "LUT reference on invoice", "missing",
                "The shipping bill declares export under LUT but the invoice has no LUT ARN.")
        else:
            inv_date = N.parse_date(_raw(inv, "doc_date"))
            m = re.search(r"FY\s*(\d{4})\s*-\s*(\d{2,4})", inv.text or "")
            if inv_date and m:
                stated = f"{m.group(1)}-{m.group(2)[-2:]}"
                needed = _financial_year(inv_date)
                add("Tax (GST)", "LUT valid for the invoice's financial year", "ok" if stated == needed else "missing",
                    f"LUT {arn} is stated as valid for FY {stated}; invoice dated {inv_date:%d %b %Y} falls in FY {needed}."
                    + ("" if stated == needed else " An LUT covers one financial year; file a fresh LUT."))
            else:
                add("Tax (GST)", "LUT valid for the invoice's financial year", "check",
                    f"LUT {arn} found, but its financial year is not stated. An LUT covers one financial year; confirm it covers this invoice.")
    elif sb:
        add("Tax (GST)", "IGST treatment", "check",
            "The shipping bill does not declare export under LUT. Confirm whether IGST was paid.")

    # Product-specific.
    inv_text = (inv.text if inv else "").upper()
    if product == "seafood":
        add("Seafood", "MPEDA registration", "ok" if "MPEDA" in inv_text else "check",
            "MPEDA registration number shown on the invoice." if "MPEDA" in inv_text
            else "MPEDA registration is mandatory for marine product exporters; it is not shown on the invoice.")
        if dest == "eu":
            add("Seafood to the EU", "EIC health certificate", "ok" if "health_certificate" in present else "missing",
                "Uploaded." if "health_certificate" in present
                else "Fishery products to the EU need an official health certificate issued by EIC.")
        else:
            add("Seafood", "Health / sanitary certificate", "ok" if "health_certificate" in present else "check",
                "Uploaded." if "health_certificate" in present
                else "Many importing countries require one; check the buyer's and the destination's requirements.")
    elif product == "spices":
        add("Spices", "Spices Board registration (CRES)", "ok" if "SPICES BOARD" in inv_text or "CRES" in inv_text else "check",
            "Registration shown on the invoice." if "SPICES BOARD" in inv_text or "CRES" in inv_text
            else "Exporters of spices must hold a Spices Board registration (CRES); it is not shown on the invoice.")
        add("Spices", "Phytosanitary certificate", "check",
            "Usually required by the importing country for plant products. Confirm with the buyer.")
    elif product == "rubber":
        add("Natural rubber", "Rubber Board registration", "check",
            "Confirm the exporter's Rubber Board registration is current.")

    if product == "seafood":
        add("Seafood", "Farm traceability for this lot", "check",
            "MPEDA's Aqua Trace enrols aquaculture farms and hatcheries; antibiotic rejections abroad have been traced "
            "back to farms. Keep the farm and hatchery records for this lot ready.")
    if product == "rubber" and dest == "eu":
        add("Natural rubber to the EU", "EUDR due-diligence statement and plot geolocation", "check",
            "The EU Deforestation Regulation covers natural rubber. It applies from 30 Dec 2026 for medium and large "
            "operators and 30 Jun 2027 for micro and small ones. The EU buyer will need plot geolocation and proof of "
            "no deforestation after 31 Dec 2020.")

    from .labtests import readiness_items
    for group, item, status, detail in readiness_items(docs, product, dest):
        add(group, item, status, detail)

    # Export incentives: RoDTEP / drawback must be claimed on the shipping bill itself.
    if sb:
        sb_text = (sb.text or "").upper()
        claimed = [name for name, words in (("RoDTEP", ["RODTEP"]), ("Drawback", ["DRAWBACK", "DBK"]))
                   if any(w in sb_text for w in words)]
        if claimed:
            add("Export incentives", "Incentive declared on shipping bill", "ok",
                f"{' and '.join(claimed)} declared on the shipping bill.")
        else:
            free = "FREE SHIPPING BILL" in sb_text
            add("Export incentives", "Incentive declared on shipping bill", "check",
                ("Filed as a Free Shipping Bill, so no RoDTEP or drawback is claimed. " if free else
                 "No RoDTEP or drawback claim found on the shipping bill. ")
                + "RoDTEP has to be declared in the shipping bill; adding it later needs an amendment that is often "
                  "refused. Confirm this is intended before filing.")

    # Key dates, counted from the shipping bill date (the exact start is the Let Export Order / export date).
    sb_date = N.parse_date(_raw(sb, "doc_date")) if sb else None
    if sb_date:
        def plus_months(d, m):
            y, mo = divmod(d.month - 1 + m, 12)
            day = min(d.day, [31, 29 if (d.year + y) % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo])
            return d.replace(year=d.year + y, month=mo + 1, day=day)
        add("Key dates", "Shipping bill amendment window", "info",
            f"Amendments must be requested within 3 months of the Let Export Order: about {plus_months(sb_date, 3):%d %b %Y} "
            f"if the order was given on the shipping bill date ({sb_date:%d %b %Y}).")
        add("Key dates", "Export proceeds to be realised", "info",
            f"Payment must be realised within 15 months of export (RBI, from Nov 2025): about {plus_months(sb_date, 15):%d %b %Y}.")

    add("Buyer requirements", "Certificate of origin", "ok" if "certificate_of_origin" in present else "check",
        "Uploaded." if "certificate_of_origin" in present
        else "Often requested by the buyer or needed for tariff preference. Check the contract.")

    counts = {s: sum(1 for i in items if i["status"] == s) for s in ("ok", "missing", "check", "info")}
    return {"product": product, "product_name": PRODUCTS[product], "product_basis": product_basis,
            "destination": dest, "destination_name": DESTINATIONS[dest], "destination_basis": dest_basis,
            "items": items, "counts": counts}
