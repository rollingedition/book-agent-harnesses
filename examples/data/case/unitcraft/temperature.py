"""Affine conversions between Celsius, Fahrenheit and kelvin."""
from decimal import Decimal

from unitcraft.quantity import Quantity

KELVIN_OFFSET = Decimal("273")


def _to_kelvin(value: Decimal, unit: str) -> Decimal:
    if unit == "C":
        return value + KELVIN_OFFSET
    if unit == "F":
        return (value - 32) * 5 / 9 + KELVIN_OFFSET
    return value


def _from_kelvin(kelvin: Decimal, unit: str) -> Decimal:
    if unit == "C":
        return kelvin - KELVIN_OFFSET
    if unit == "F":
        return (kelvin - KELVIN_OFFSET) * 9 / 5 + 32
    return kelvin


def convert_temperature(q: Quantity, unit: str) -> Quantity:
    """Convert a temperature quantity to another temperature unit."""
    kelvin = _to_kelvin(q.value, q.unit)
    return Quantity(_from_kelvin(kelvin, unit), unit)
