from decimal import Decimal

from unitcraft import convert, parse_quantity
from unitcraft.prefixes import split_prefix


def test_minutes_are_minutes():
    q = convert(parse_quantity("2 min"), "s")
    assert (q.value, q.unit) == (Decimal("120"), "s")


def test_millimetres_still_parse():
    q = convert(parse_quantity("2 mm"), "m")
    assert (q.value, q.unit) == (Decimal("0.002"), "m")


def test_whole_unit_names_are_not_split():
    assert split_prefix("min") == ("", "min")
    assert split_prefix("kft") == ("k", "ft")
