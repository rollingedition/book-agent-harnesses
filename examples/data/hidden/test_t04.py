from decimal import Decimal

from unitcraft import convert, parse_quantity
from unitcraft.units import UNITS


def test_inch_is_a_length_unit():
    assert UNITS["in"].dimension == "length"


def test_inch_parses_and_converts():
    q = convert(parse_quantity("2 in"), "cm")
    assert (q.value, q.unit) == (Decimal("5.08"), "cm")
