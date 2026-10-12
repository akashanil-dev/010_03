"""Invoice arithmetic for goods priced per kg, MT, piece, dozen, metre or package. Run: pytest -q"""

import pytest

from app import normalize as N
from app.rules import arithmetic
from tests.fixtures import make_docs


def invoice_check(**raw):
    raw.setdefault("net_weight_unit", "kg")
    checks = arithmetic(make_docs({"commercial_invoice": raw}))
    return next(c for c in checks if c.id == "math:invoice")


@pytest.mark.parametrize("raw,dim,factor", [
    ("USD/MT", "weight", 1000), ("per kg", "weight", 1), ("PCS", "piece", 1), ("per dozen", "piece", 12),
    ("Pairs", "pair", 1), ("Sq. M", "area", 1), ("per carton", "package", 1), ("12,000 KGS", "weight", 1),
    ("NOS", "piece", 1), ("Metric Ton", "weight", 1000),
])
def test_units_are_recognised(raw, dim, factor):
    u = N.unit(raw)
    assert (u.dim, u.factor) == (dim, factor)


def test_unknown_units():
    assert N.unit("not stated") is None and N.unit(None) is None and N.unit("as per contract") is None


def test_priced_per_piece_is_not_a_false_flag():
    """Coir mats: 4,800 pieces at $3.25 each. Per kg (7,680 kg) it would look badly wrong."""
    c = invoice_check(quantity="4,800", quantity_unit="PCS", unit_price="3.25", price_unit="per piece",
                      total_amount="15,600.00", net_weight="7,680")
    assert c.status == "pass" and c.message.startswith("4,800 pcs × 3.25 = 15,600")


def test_priced_per_piece_catches_a_wrong_total():
    c = invoice_check(quantity="4,800", quantity_unit="PCS", unit_price="3.25", price_unit="per piece",
                      total_amount="15,060.00", net_weight="7,680")
    assert c.status == "error" and "4,800 pcs × 3.25 = 15,600" in c.message and "15,060" in c.message


def test_price_unit_alone_is_enough():
    """The unit is only on the price column ('USD per pc'); the quantity has no unit of its own."""
    c = invoice_check(quantity="2,000", unit_price="1.10", price_unit="USD per pc", total_amount="2,200.00")
    assert c.status == "pass"


def test_quantity_in_pieces_priced_per_dozen():
    c = invoice_check(quantity="4,800", quantity_unit="PCS", unit_price="30.00", price_unit="per dozen",
                      total_amount="12,000.00")
    assert c.status == "pass" and "400 dozen" in c.message


def test_weight_priced_per_tonne():
    """Spices: 12 MT at $4,250 per MT, with the weight given in kg on the invoice."""
    c = invoice_check(net_weight="12,000", unit_price="4,250", price_unit="USD/MT", total_amount="51,000.00")
    assert c.status == "pass" and "12 MT" in c.message


def test_price_per_carton_uses_the_carton_count():
    c = invoice_check(cartons="240", unit_price="65.00", price_unit="per carton", total_amount="15,600.00")
    assert c.status == "pass"


def test_quantity_and_price_in_different_kinds_of_unit_is_skipped():
    c = invoice_check(quantity="7,680", quantity_unit="KGS", unit_price="3.25", price_unit="per piece",
                      total_amount="15,600.00")
    assert c.status == "skipped" and "price is per piece" in c.message


def test_unknown_basis_is_only_a_warning():
    """A quantity without any unit, and no price basis: either reading may be meant, so a mismatch is not an error."""
    ok = invoice_check(quantity="4,800", unit_price="3.25", total_amount="15,600.00", net_weight="7,680")
    assert ok.status == "pass"
    bad = invoice_check(quantity="4,800", unit_price="3.25", total_amount="15,060.00", net_weight="7,680")
    assert bad.status == "warning" and "could not tell what the price is charged per" in bad.message


def test_wrong_fob_is_always_an_error():
    c = invoice_check(quantity="4,800", unit_price="3.25", total_amount="15,600.00", freight="1,450.00",
                      fob_value="14,000.00")
    assert c.status == "error" and "FOB" in c.message


def test_readings_without_quantity_stay_per_kg():
    """Documents read before quantities were extracted keep the original per-kg arithmetic."""
    assert invoice_check(net_weight="12,000", unit_price="8.50", total_amount="102,000.00").status == "pass"
    assert invoice_check(net_weight="12,000", unit_price="8.50", total_amount="101,200.00").status == "error"


def test_source_check_accepts_other_number_formats_and_units():
    from app.extract import locate
    text = "Quantity: 4,800; Unit: PCS; USD per piece: 3.25; Amount USD: 15,060.00\nNet weight 7,680.00 kg"
    assert locate("15060.00", text)[1] and locate("7680", text)[1] and locate("4800", text)[1]
    assert "15,060.00" in locate("15060.00", text)[0]
    assert locate("per piece", text, unit=True)[1] and locate("KGS", text, unit=True)[1]
    assert not locate("15500.00", text)[1]                 # a number the document does not contain
    assert not locate("per dozen", text, unit=True)[1]     # a unit the document does not use
