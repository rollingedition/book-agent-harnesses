from decimal import Decimal

import pytest

from unitcraft import ParseError, parse_quantity


def test_commas_in_the_whole_part_parse():
    q = parse_quantity("1,000 m")
    assert (q.value, q.unit) == (Decimal("1000"), "m")
    q = parse_quantity("1,000.5 m")
    assert (q.value, q.unit) == (Decimal("1000.5"), "m")
    q = parse_quantity("12,345,678 kg")
    assert (q.value, q.unit) == (Decimal("12345678"), "kg")


def test_wrong_group_size_still_raises():
    with pytest.raises(ParseError):
        parse_quantity("1,00 m")
