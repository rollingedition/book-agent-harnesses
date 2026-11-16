from decimal import Decimal

import pytest

from unitcraft import IncompatibleUnitsError, Quantity
from unitcraft.arith import add


def make(text, unit):
    return Quantity(Decimal(text), unit)


def test_add_converts_the_second_operand():
    r = add(make("1", "kg"), make("500", "g"))
    assert (r.value, r.unit) == (Decimal("1.5"), "kg")


def test_add_refuses_mixed_dimensions():
    with pytest.raises(IncompatibleUnitsError):
        add(make("1", "kg"), make("1", "m"))
