"""Model output recorded from granite4:micro on data/demo/errors (raw values exactly as extracted).

Used to test the rule engine without running the model.
"""

from app.schemas import ExtractedField, ParsedDocument

ERRORS_RAW = {
    "purchase_order": {
        "doc_number": "NHF-PO-2026-0418", "doc_date": "20-Aug-2026",
        "exporter_name": "Kayal Marine Exports Private Limited", "consignee_name": "Noordhaven Foods B.V.",
        "description": "Frozen Raw Headless Shell-On Vannamei Shrimp (Litopenaeus vannamei), Size 31/40, IQF, 10 x 1 kg per master carton",
        "cartons": "1,200", "net_weight": "12,000", "net_weight_unit": "kg", "unit_price": "8.50",
        "total_amount": "102,000.00", "currency": "USD", "incoterms": "CFR Rotterdam",
        "port_of_loading": "Cochin (INCOK1)", "port_of_discharge": "Rotterdam (NLRTM)",
    },
    "commercial_invoice": {
        "doc_number": "KME/EXP/26-27/0093", "doc_date": "18-Sep-2026", "po_number": "NHF-PO-2026-0418",
        "exporter_name": "Kayal Marine Exports Private Limited", "iec": "AAKCK7731M", "gstin": "32AAKCK7731M1Z9",
        "consignee_name": "Noordhaven Foods B.V.",
        "description": "Frozen Raw Headless Shell-On Vannamei Shrimp (Litopenaeus vannamei), Size 31/40, IQF, 10 x 1 kg per master carton",
        "hs_code": "03061720", "cartons": "1,200", "net_weight": "12,000.00", "net_weight_unit": "kg",
        "unit_price": "8.50", "total_amount": "101,200.00", "currency": "USD", "incoterms": "CIF Rotterdam",
        "freight": "3,800.00", "fob_value": "98,200.00", "port_of_loading": "Cochin (INCOK1)",
        "port_of_discharge": "Rotterdam (NLRTM)", "lut_arn": None,
    },
    "packing_list": {
        "doc_number": "KME/PL/26-27/0093", "doc_date": "18-Sep-2026", "invoice_number": "KME/EXP/26-27/0093",
        "po_number": "NHF-PO-2026-0418", "consignee_name": "Noordhaven Foods B.V., Rotterdam, NL",
        "cartons": "1,180", "net_weight": "12,000.00", "net_weight_unit": "kg", "gross_weight": "13,440.00",
        "gross_weight_unit": "kg", "net_per_carton": "10.00", "gross_per_carton": "11.20",
        "port_of_loading": "Cochin (INCOK1)", "port_of_discharge": "Rotterdam (NLRTM)", "container_no": "KYLU 482913-0",
    },
    "shipping_bill": {
        "doc_number": "4718293", "doc_date": "15-Sep-2026", "invoice_number": "KME/EXP/26-27/0093 / 18-09-2026",
        "exporter_name": "KAYAL MARINE EXPORTS PRIVATE LIMITED", "iec": "AAKCK7731M", "gstin": "32AAKCK7731M1Z9",
        "consignee_name": "NOORDHAVEN FOODS B.V., NETHERLANDS", "hs_code": "03061740", "cartons": "1200",
        "net_weight": "12.000", "net_weight_unit": "MTS", "gross_weight": "13,440.000", "gross_weight_unit": "KGS",
        "fob_value": "98,200.00", "port_of_discharge": "ANTWERP (BEANR)", "container_no": "KYLU4829130",
        "lut_arn": "AD320326004417X", "igst_status": "LUT - NOT PAID",
    },
    "health_certificate": {
        "doc_number": "EIA/KOC/HC/2026/18842", "doc_date": "22-Sep-2026",
        "exporter_name": "Kayal Marine Exports Private Limited", "consignee_name": "Noordhaven Foods B.V.",
        "description": "Litopenaeus vannamei (aquacultured), frozen, raw, headless shell-on", "hs_code": "0306.17",
        "cartons": "1,200", "net_weight": "12,000.00", "net_weight_unit": "kg", "gross_weight": "13,440.00",
        "gross_weight_unit": "kg", "container_no": "KYLU 482913-0 / EIA 0048213",
    },
    "certificate_of_origin": {
        "doc_number": "MCT/COO/2026/7731", "doc_date": "23-Sep-2026",
        "invoice_number": "KME/EXP/26-27/0093 dt 18-Sep-2026", "exporter_name": "KAYAL MARINE EXPORTS PVT. LTD.",
        "consignee_name": "Noordhaven Foods B.V.", "description": "Frozen Shrimp", "hs_code": "0306.17.20",
        "cartons": "1,200", "net_weight": "12,000", "net_weight_unit": "kg", "gross_weight": "13,440",
        "gross_weight_unit": "kg",
    },
}

# The clean set differs from the errors set only in the 8 planted fields (see tools/make_demo_docs.py).
CLEAN_PATCH = {
    "packing_list": {"cartons": "1,200"},
    "shipping_bill": {"hs_code": "03061720", "doc_date": "23-Sep-2026", "port_of_discharge": "ROTTERDAM (NLRTM)"},
    "commercial_invoice": {"total_amount": "102,000.00", "incoterms": "CFR Rotterdam", "lut_arn": "AD320326004417X"},
    "certificate_of_origin": {
        "description": "Frozen Raw Headless Shell-On Vannamei Shrimp (Litopenaeus vannamei), 31/40, IQF"},
}


def make_docs(raw_by_type: dict) -> list[ParsedDocument]:
    docs = []
    for doc_type, values in raw_by_type.items():
        fields = {k: ExtractedField(key=k, raw=v, evidence=v, verified=v is not None) for k, v in values.items()}
        docs.append(ParsedDocument(filename=f"{doc_type}.pdf", doc_type=doc_type, text="", ocr_used=False,
                                   fields=fields))
    return docs


def errors_docs() -> list[ParsedDocument]:
    return make_docs(ERRORS_RAW)


def clean_docs() -> list[ParsedDocument]:
    raw = {t: dict(v) | CLEAN_PATCH.get(t, {}) for t, v in ERRORS_RAW.items()}
    return make_docs(raw)
