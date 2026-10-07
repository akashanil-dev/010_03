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
    assert str(N.parse_date("18-09-2026")) == str(N.parse_date("18-Sep-2026")) == "2026-09-18"
