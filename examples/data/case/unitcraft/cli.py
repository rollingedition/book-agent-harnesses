"""Command line: ``python -m unitcraft convert VALUE FROM TO``."""
import sys

from unitcraft.convert import convert
from unitcraft.parse import parse_quantity

USAGE = "usage: python -m unitcraft convert VALUE FROM TO"


def main(argv: list[str] | None = None) -> int:
    """Run the command line and return the exit code."""
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 4 or args[0] != "convert":
        print(USAGE, file=sys.stderr)
        return 2
    _, value, source, target = args
    result = convert(parse_quantity(f"{value} {source}"), target)
    print(result.value)
    return 0
