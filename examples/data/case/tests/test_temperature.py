from decimal import Decimal

from unitcraft import convert, parse_quantity


def test_celsius_to_kelvin():
    q = convert(parse_quantity("0 C"), "K")
    assert (q.value, q.unit) == (Decimal("273.15"), "K")


def test_fahrenheit_to_celsius():
    q = convert(parse_quantity("-40 F"), "C")
    assert (q.value, q.unit) == (Decimal("-40"), "C")


def test_celsius_to_fahrenheit():
    q = convert(parse_quantity("100 C"), "F")
    assert (q.value, q.unit) == (Decimal("212"), "F")
