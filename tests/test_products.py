"""Product detection and product-specific readiness items. Run: pytest -q"""

import pytest

from app import readiness
from tests.fixtures import make_docs


def build(hs, description="Goods", text="", pod="Hamburg (DEHAM)"):
    docs = make_docs({"commercial_invoice": {"hs_code": hs, "description": description, "port_of_discharge": pod}})
    docs[0].text = text
    return readiness.build(docs)


def items(result):
    return {i["item"]: i for i in result["items"]}


@pytest.mark.parametrize("hs,product", [
    ("03061720", "seafood"), ("16052100", "seafood"),
    ("09011112", "coffee"), ("09024010", "tea"),        # chapter 09, but not spices
    ("09042110", "spices"), ("09083110", "spices"),
    ("08013220", "cashew"), ("08013100", "cashew"),
    ("08011100", "general"),                            # coconuts share heading 0801 with cashew
    ("57022010", "coir"), ("53081010", "coir"),
    ("40012100", "rubber"), ("62052000", "general"),
])
def test_product_from_hs_code(hs, product):
    assert build(hs)["product"] == product


def test_coir_recognised_from_the_description():
    assert build("56079090", description="Coir rope, 3 strand, 12 mm")["product"] == "coir"


@pytest.mark.parametrize("hs,board", [
    ("09024010", "Tea Board registration"), ("09011112", "Coffee Board registration"),
    ("08013220", "CEPCI registration (Cashew Export Promotion Council)"), ("57022010", "Coir Board registration"),
    ("40012100", "Rubber Board registration"), ("09042110", "Spices Board registration (CRES)"),
])
def test_each_product_asks_for_its_board_registration(hs, board):
    it = items(build(hs))
    assert it[board]["status"] == "check"


def test_registration_shown_on_the_invoice_is_ok():
    it = items(build("09024010", text="Exporter: Highrange Teas | Tea Board Reg. No. TB/EXP/0042"))
    assert it["Tea Board registration"]["status"] == "ok"


def test_plant_products_need_a_phytosanitary_check_and_coir_a_fumigation_check():
    assert "Phytosanitary certificate" in items(build("08013220"))
    assert "Fumigation or phytosanitary certificate" in items(build("57022010"))
    assert "Phytosanitary certificate" not in items(build("57022010"))


def test_eudr_for_coffee_and_rubber_to_the_eu_only():
    eudr = "EUDR due-diligence statement and plot geolocation"
    coffee = items(build("09011112"))[eudr]
    assert coffee["group"] == "Coffee to the EU" and "covers coffee" in coffee["detail"]
    assert items(build("40012100"))[eudr]["group"] == "Natural rubber to the EU"
    assert eudr not in items(build("09011112", pod="New York (USNYC)"))
    assert eudr not in items(build("09024010"))   # tea is not covered by the EUDR


def test_health_certificate_is_expected_for_food_only():
    from app.rules import compliance

    def recommended_check(hs):
        docs = make_docs({"commercial_invoice": {"hs_code": hs}, "packing_list": {}, "shipping_bill": {},
                          "purchase_order": {}, "certificate_of_origin": {}})
        return next(c for c in compliance(docs) if c.id == "comp:recommended_docs")

    assert recommended_check("57022010").status == "pass"                      # coir mats: no health certificate needed
    food = recommended_check("08013220")
    assert food.status == "warning" and "health" in food.message.lower()                # cashew: food


def test_coir_demo_gives_exactly_its_planted_pricing_error():
    """Recorded Granite output for the coir set: priced per piece, so no per-kg false flags."""
    from app.report import build as build_report
    from tests.fixtures import coir_docs

    rep = build_report(coir_docs())
    flags = {c["id"]: c for c in rep["checks"] if c["status"] in ("error", "warning")}
    assert list(flags) == ["math:invoice"] and flags["math:invoice"]["status"] == "error"
    assert "4,800 pcs × 3.25 = 15,600" in flags["math:invoice"]["message"]
    assert rep["readiness"]["product"] == "coir"
    assert "Quality / Health Certificate" not in [c["doc_name"] for c in rep["coverage"]]
