from decimal import Decimal

import pytest

from unitcraft import IncompatibleUnitsError, Quantity, convert


def test_metres_are_not_convertible_to_kilograms():
    with pytest.raises(IncompatibleUnitsError):
        convert(Quantity(Decimal("1"), "m"), "kg")
