from decimal import Decimal

from unitcraft import Quantity, convert, parse_quantity
from unitcraft.units import UNITS


def test_yard_is_a_length_unit():
    assert UNITS["yd"].dimension == "length"


def test_yard_to_foot():
    q = convert(parse_quantity("1 yd"), "ft")
    assert (q.value, q.unit) == (Decimal("3"), "ft")


def test_yard_round_trips_through_every_length_unit():
    for unit in ["m", "km", "cm", "mm", "ft"]:
        there = convert(Quantity(Decimal("1"), "yd"), unit)
        back = convert(there, "yd")
        assert back.value == Decimal("1"), unit
