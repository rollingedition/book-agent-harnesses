from decimal import Decimal

from unitcraft import convert, parse_quantity


def test_zero_celsius_is_273_15_kelvin():
    q = convert(parse_quantity("0 C"), "K")
    assert (q.value, q.unit) == (Decimal("273.15"), "K")


def test_offset_is_exact_at_several_values():
    assert convert(parse_quantity("-273.15 C"), "K").value == Decimal("0")
    assert convert(parse_quantity("100 C"), "K").value == Decimal("373.15")
    assert convert(parse_quantity("-40 C"), "K").value == Decimal("233.15")


def test_minus_forty_fahrenheit_is_minus_forty_celsius():
    assert convert(parse_quantity("-40 F"), "C").value == Decimal("-40")
