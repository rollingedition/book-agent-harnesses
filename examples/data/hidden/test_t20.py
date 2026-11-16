from decimal import Decimal

from unitcraft import Quantity, format_quantity


def test_zero_places_has_no_point():
    assert format_quantity(Quantity(Decimal("3"), "kg"), places=0) == "3 kg"


def test_zero_places_rounds_half_even():
    assert format_quantity(Quantity(Decimal("3.5"), "kg"), places=0) == "4 kg"


def test_zero_places_keeps_the_sign():
    assert format_quantity(Quantity(Decimal("-2"), "kg"), places=0) == "-2 kg"
