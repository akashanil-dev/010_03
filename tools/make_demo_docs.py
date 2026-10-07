"""Generate the synthetic demo shipment PDFs used for testing and the live demo.

Produces three sets under data/demo/:
  clean/    six consistent documents
  errors/   the same six documents with 8 planted issues
  bundle/   the scanned set merged into one PDF
  scanned/  the errors set, with the packing list as an image-only "scan"

All companies, people and ID numbers are fictitious.
Usage: python tools/make_demo_docs.py
"""

import copy
import io
import random
from pathlib import Path

import pymupdf
from PIL import Image, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "data" / "demo"

CLEAN = {
    "exporter": "Kayal Marine Exports Private Limited",
    "exporter_addr": "Plot 14, KSIDC Industrial Estate, Aroor, Alappuzha, Kerala 688534, India",
    "iec": "AAKCK7731M",
    "gstin": "32AAKCK7731M1Z9",
    "mpeda": "KL/MPEDA/EXP/2019/0471",
    "buyer": "Noordhaven Foods B.V.",
    "buyer_addr": "Havenkade 21, 3011 AB Rotterdam, The Netherlands",
    "eori": "NL861204573",
    "po_no": "NHF-PO-2026-0418",
    "po_date": "20-Aug-2026",
    "inv_no": "KME/EXP/26-27/0093",
    "inv_date": "18-Sep-2026",
    "pl_no": "KME/PL/26-27/0093",
    "desc": "Frozen Raw Headless Shell-On Vannamei Shrimp (Litopenaeus vannamei), Size 31/40, IQF, 10 x 1 kg per master carton",
    "coo_desc": "Frozen Raw Headless Shell-On Vannamei Shrimp (Litopenaeus vannamei), 31/40, IQF",
    "hs": "03061720",
    "cartons": "1,200",
    "pl_cartons": "1,200",
    "net": "12,000.00",
    "gross": "13,440.00",
    "rate": "8.50",
    "total": "102,000.00",
    "freight": "3,800.00",
    "fob": "98,200.00",
    "fob_inr": "84,94,300.00",
    "incoterms": "CFR Rotterdam",
    "pol": "Cochin (INCOK1)",
    "pod": "Rotterdam (NLRTM)",
    "sb_pod": "ROTTERDAM (NLRTM)",
    "container": "KYLU 482913-0",
    "seal": "EIA 0048213",
    "vessel": "MV Malabar Star V.026W",
    "lut_line": 'Supply meant for export under LUT without payment of IGST. LUT ARN AD320326004417X, valid FY 2026-27.',
    "sb_no": "4718293",
    "sb_date": "23-Sep-2026",
    "hc_no": "EIA/KOC/HC/2026/18842",
    "hc_date": "22-Sep-2026",
    "coo_no": "MCT/COO/2026/7731",
    "coo_date": "23-Sep-2026",
}

# The 8 planted issues (see the data pack, page 6).
ERRORS = {
    "pl_cartons": "1,180",                       # 1 PL cartons vs everyone else
    "sb_hs": "03061740",                         # 2 SB HS code: black tiger, not Vannamei
    "total": "101,200.00",                       # 3 invoice total != 12,000 x 8.50
    "inv_incoterms": "CIF Rotterdam",            # 4 invoice Incoterms vs PO CFR
    "lut_line": "",                              # 5 LUT reference removed from invoice
    "sb_date": "15-Sep-2026",                    # 6 SB dated before the invoice
    "sb_pod": "ANTWERP (BEANR)",                 # 7 SB port of discharge
    "coo_desc": "Frozen Shrimp",                 # 8 vague description on CoO (warning)
}

CSS = """
* { font-family: sans-serif; font-size: 9pt; }
h1 { font-size: 15pt; margin: 0 0 2px 0; }
.sub { color: #555; font-size: 8pt; }
table { border-collapse: collapse; width: 100%; margin-top: 6px; }
td, th { border: 1px solid #999; padding: 3px; vertical-align: top; }
th { background-color: #eee; text-align: left; }
.r { text-align: right; }
p { margin: 4px 0; }
"""


def kv(rows):
    return "<table>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</table>"


def doc_po(d):
    return f"""<h1>PURCHASE ORDER</h1>
<p class="sub">{d['buyer']}, {d['buyer_addr']} | EORI {d['eori']}</p>
{kv([("PO No.", d['po_no']), ("Date", d['po_date']), ("Supplier", f"{d['exporter']}, {d['exporter_addr']}"),
     ("Incoterms", d['incoterms'] + " (Incoterms 2020)"), ("Port of loading", d['pol']), ("Port of discharge", d['pod']),
     ("Latest shipment", "30-Sep-2026"), ("Payment", "30% advance, 70% cash against documents")])}
<table><tr><th>Item</th><th>Description</th><th>Cartons</th><th>Net kg</th><th>USD/kg</th><th>Amount USD</th></tr>
<tr><td>1</td><td>{d['desc']}</td><td class="r">{d['cartons']}</td><td class="r">{d['net']}</td><td class="r">{d['rate']}</td><td class="r">102,000.00</td></tr></table>
<p>Documents required: commercial invoice, packing list, EIC health certificate for EU, certificate of origin.</p>
<p>Authorised by: Purchasing, {d['buyer']}</p>"""


def doc_invoice(d):
    inc = d.get("inv_incoterms", d["incoterms"])
    return f"""<h1>COMMERCIAL INVOICE</h1>
<p class="sub">{d['exporter']}, {d['exporter_addr']}<br>IEC {d['iec']} | GSTIN {d['gstin']} | MPEDA Reg. {d['mpeda']}</p>
{kv([("Invoice No.", d['inv_no']), ("Invoice date", d['inv_date']), ("Buyer / Consignee", f"{d['buyer']}, {d['buyer_addr']} | EORI {d['eori']}"),
     ("Buyer's order", f"{d['po_no']} dt {d['po_date']}"), ("Incoterms", inc), ("Payment terms", "30% advance, 70% CAD"),
     ("Port of loading", d['pol']), ("Port of discharge", d['pod']), ("Vessel", d['vessel'])])}
<table><tr><th>Marks</th><th>Description of goods</th><th>ITC-HS</th><th>Cartons</th><th>Net kg</th><th>USD/kg</th><th>Amount USD</th></tr>
<tr><td>KME/NHF-0418</td><td>{d['desc']}</td><td>{d['hs']}</td><td class="r">{d['cartons']}</td><td class="r">{d['net']}</td><td class="r">{d['rate']}</td><td class="r">{d['total']}</td></tr>
<tr><td colspan="6" class="r">Total {inc}</td><td class="r"><b>{d['total']}</b></td></tr>
<tr><td colspan="6" class="r">Less: ocean freight</td><td class="r">{d['freight']}</td></tr>
<tr><td colspan="6" class="r">FOB value</td><td class="r">{d['fob']}</td></tr></table>
<p>{d['lut_line']}</p>
<p>Country of origin: India.</p>
<p>We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct.</p>
<p>For {d['exporter']}, Authorised Signatory</p>"""


def doc_packing(d):
    return f"""<h1>PACKING LIST</h1>
<p class="sub">{d['exporter']}, Aroor, Alappuzha, Kerala</p>
{kv([("Packing list No.", d['pl_no']), ("Date", d['inv_date']), ("Invoice No.", d['inv_no']), ("Buyer's order", d['po_no']),
     ("Consignee", f"{d['buyer']}, Rotterdam, NL"), ("Container / Seal", f"{d['container']} (20' reefer, -18 C) / {d['seal']}"),
     ("Port of loading", d['pol']), ("Port of discharge", d['pod']), ("Vessel", d['vessel'])])}
<table><tr><th>Carton nos.</th><th>Description</th><th>Cartons</th><th>Net/ctn kg</th><th>Gross/ctn kg</th><th>Total net kg</th><th>Total gross kg</th></tr>
<tr><td>1-1200</td><td>Frozen Raw HLSO Vannamei Shrimp 31/40, IQF, 10 x 1 kg</td><td class="r">{d['pl_cartons']}</td><td class="r">10.00</td><td class="r">11.20</td><td class="r">{d['net']}</td><td class="r">{d['gross']}</td></tr>
<tr><td colspan="2" class="r"><b>TOTAL</b></td><td class="r"><b>{d['pl_cartons']}</b></td><td></td><td></td><td class="r"><b>{d['net']}</b></td><td class="r"><b>{d['gross']}</b></td></tr></table>
<p>Shipping marks: KME / NHF-0418 / ROTTERDAM / C/No. 1-1200. Keep at -18 C or below.</p>
<p>Packed and checked: Warehouse, Aroor plant. Authorised Signatory.</p>"""


def doc_shipping_bill(d):
    return f"""<h1>SHIPPING BILL FOR EXPORT</h1>
<p class="sub">Indian Customs EDI System (ICEGATE) | Port: Cochin Sea (INCOK1) | CHA: Backwater Clearing Agency, Lic. KOC/CHA/2211</p>
{kv([("SB No.", d['sb_no']), ("SB Date", d['sb_date']), ("Exporter", d['exporter'].upper()), ("IEC", d['iec']), ("GSTIN", d['gstin']),
     ("Consignee", d['buyer'].upper() + ", NETHERLANDS"), ("Port of discharge", d['sb_pod']), ("Country of destination", "NETHERLANDS"),
     ("Invoice No. / Date", f"{d['inv_no']} / 18-09-2026"), ("Nature of contract", "CFR"),
     ("IGST payment status", "LUT - NOT PAID (ARN AD320326004417X)"), ("Exchange rate", "1 USD = 86.50 INR")])}
<table><tr><th>RITC</th><th>Description</th><th>Qty</th><th>Unit</th><th>Pkgs</th><th>FOB (USD)</th><th>FOB (INR)</th></tr>
<tr><td>{d.get('sb_hs', d['hs'])}</td><td>FROZEN RAW HLSO VANNAMEI SHRIMP 31/40</td><td class="r">12.000</td><td>MTS</td><td class="r">1200 CTNS</td><td class="r">{d['fob']}</td><td class="r">{d['fob_inr']}</td></tr></table>
<p>Gross wt 13,440.000 KGS | Container KYLU4829130 | Seal EIA0048213 | Scheme: Free Shipping Bill</p>"""


def doc_health_cert(d):
    return f"""<h1>HEALTH CERTIFICATE - FISHERY PRODUCTS FOR EU</h1>
<p class="sub">Export Inspection Agency, Kochi (simplified demo format)</p>
{kv([("Certificate No.", d['hc_no']), ("Date of issue", d['hc_date']), ("Consignor", f"{d['exporter']}, Aroor, Alappuzha, Kerala, India | MPEDA {d['mpeda']}"),
     ("Consignee", f"{d['buyer']}, {d['buyer_addr']}"), ("Approved establishment", "EIA-KOC-1742"),
     ("Place of loading / destination", "Cochin, India -> Rotterdam, Netherlands"), ("Commodity (HS)", "0306.17"),
     ("Species", "Litopenaeus vannamei (aquacultured), frozen, raw, headless shell-on"),
     ("Number of packages", f"{d['cartons']} cartons"), ("Net weight", f"{d['net']} kg"), ("Gross weight", f"{d['gross']} kg"),
     ("Container / Seal", f"{d['container']} / {d['seal']}"), ("Identification marks", "KME / NHF-0418 / ROTTERDAM")])}
<p>The official inspector certifies that the fishery products described above were obtained, processed, stored and transported in line with the applicable requirements and are fit for human consumption.</p>
<p>Place: Kochi | Date: {d['hc_date']} | Official Inspector (seal)</p>"""


def doc_origin(d):
    return f"""<h1>CERTIFICATE OF ORIGIN (NON-PREFERENTIAL)</h1>
<p class="sub">Issued by: Malabar Chamber of Trade, Kochi</p>
{kv([("Certificate No.", d['coo_no']), ("Date", d['coo_date']), ("Exporter", "KAYAL MARINE EXPORTS PVT. LTD., Aroor, Alappuzha, Kerala, India"),
     ("Consignee", f"{d['buyer']}, Rotterdam, The Netherlands"), ("Transport", f"By sea, {d['vessel']}, Cochin -> Rotterdam"),
     ("Invoice reference", f"{d['inv_no']} dt {d['inv_date']}")])}
<table><tr><th>Marks</th><th>Description of goods</th><th>HS</th><th>Packages</th><th>Net / Gross kg</th></tr>
<tr><td>KME/NHF-0418</td><td>{d['coo_desc']}</td><td>0306.17.20</td><td class="r">{d['cartons']} cartons</td><td class="r">{d['net']} / {d['gross']}</td></tr></table>
<p>It is hereby certified that the goods described above originate in India.</p>
<p>Exporter's declaration signed {d['coo_date']}. Certifying authority (seal).</p>"""


DOCS = {
    "01_purchase_order.pdf": doc_po,
    "02_commercial_invoice.pdf": doc_invoice,
    "03_packing_list.pdf": doc_packing,
    "04_shipping_bill.pdf": doc_shipping_bill,
    "05_health_certificate.pdf": doc_health_cert,
    "06_certificate_of_origin.pdf": doc_origin,
}


def render_pdf(html: str, path: Path) -> None:
    story = pymupdf.Story(html=f"<style>{CSS}</style><body>{html}<p class='sub'>SYNTHETIC DEMO DOCUMENT - fictitious entities</p></body>")
    writer = pymupdf.DocumentWriter(str(path))
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (36, 36, -36, -36)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()


def make_scan(src: Path, dst: Path) -> None:
    """Turn a PDF into an image-only PDF that looks like a slightly skewed photocopy."""
    rng = random.Random(7)
    pdf = pymupdf.open(src)
    out = pymupdf.open()
    for page in pdf:
        pix = page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
        img = img.rotate(1.8, expand=True, fillcolor=235, resample=Image.BICUBIC)
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        px = img.load()
        for _ in range(img.width * img.height // 80):
            x, y = rng.randrange(img.width), rng.randrange(img.height)
            px[x, y] = max(0, px[x, y] - rng.randrange(40, 120))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=buf.getvalue())
    out.save(dst)


def main() -> None:
    errors = copy.deepcopy(CLEAN) | ERRORS
    for name, data in (("clean", CLEAN), ("errors", errors)):
        folder = OUT / name
        folder.mkdir(parents=True, exist_ok=True)
        for fname, builder in DOCS.items():
            render_pdf(builder(data), folder / fname)

    scanned = OUT / "scanned"
    scanned.mkdir(parents=True, exist_ok=True)
    for fname in DOCS:
        src = OUT / "errors" / fname
        if fname == "03_packing_list.pdf":
            make_scan(src, scanned / fname)
        else:
            (scanned / fname).write_bytes(src.read_bytes())

    # bundle/: the whole scanned set merged into a single PDF, as a broker might receive it.
    bundle = OUT / "bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    merged = pymupdf.open()
    for fname in DOCS:
        with pymupdf.open(scanned / fname) as part:
            merged.insert_pdf(part)
    merged.save(bundle / "shipment_KME-0093_all_documents.pdf")
    print(f"Wrote demo sets to {OUT}")


if __name__ == "__main__":
    main()
