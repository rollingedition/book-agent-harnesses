"""Rounding of decimal values to a number of places, with ties to even."""
from decimal import ROUND_HALF_EVEN, Decimal


def round_places(value: Decimal, places: int) -> Decimal:
    """Round ``value`` to ``places`` decimal places. Exact ties go to the even digit."""
    step = Decimal(1).scaleb(-places)
    return value.quantize(step, rounding=ROUND_HALF_EVEN)
