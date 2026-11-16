from decimal import Decimal

from unitcraft import Quantity, format_quantity


def test_pads_to_two_places():
    assert format_quantity(Quantity(Decimal("3.5"), "kg")) == "3.50 kg"
    assert format_quantity(Quantity(Decimal("0"), "kg")) == "0.00 kg"
    assert format_quantity(Quantity(Decimal("12"), "kg")) == "12.00 kg"
