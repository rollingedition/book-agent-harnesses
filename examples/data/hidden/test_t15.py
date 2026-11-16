from decimal import Decimal

from unitcraft import Quantity, format_quantity


def test_half_even_rounding_is_kept():
    assert format_quantity(Quantity(Decimal("0.125"), "kg")) == "0.12 kg"
    assert format_quantity(Quantity(Decimal("0.135"), "kg")) == "0.14 kg"


def test_binary_float_edge_rounds_to_even_decimal():
    assert format_quantity(Quantity(Decimal("2.675"), "kg")) == "2.68 kg"
