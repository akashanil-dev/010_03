"""Generate the coir demo shipment: goods priced per piece, not per kg.

Writes data/demo/coir/: 4,800 coir door mats from Alappuzha to Hamburg at USD 3.25 per piece. One planted issue:
the invoice total is typed as 15,060.00 instead of 15,600.00 (the FOB value and shipping bill follow the wrong
total). Everything else agrees, and no health certificate is involved, so the only flag expected is the invoice
arithmetic, worked out per piece.

All companies, people and ID numbers are fictitious.
Usage: python tools/make_coir_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_demo_docs import OUT, kv, render_pdf  # noqa: E402  (shared PDF style)

D = {
    "exporter": "Vembanad Coir Crafts Private Limited",
    "exporter_addr": "Coir Park Road, Kalavoor, Alappuzha, Kerala 688522, India",
    "iec": "AAFCV4419K",
    "gstin": "32AAFCV4419K1Z3",
    "coir_board": "CB/EXP/ALP/0318",
    "buyer": "Elbmarkt Wohnwaren GmbH",
    "buyer_addr": "Billstrasse 88, 20539 Hamburg, Germany",
    "eori": "DE4471902",
    "po_no": "EWW-PO-26-0177",
    "po_date": "03-Sep-2026",
    "inv_no": "VCC/EXP/26-27/0058",
    "inv_date": "01-Oct-2026",
    "pl_no": "VCC/PL/26-27/0058",
    "desc": "Coir door mats, natural fibre, PVC backed, 40 x 60 cm, printed 'Welcome', 20 pcs per carton",
    "hs": "57022010",
    "qty": "4,800",
    "cartons": "240",
    "net": "7,680.00",
    "gross": "8,040.00",
    "rate": "3.25",
    "total": "15,600.00",
    "inv_total": "15,060.00",       # planted: digits swapped
    "freight": "1,450.00",
    "fob": "13,610.00",             # follows the wrong total
    "fob_inr": "11,77,265.00",
    "incoterms": "CFR Hamburg",
    "pol": "Cochin (INCOK1)",
    "pod": "Hamburg (DEHAM)",
    "container": "TGHU 731052-6",
    "seal": "VCC 0030917",
    "vessel": "MV Kerala Pride V.031W",
    "lut": "AD320426011852Q",
    "sb_no": "5520174",
    "sb_date": "06-Oct-2026",
    "coo_no": "ACC/COO/2026/1196",
    "coo_date": "06-Oct-2026",
}


def doc_po(d):
    return f"""<h1>PURCHASE ORDER</h1>
<p class="sub">{d['buyer']}, {d['buyer_addr']} | EORI {d['eori']}</p>
{kv([("PO No.", d['po_no']), ("Date", d['po_date']), ("Supplier", f"{d['exporter']}, {d['exporter_addr']}"),
     ("Incoterms", d['incoterms'] + " (Incoterms 2020)"), ("Port of loading", d['pol']), ("Port of discharge", d['pod']),
     ("Latest shipment", "15-Oct-2026"), ("Payment", "Cash against documents")])}
<table><tr><th>Item</th><th>Description</th><th>Quantity</th><th>Unit</th><th>USD per piece</th><th>Amount USD</th></tr>
<tr><td>1</td><td>{d['desc']}</td><td class="r">{d['qty']}</td><td>PCS</td><td class="r">{d['rate']}</td><td class="r">{d['total']}</td></tr></table>
<p>Packing: {d['cartons']} export cartons. Documents required: commercial invoice, packing list, certificate of origin.</p>
<p>Authorised by: Einkauf, {d['buyer']}</p>"""


def doc_invoice(d):
    return f"""<h1>COMMERCIAL INVOICE</h1>
<p class="sub">{d['exporter']}, {d['exporter_addr']}<br>IEC {d['iec']} | GSTIN {d['gstin']} | Coir Board Reg. {d['coir_board']}</p>
{kv([("Invoice No.", d['inv_no']), ("Invoice date", d['inv_date']), ("Buyer / Consignee", f"{d['buyer']}, {d['buyer_addr']} | EORI {d['eori']}"),
     ("Buyer's order", f"{d['po_no']} dt {d['po_date']}"), ("Incoterms", d['incoterms']), ("Payment terms", "CAD"),
     ("Port of loading", d['pol']), ("Port of discharge", d['pod']), ("Vessel", d['vessel'])])}
<table><tr><th>Marks</th><th>Description of goods</th><th>ITC-HS</th><th>Cartons</th><th>Quantity</th><th>Unit</th><th>USD per piece</th><th>Amount USD</th></tr>
<tr><td>VCC/EWW-0177</td><td>{d['desc']}</td><td>{d['hs']}</td><td class="r">{d['cartons']}</td><td class="r">{d['qty']}</td><td>PCS</td><td class="r">{d['rate']}</td><td class="r">{d['inv_total']}</td></tr>
<tr><td colspan="7" class="r">Total {d['incoterms']}</td><td class="r"><b>{d['inv_total']}</b></td></tr>
<tr><td colspan="7" class="r">Less: ocean freight</td><td class="r">{d['freight']}</td></tr>
<tr><td colspan="7" class="r">FOB value</td><td class="r">{d['fob']}</td></tr></table>
<p>Net weight {d['net']} kg | Gross weight {d['gross']} kg</p>
<p>Supply meant for export under LUT without payment of IGST. LUT ARN {d['lut']}, valid FY 2026-27.</p>
<p>Country of origin: India.</p>
<p>For {d['exporter']}, Authorised Signatory</p>"""


def doc_packing(d):
    return f"""<h1>PACKING LIST</h1>
<p class="sub">{d['exporter']}, Kalavoor, Alappuzha, Kerala</p>
{kv([("Packing list No.", d['pl_no']), ("Date", d['inv_date']), ("Invoice No.", d['inv_no']), ("Buyer's order", d['po_no']),
     ("Consignee", f"{d['buyer']}, Hamburg, DE"), ("Container / Seal", f"{d['container']} (40' dry) / {d['seal']}"),
     ("Port of loading", d['pol']), ("Port of discharge", d['pod']), ("Vessel", d['vessel'])])}
<table><tr><th>Carton nos.</th><th>Description</th><th>Cartons</th><th>Pieces</th><th>Net/ctn kg</th><th>Gross/ctn kg</th><th>Total net kg</th><th>Total gross kg</th></tr>
<tr><td>1-240</td><td>Coir door mats 40 x 60 cm, 20 pcs per carton</td><td class="r">{d['cartons']}</td><td class="r">{d['qty']}</td><td class="r">32.00</td><td class="r">33.50</td><td class="r">{d['net']}</td><td class="r">{d['gross']}</td></tr>
<tr><td colspan="2" class="r"><b>TOTAL</b></td><td class="r"><b>{d['cartons']}</b></td><td class="r"><b>{d['qty']}</b></td><td></td><td></td><td class="r"><b>{d['net']}</b></td><td class="r"><b>{d['gross']}</b></td></tr></table>
<p>Shipping marks: VCC / EWW-0177 / HAMBURG / C/No. 1-240.</p>
<p>Packed and checked: Despatch, Kalavoor unit. Authorised Signatory.</p>"""


def doc_shipping_bill(d):
    return f"""<h1>SHIPPING BILL FOR EXPORT</h1>
<p class="sub">Indian Customs EDI System (ICEGATE) | Port: Cochin Sea (INCOK1) | CHA: Backwater Clearing Agency, Lic. KOC/CHA/2211</p>
{kv([("SB No.", d['sb_no']), ("SB Date", d['sb_date']), ("Exporter", d['exporter'].upper()), ("IEC", d['iec']), ("GSTIN", d['gstin']),
     ("Consignee", d['buyer'].upper() + ", GERMANY"), ("Port of discharge", "HAMBURG (DEHAM)"), ("Country of destination", "GERMANY"),
     ("Invoice No. / Date", f"{d['inv_no']} / 01-10-2026"), ("Nature of contract", "CFR"),
     ("IGST payment status", f"LUT - NOT PAID (ARN {d['lut']})"), ("Exchange rate", "1 USD = 86.50 INR")])}
<table><tr><th>RITC</th><th>Description</th><th>Qty</th><th>Unit</th><th>Pkgs</th><th>FOB (USD)</th><th>FOB (INR)</th></tr>
<tr><td>{d['hs']}</td><td>COIR DOOR MATS, PVC BACKED, 40X60 CM</td><td class="r">4800</td><td>PCS</td><td class="r">240 CTNS</td><td class="r">{d['fob']}</td><td class="r">{d['fob_inr']}</td></tr></table>
<p>Net wt {d['net']} KGS | Gross wt {d['gross']} KGS | Container TGHU7310526 | Seal VCC0030917 | Scheme: Free Shipping Bill</p>"""


def doc_origin(d):
    return f"""<h1>CERTIFICATE OF ORIGIN (NON-PREFERENTIAL)</h1>
<p class="sub">Issued by: Alleppey Chamber of Commerce (fictitious)</p>
{kv([("Certificate No.", d['coo_no']), ("Date", d['coo_date']), ("Exporter", f"{d['exporter'].upper()}, Kalavoor, Alappuzha, Kerala, India"),
     ("Consignee", f"{d['buyer']}, Hamburg, Germany"), ("Transport", f"By sea, {d['vessel']}, Cochin -> Hamburg"),
     ("Invoice reference", f"{d['inv_no']} dt {d['inv_date']}")])}
<table><tr><th>Marks</th><th>Description of goods</th><th>HS</th><th>Packages</th><th>Net / Gross kg</th></tr>
<tr><td>VCC/EWW-0177</td><td>Coir door mats, natural fibre, PVC backed, 40 x 60 cm ({d['qty']} pcs)</td><td>5702.20.10</td><td class="r">{d['cartons']} cartons</td><td class="r">{d['net']} / {d['gross']}</td></tr></table>
<p>It is hereby certified that the goods described above originate in India.</p>
<p>Exporter's declaration signed {d['coo_date']}. Certifying authority (seal).</p>"""


def main() -> None:
    folder = OUT / "coir"
    folder.mkdir(parents=True, exist_ok=True)
    for name, make in (("01_purchase_order.pdf", doc_po), ("02_commercial_invoice.pdf", doc_invoice),
                       ("03_packing_list.pdf", doc_packing), ("04_shipping_bill.pdf", doc_shipping_bill),
                       ("05_certificate_of_origin.pdf", doc_origin)):
        render_pdf(make(D), folder / name)
    print(f"Wrote {folder}")


if __name__ == "__main__":
    main()
