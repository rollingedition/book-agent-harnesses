from decimal import Decimal

from unitcraft import parse_quantity


def test_trailing_spaces_parse():
    q = parse_quantity("5 kg ")
    assert (q.value, q.unit) == (Decimal("5"), "kg")


def test_leading_spaces_parse():
    q = parse_quantity("  5 kg")
    assert (q.value, q.unit) == (Decimal("5"), "kg")
