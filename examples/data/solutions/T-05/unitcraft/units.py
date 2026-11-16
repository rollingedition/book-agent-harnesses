"""The unit table: each symbol with its dimension and its factor to the base unit."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Unit:
    """One unit: its symbol, its dimension and its factor to the base unit.

    ``factor`` is ``None`` for temperature units, which convert affinely.
    """

    symbol: str
    dimension: str
    factor: Decimal | None


UNITS: dict[str, Unit] = {
    unit.symbol: unit
    for unit in (
        Unit("m", "length", Decimal(1)),
        Unit("km", "length", Decimal(1000)),
        Unit("cm", "length", Decimal("0.01")),
        Unit("mm", "length", Decimal("0.001")),
        Unit("ft", "length", Decimal("0.3048")),
        Unit("yd", "length", Decimal("0.9144")),
        Unit("kg", "mass", Decimal(1)),
        Unit("g", "mass", Decimal("0.001")),
        Unit("lb", "mass", Decimal("0.45359237")),
        Unit("s", "time", Decimal(1)),
        Unit("min", "time", Decimal(60)),
        Unit("h", "time", Decimal(3600)),
        Unit("C", "temperature", None),
        Unit("F", "temperature", None),
        Unit("K", "temperature", None),
    )
}
