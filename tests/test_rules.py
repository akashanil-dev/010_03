"""Rule engine tests on recorded model output for the demo shipment. Run: pytest -q"""

from app import normalize as N
from app.report import build
from tests.fixtures import clean_docs, errors_docs


def flagged(report):
    return {c["id"]: c["status"] for c in report["checks"] if c["status"] in ("error", "warning")}


def test_clean_set_has_no_false_flags():
    report = build(clean_docs())
    assert report["verdict"] == "ready"
    assert flagged(report) == {}


def test_all_eight_planted_issues_are_caught():
    report = build(errors_docs())
    flags = flagged(report)
    assert report["verdict"] == "blocked"
    assert flags["cross:cartons"] == "error"                                    # 1 packing list 1,180
    assert flags["cross:hs_code"] == "error"                                    # 2 shipping bill HS
    assert flags["math:invoice"] == "error"                                     # 3 invoice total
    assert flags["cross:incoterms"] == "error"                                  # 4 CIF vs CFR
    assert flags["comp:lut"] == "error"                                         # 5 LUT missing
    assert flags["comp:date:commercial_invoice:shipping_bill"] == "error"       # 6 SB dated early
    assert flags["cross:port_of_discharge"] == "error"                          # 7 Antwerp
    assert flags["cross:description"] == "warning"                              # 8 vague description


def test_format_traps_are_not_flagged():
    flags = flagged(build(errors_docs()))
    for trap in ("cross:net_weight", "cross:gross_weight", "cross:exporter_name", "cross:consignee_name",
                 "cross:container_no", "cross:invoice_ref"):
        assert trap not in flags, trap


def test_outlier_is_the_packing_list():
    check = next(c for c in build(errors_docs())["checks"] if c["id"] == "cross:cartons")
    outliers = [v["doc_type"] for v in check["values"] if v["outlier"]]
    assert outliers == ["packing_list"]


def test_normalisers():
    assert N.weight_kg("12.000", "MTS") == 12000
    assert N.weight_kg("13,440.000 KGS", None) == 13440
    assert N.count("1200 CTNS") == 1200
    assert N.company("KAYAL MARINE EXPORTS PVT. LTD.") == N.company("Kayal Marine Exports Private Limited")
    assert N.hs_equal(N.hs_code("0306.17"), N.hs_code("03061720"))
    assert not N.hs_equal(N.hs_code("03061740"), N.hs_code("03061720"))
    assert N.container("KYLU 482913-0 / EIA 0048213") == N.container("KYLU4829130")
    assert N.reference("KME/EXP/26-27/0093 dt 18-Sep-2026") == "KME/EXP/26-27/0093"
    assert N.reference("Invoice No.: KME/EXP/26-27/0093") == "KME/EXP/26-27/0093"   # label leaked by the model
    assert N.iec("IEC AAKCK7731M") == N.iec("AAKCK7731M") == "AAKCK7731M"
    assert N.gstin("GSTIN 32AAKCK7731M1Z9") == "32AAKCK7731M1Z9"
    assert str(N.parse_date("18-09-2026")) == str(N.parse_date("18-Sep-2026")) == "2026-09-18"


def test_certificate_titles_are_recognised():
    from app.parsing import classify
    for title in ("HEALTH CERTIFICATE", "QUALITY CERTIFICATE", "CERTIFICATE OF ANALYSIS", "INSPECTION CERTIFICATE",
                  "PHYTOSANITARY CERTIFICATE", "LABORATORY TEST REPORT"):
        assert classify(f"## {title}\n\nIssued by ...") == "health_certificate", title
    assert classify("## CERTIFICATE OF ORIGIN (NON-PREFERENTIAL)") == "certificate_of_origin"
    assert classify("## PACKING LIST") == "packing_list"


def _cert(text):
    from app.schemas import ParsedDocument
    return ParsedDocument(filename="qc.pdf", doc_type="health_certificate", text=text, ocr_used=False, fields={})


def test_lab_results_screening():
    from app import labtests
    bad = labtests.check([_cert("Parameter: Nitrofurans (AOZ, AMOZ, AHD, SEM); Result: Detected: AOZ 1.6 ug/kg; Limit: Not detected")],
                         "seafood", "eu")
    assert [c.status for c in bad] == ["error"]
    good = labtests.check([_cert("Parameter: Chloramphenicol; Result: Not detected; Limit: Not detected\nNitrofurans: ND")],
                          "seafood", "eu")
    assert all(c.status == "pass" for c in good) and len(good) == 2
    eto = labtests.check([_cert("Ethylene oxide: 0.35 mg/kg")], "spices", "eu")
    assert eto[0].status == "error"
    assert labtests.check([_cert("Ethylene oxide: 0.05 mg/kg")], "spices", "eu")[0].status == "pass"


def _lc(**over):
    from app.schemas import ExtractedField, ParsedDocument
    raw = {"doc_number": "HVB-LC-26-07731", "expiry_date": "15-Oct-2099", "latest_shipment_date": "20-Sep-2026",
           "total_amount": "102,000.00", "currency": "USD", "amount_tolerance": "05/05",
           "description": "FROZEN RAW HEADLESS SHELL-ON VANNAMEI SHRIMP (LITOPENAEUS VANNAMEI), SIZE 26/30, IQF",
           "incoterms": "CFR ROTTERDAM", "port_of_loading": "COCHIN, INDIA", "port_of_discharge": "ROTTERDAM, NETHERLANDS",
           "presentation_days": "21 DAYS", "documents_required": "COMMERCIAL INVOICE; PACKING LIST; BILLS OF LADING"} | over
    fields = {k: ExtractedField(key=k, raw=v, evidence=v, verified=True) for k, v in raw.items()}
    return ParsedDocument(filename="lc.pdf", doc_type="letter_of_credit", text="", ocr_used=False, fields=fields)


def test_letter_of_credit_checks():
    from app import lc
    flags = {c.id: c.status for c in lc.check(clean_docs() + [_lc()])}
    assert flags["lc:shipment_date"] == "error"            # SB 23 Sep after latest shipment 20 Sep
    assert flags["lc:description"] == "error"              # 31/40 on invoice vs 26/30 in LC
    assert flags["lc:amount"] == "pass"                    # 102,000 within 102,000 + 5%
    assert flags["lc:port_of_discharge"] == "pass"
    assert flags["lc:documents_unchecked"] == "warning"    # bill of lading is required but not read
    ok = {c.id: c.status for c in lc.check(clean_docs() + [_lc(latest_shipment_date="30-Sep-2026",
          description="FROZEN RAW HEADLESS SHELL-ON VANNAMEI SHRIMP (LITOPENAEUS VANNAMEI), SIZE 31/40, IQF")])}
    assert ok["lc:shipment_date"] == "pass" and ok["lc:description"] == "pass"


def test_upload_content_checks(tmp_path):
    import pytest
    from app import uploads
    fake = tmp_path / "notes.pdf"
    fake.write_text("just text")
    with pytest.raises(uploads.UploadError):
        uploads.check_content(fake, "notes.pdf")
    real = tmp_path / "invoice.pdf"
    real.write_bytes(open("data/demo/errors/02_commercial_invoice.pdf", "rb").read())
    uploads.check_content(real, "invoice.pdf")   # a genuine PDF passes


def test_unrecognised_and_duplicate_files_are_flagged():
    from app.report import build
    from app.schemas import ParsedDocument
    docs = errors_docs()
    docs.append(ParsedDocument(filename="lunch_menu.pdf", doc_type=None, text="Team lunch menu", ocr_used=False, fields={}))
    docs.append(docs[1].model_copy(update={"filename": "old_invoice.pdf"}))
    flags = {c["id"]: c["status"] for c in build(docs)["checks"]}
    assert flags["intake:unrecognised"] == "warning"
    assert flags["intake:duplicate:commercial_invoice"] == "warning"


def test_format_edge_cases():
    assert N.number("12.000,50") == 12000.5              # European number style
    assert N.weight_kg("26,455", "LBS") == round(26455 * 0.45359237, 3)
    assert N.currency("US$") == N.currency("usd") == "USD"
    assert N.hs_equal(N.hs_code("0306"), N.hs_code("03061720"))       # 4-digit heading on a certificate
    assert not N.hs_equal(N.hs_code("0307"), N.hs_code("03061720"))


def test_known_but_unsupported_document_is_named():
    from app.report import build
    from app.schemas import ParsedDocument
    docs = errors_docs() + [ParsedDocument(filename="bl.pdf", doc_type=None, text="BILL OF LADING\nShipper ...",
                                           ocr_used=False, fields={})]
    checks = {c["id"]: c for c in build(docs)["checks"]}
    assert "intake:unsupported:bl.pdf" in checks and "intake:unrecognised" not in checks


def test_unreadable_file_is_reported():
    from app.report import build
    checks = build(errors_docs(), failed=[("pl.pdf", "Failed to connect to Ollama")])["checks"]
    assert checks[0]["id"] == "intake:read_failed:pl.pdf" and "not running" in checks[0]["message"]


def test_final_verdict_after_overrides():
    from app.report import build, final_verdict
    r = build(errors_docs())
    flags = [c for c in r["checks"] if c["status"] in ("error", "warning")]
    all_overridden = {c["id"]: {"decision": "overridden"} for c in flags}
    assert final_verdict(r, all_overridden)["verdict"] == "ready"
    one_confirmed = dict(all_overridden, **{flags[0]["id"]: {"decision": "confirmed"}})
    assert final_verdict(r, one_confirmed)["verdict"] == "blocked"
    assert final_verdict(r, {})["verdict"] == "blocked"


def test_label_is_not_a_company_name():
    assert N.company("Buyer") is None and N.company("Consignee:") is None
    assert N.company("NordMark Lebensmittel GmbH") == "NORDMARK LEBENSMITTEL GMBH"


def test_swapped_invoice_and_po_references():
    from tests.fixtures import ERRORS_RAW, make_docs
    raw = {t: dict(v) for t, v in ERRORS_RAW.items()}
    raw["packing_list"]["invoice_number"], raw["packing_list"]["po_number"] = "NHF-PO-2026-0418", "KME/EXP/26-27/0093"
    from app.report import build
    checks = {c["id"]: c for c in build(make_docs(raw))["checks"]}
    assert "look swapped" in checks["cross:invoice_ref"]["message"]


def test_verified_value_wins_a_tie():
    from tests.fixtures import ERRORS_RAW, make_docs
    from app.rules import cross_document
    raw = {"packing_list": dict(ERRORS_RAW["packing_list"]), "shipping_bill": dict(ERRORS_RAW["shipping_bill"])}
    raw["shipping_bill"]["gross_weight"] = "13,500.000"
    docs = make_docs(raw)
    docs[0].fields["gross_weight"].verified = False       # packing list value not found in its source
    check = next(c for c in cross_document(docs) if c.id == "cross:gross_weight")
    assert [v.doc_type for v in check.values if v.outlier] == ["packing_list"]
