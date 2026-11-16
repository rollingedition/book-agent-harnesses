"""Arithmetic on quantities. The result is in the unit of the first operand."""
from unitcraft.convert import convert
from unitcraft.quantity import Quantity


def add(a: Quantity, b: Quantity) -> Quantity:
    """Add ``b`` to ``a``. ``b`` is converted to the unit of ``a`` first."""
    return Quantity(a.value + convert(b, a.unit).value, a.unit)
