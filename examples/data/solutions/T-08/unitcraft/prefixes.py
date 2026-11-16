"""SI prefixes, and the split of a unit symbol into a prefix and a base."""
from decimal import Decimal

from unitcraft.units import UNITS

PREFIXES: dict[str, Decimal] = {
    "k": Decimal(1000),
    "c": Decimal("0.01"),
    "m": Decimal("0.001"),
}


def split_prefix(unit: str) -> tuple[str, str]:
    """Split a unit symbol into ``(prefix, base)``: ``"km"`` gives ``("k", "m")``.

    A symbol with no prefix gives ``("", unit)``. A whole unit name wins over a
    prefix split, so ``"min"`` is minutes, not milli-inches.
    """
    if unit in UNITS:
        return "", unit
    if unit[:1] in PREFIXES and unit[1:]:
        return unit[0], unit[1:]
    return "", unit
