"""The Quantity type: a decimal value and the symbol of its unit."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Quantity:
    """A value with its unit, for example ``Quantity(Decimal("3.5"), "kg")``."""

    value: Decimal
    unit: str
