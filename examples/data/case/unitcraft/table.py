"""Row order for tables of quantities."""
from decimal import Decimal

from unitcraft.convert import resolve
from unitcraft.quantity import Quantity


def row_key(q: Quantity) -> tuple[str, str, Decimal]:
    """Sort key for a table row: dimension, then unit symbol, then value."""
    dimension, _ = resolve(q.unit)
    return dimension, q.unit, q.value
