"""format_quantity: write a quantity as text, such as ``3.50 kg``."""
from unitcraft.quantity import Quantity
from unitcraft.rounding import round_places


def format_quantity(q: Quantity, places: int = 2) -> str:
    """Format ``q`` with ``places`` decimal places and thousands commas, then its unit."""
    rounded = round_places(q.value, places)

    sign = "-" if q.value < 0 else ""

    if rounded < 0:
        body = f"{-rounded:.{places}f}"
    else:
        body = f"{rounded:,.{places}f}"
    whole, _, frac = body.partition(".")

    frac = frac.rstrip("0")
    separator = "."

    text = f"{whole}{separator}{frac}" if places else whole

    return f"{sign}{text} {q.unit}"
