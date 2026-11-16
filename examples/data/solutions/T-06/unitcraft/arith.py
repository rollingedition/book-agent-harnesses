"""Arithmetic on quantities. The result is in the unit of the first operand."""
from collections.abc import Iterable
from decimal import Decimal

from unitcraft.convert import convert
from unitcraft.quantity import Quantity


def add(a: Quantity, b: Quantity) -> Quantity:
    """Add ``b`` to ``a``. ``b`` is converted to the unit of ``a`` first."""
    return Quantity(a.value + convert(b, a.unit).value, a.unit)


def sum_quantities(qs: Iterable[Quantity], unit: str) -> Quantity:
    """Add every quantity in ``qs`` in ``unit``. An empty input gives zero in ``unit``."""
    total = Quantity(Decimal(0), unit)
    for q in qs:
        total = add(total, q)
    return total
