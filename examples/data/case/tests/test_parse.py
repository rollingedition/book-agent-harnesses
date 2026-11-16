from decimal import Decimal

import pytest

from unitcraft import ParseError, parse_quantity


def test_parses_decimal_value_and_unit():
    q = parse_quantity("3.5 kg")
    assert (q.value, q.unit) == (Decimal("3.5"), "kg")


def test_parses_negative_value():
    q = parse_quantity("-2 m")
    assert (q.value, q.unit) == (Decimal("-2"), "m")


def test_thousands_commas_are_accepted():
    q = parse_quantity("1,000 m")
    assert (q.value, q.unit) == (Decimal("1000"), "m")


def test_wrong_group_size_is_rejected():
    with pytest.raises(ParseError):
        parse_quantity("1,00 m")


def test_text_without_a_number_is_rejected():
    with pytest.raises(ParseError):
        parse_quantity("kg")
