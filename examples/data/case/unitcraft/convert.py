"""convert: change a quantity to another unit of the same dimension."""
from decimal import Decimal

from unitcraft.errors import IncompatibleUnitsError, UnknownUnitError
from unitcraft.prefixes import PREFIXES, split_prefix
from unitcraft.quantity import Quantity
from unitcraft.temperature import convert_temperature
from unitcraft.units import UNITS


def resolve(symbol: str) -> tuple[str, Decimal | None]:
    """Return the dimension of a unit symbol and its factor to the base unit.

    The factor is ``None`` for temperature units, which convert affinely.
    """
    prefix, base = split_prefix(symbol)
    unit = UNITS.get(base)
    if unit is None or (prefix and unit.factor is None):
        raise UnknownUnitError(f"unknown unit: {symbol}")
    if unit.factor is None:
        return unit.dimension, None
    return unit.dimension, PREFIXES.get(prefix, Decimal(1)) * unit.factor


def convert(q: Quantity, unit: str) -> Quantity:
    """Convert ``q`` to ``unit``. Raises IncompatibleUnitsError across dimensions."""
    dimension, source = resolve(q.unit)
    target_dimension, target = resolve(unit)
    if dimension != target_dimension:
        raise IncompatibleUnitsError(f"cannot convert {q.unit} to {unit}")
    if dimension == "temperature":
        return convert_temperature(q, unit)
    return Quantity(q.value * source / target, unit)
