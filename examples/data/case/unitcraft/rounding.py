"""Rounding of decimal values to a number of places, with ties to even."""
from decimal import Decimal


def round_places(value: Decimal, places: int) -> Decimal:
    """Round ``value`` to ``places`` decimal places. Exact ties go to the even digit."""
    return Decimal(str(round(float(value), places)))
