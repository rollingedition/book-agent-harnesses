from decimal import Decimal

import pytest

from unitcraft import IncompatibleUnitsError, Quantity, sum_quantities


def test_sum_converts_each_operand():
    qs = [Quantity(Decimal("1"), "kg"), Quantity(Decimal("500"), "g")]
    r = sum_quantities(qs, "g")
    assert (r.value, r.unit) == (Decimal("1500"), "g")


def test_empty_input_is_zero_in_the_unit():
    r = sum_quantities([], "m")
    assert (r.value, r.unit) == (Decimal("0"), "m")


def test_mixed_dimensions_raise():
    with pytest.raises(IncompatibleUnitsError):
        sum_quantities([Quantity(Decimal("1"), "kg"), Quantity(Decimal("1"), "m")], "kg")
