from decimal import Decimal

from unitcraft import Quantity
from unitcraft.table import row_key


def make(text, unit):
    return Quantity(Decimal(text), unit)


def test_rows_sort_by_dimension_then_unit_then_value():
    rows = [make("2", "s"), make("1", "m"), make("3", "kg"), make("1.5", "m")]
    ordered = sorted(rows, key=row_key)
    assert [(q.value, q.unit) for q in ordered] == [
        (Decimal("1"), "m"),
        (Decimal("1.5"), "m"),
        (Decimal("3"), "kg"),
        (Decimal("2"), "s"),
    ]
