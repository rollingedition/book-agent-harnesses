from decimal import Decimal

import pytest

from unitcraft import ParseError, parse_quantity


def test_leading_plus_sign_parses():
    q = parse_quantity("+3 kg")
    assert (q.value, q.unit) == (Decimal("3"), "kg")


def test_plus_then_space_is_refused():
    with pytest.raises(ParseError):
        parse_quantity("+ 3 kg")


def test_plus_then_minus_is_refused():
    with pytest.raises(ParseError):
        parse_quantity("+-3 kg")
