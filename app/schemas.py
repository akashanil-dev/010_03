"""Document types and the fields extracted from each one.

The model copies every value exactly as printed (as text). Conversion to
numbers, kilograms, dates and canonical codes happens later, in normalize.py,
with plain deterministic code.
"""

from pydantic import BaseModel

DOC_TYPES = {
    "purchase_order": "Purchase Order",
    "commercial_invoice": "Commercial Invoice",
    "packing_list": "Packing List",
    "shipping_bill": "Shipping Bill",
    "health_certificate": "Quality / Health Certificate",
    "certificate_of_origin": "Certificate of Origin",
    "letter_of_credit": "Letter of Credit",
}

# Who usually prepares each document: issues are routed to them.
OWNERS = {
    "purchase_order": "Buyer / sales team",
    "commercial_invoice": "Accounts / sales",
    "packing_list": "Warehouse",
    "shipping_bill": "Customs broker (CHA)",
    "health_certificate": "Quality / EIC liaison",
    "certificate_of_origin": "Export documentation",
    "letter_of_credit": "Buyer / bank (LC amendment)",
}

# Hierarchy rank: lower = closer to the source of truth (the buyer's contract).
HIERARCHY = {
    "purchase_order": 0,
    "commercial_invoice": 1,
    "packing_list": 2,
    "shipping_bill": 3,
    "health_certificate": 3,
    "certificate_of_origin": 3,
    "letter_of_credit": -1,   # checked separately: documents must comply with the LC, not outvote it
}

# Field key -> (label shown in the UI, instruction given to the model)
FIELDS = {
    "doc_number": ("Document no.", "this document's own number (PO no., invoice no., SB no., certificate no.)"),
    "doc_date": ("Document date", "this document's own date, as printed"),
    "po_number": ("PO reference", "the buyer's purchase order number referenced"),
    "invoice_number": ("Invoice reference", "the commercial invoice number referenced"),
    "exporter_name": ("Exporter", "exporter / supplier / consignor company name only, no address"),
    "iec": ("IEC", "exporter's IEC code"),
    "gstin": ("GSTIN", "exporter's GSTIN"),
    "consignee_name": ("Consignee", "buyer / consignee company name only, no address"),
    "description": ("Goods description", "full description of the goods as printed"),
    "hs_code": ("HS code", "HS / ITC-HS / RITC code of the goods"),
    "cartons": ("Cartons", "total number of cartons / packages, as printed (e.g. '1,200' or '1200 CTNS')"),
    "net_weight": ("Net weight", "TOTAL net weight of the shipment as printed, without unit (not the carton count)"),
    "net_weight_unit": ("Net weight unit", "unit of the total net weight (e.g. kg, KGS, MT, MTS); if the unit is only in a label like 'Total net kg', use kg"),
    "gross_weight": ("Gross weight", "TOTAL gross weight of the shipment as printed, without unit (not the carton count)"),
    "gross_weight_unit": ("Gross weight unit", "unit of the total gross weight; if the unit is only in a label like 'Total gross kg', use kg"),
    "net_per_carton": ("Net kg per carton", "net weight per carton"),
    "gross_per_carton": ("Gross kg per carton", "gross weight per carton"),
    "unit_price": ("Unit price", "price per unit (per kg) as printed"),
    "total_amount": ("Total amount", "total invoice / order amount as printed"),
    "currency": ("Currency", "currency of the amounts (e.g. USD)"),
    "incoterms": ("Incoterms", "Incoterms, e.g. 'CFR Rotterdam'"),
    "freight": ("Freight", "ocean freight amount, if shown"),
    "fob_value": ("FOB value", "FOB value in the foreign currency (USD)"),
    "port_of_loading": ("Port of loading", "port of loading"),
    "port_of_discharge": ("Port of discharge", "port of discharge / destination port"),
    "container_no": ("Container no.", "container number"),
    "lut_arn": ("LUT ARN", "LUT ARN reference number if printed, else null"),
    "igst_status": ("IGST status", "IGST payment status text, e.g. 'LUT - NOT PAID'"),
    "expiry_date": ("LC expiry date", "date and place of expiry of the credit (field 31D)"),
    "latest_shipment_date": ("Latest shipment date", "latest date of shipment (field 44C)"),
    "applicant_name": ("Applicant", "applicant / buyer company name only (field 50)"),
    "beneficiary_name": ("Beneficiary", "beneficiary / exporter company name only (field 59)"),
    "amount_tolerance": ("Amount tolerance", "percentage credit amount tolerance (field 39A), e.g. '05/05'"),
    "presentation_days": ("Presentation period", "period for presentation of documents (field 48), e.g. '21 DAYS'"),
    "documents_required": ("Documents required", "list of documents required (field 46A), as printed, separated by ';'"),
}

DOC_FIELDS = {
    "letter_of_credit": ["doc_number", "doc_date", "expiry_date", "latest_shipment_date", "applicant_name",
                         "beneficiary_name", "total_amount", "currency", "amount_tolerance", "description",
                         "net_weight", "net_weight_unit", "incoterms", "port_of_loading", "port_of_discharge",
                         "presentation_days", "documents_required"],
    "purchase_order": ["doc_number", "doc_date", "exporter_name", "consignee_name", "description", "cartons",
                       "net_weight", "net_weight_unit", "unit_price", "total_amount", "currency", "incoterms",
                       "port_of_loading", "port_of_discharge"],
    "commercial_invoice": ["doc_number", "doc_date", "po_number", "exporter_name", "iec", "gstin", "consignee_name",
                           "description", "hs_code", "cartons", "net_weight", "net_weight_unit", "unit_price",
                           "total_amount", "currency", "incoterms", "freight", "fob_value", "port_of_loading",
                           "port_of_discharge", "lut_arn"],
    "packing_list": ["doc_number", "doc_date", "invoice_number", "po_number", "consignee_name", "cartons",
                     "net_weight", "net_weight_unit", "gross_weight", "gross_weight_unit", "net_per_carton",
                     "gross_per_carton", "port_of_loading", "port_of_discharge", "container_no"],
    "shipping_bill": ["doc_number", "doc_date", "invoice_number", "exporter_name", "iec", "gstin", "consignee_name",
                      "hs_code", "cartons", "net_weight", "net_weight_unit", "gross_weight", "gross_weight_unit",
                      "fob_value", "port_of_discharge", "container_no", "lut_arn", "igst_status"],
    "health_certificate": ["doc_number", "doc_date", "exporter_name", "consignee_name", "description", "hs_code",
                           "cartons", "net_weight", "net_weight_unit", "gross_weight", "gross_weight_unit",
                           "container_no"],
    "certificate_of_origin": ["doc_number", "doc_date", "invoice_number", "exporter_name", "consignee_name",
                              "description", "hs_code", "cartons", "net_weight", "net_weight_unit", "gross_weight",
                              "gross_weight_unit"],
}


class ExtractedField(BaseModel):
    key: str
    raw: str | None            # exactly as the model read it
    value: object = None       # normalised value (number, kg, date, canonical text)
    evidence: str | None = None  # snippet of the source text that contains the value
    verified: bool = False     # True when the raw value was found in the source text


class ParsedDocument(BaseModel):
    filename: str
    doc_type: str | None
    text: str                  # markdown text from Docling
    ocr_used: bool
    source_format: str = ""
    fields: dict[str, ExtractedField] = {}
    seconds: float = 0.0
