"""Row order and layout for tables of quantities."""
from collections.abc import Iterable
from decimal import Decimal

from unitcraft.convert import resolve
from unitcraft.rounding import round_places
from unitcraft.quantity import Quantity


def row_key(q: Quantity) -> tuple[str, str, Decimal]:
    """Sort key for a table row: dimension, then unit symbol, then value."""
    dimension, _ = resolve(q.unit)
    return dimension, q.unit, q.value


def format_table(qs: Iterable[Quantity]) -> str:
    """One line per quantity, sorted by row_key, with the decimal points aligned."""
    rows = sorted(qs, key=row_key)
    texts = [f"{round_places(q.value, 2):,.2f}" for q in rows]
    width = max((len(t) for t in texts), default=0)
    return "\n".join(f"{t.rjust(width)} {q.unit}" for t, q in zip(texts, rows))
