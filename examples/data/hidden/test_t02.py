from decimal import Decimal

import pytest

from unitcraft import Quantity, format_quantity


@pytest.mark.parametrize(
    "value, unit, expected",
    [
        ("-999.5", "m", "-999.5 m"),
        ("-9999.5", "m", "-9,999.5 m"),
        ("-1234.5", "m", "-1,234.5 m"),
        ("-1234567.5", "kg", "-1,234,567.5 kg"),
    ],
)
def test_negative_values_group_like_positive(value, unit, expected):
    assert format_quantity(Quantity(Decimal(value), unit), places=1) == expected
