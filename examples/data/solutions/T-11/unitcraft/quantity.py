"""The Quantity type: a decimal value and the symbol of its unit."""
from dataclasses import dataclass
from decimal import Decimal

from unitcraft.errors import UnitError


@dataclass(frozen=True, eq=False)
class Quantity:
    """A value with its unit, for example ``Quantity(Decimal("3.5"), "kg")``.

    Equality compares converted values, so ``1 kg`` equals ``1000 g``.
    """

    value: Decimal
    unit: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Quantity):
            return NotImplemented
        if self.unit == other.unit:
            return self.value == other.value
        try:
            return _base(self) == _base(other)
        except UnitError:
            return False

    def __hash__(self) -> int:
        try:
            return hash(_base(self))
        except UnitError:
            return hash((self.value, self.unit))


def _base(q: Quantity) -> tuple[str, Decimal]:
    """Return the value of ``q`` in the base unit of its dimension, with that unit."""
    from unitcraft.convert import to_base  # convert imports this module, so import late

    base = to_base(q)
    return base.unit, base.value
