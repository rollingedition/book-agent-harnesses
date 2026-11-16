from decimal import Decimal

from unitcraft import Quantity, format_quantity


def make(text, unit):
    return Quantity(Decimal(text), unit)


def test_pads_to_two_places():
    assert format_quantity(make("3.5", "kg")) == "3.50 kg"


def test_groups_thousands():
    assert format_quantity(make("1234.5", "m"), places=1) == "1,234.5 m"


def test_negative_keeps_thousands_separator():
    assert format_quantity(make("-1234.5", "m"), places=1) == "-1,234.5 m"


def test_tiny_negative_has_no_sign():
    assert not format_quantity(make("-0.001", "m")).startswith("-")


def test_zero_places_has_no_point():
    assert format_quantity(make("3", "kg"), places=0) == "3 kg"
