from decimal import Decimal
from pathlib import Path

from unitcraft import Quantity, format_table

ROWS = [
    Quantity(Decimal("12.5"), "m"),
    Quantity(Decimal("1200"), "m"),
    Quantity(Decimal("3"), "kg"),
    Quantity(Decimal("-40"), "C"),
    Quantity(Decimal("90"), "s"),
    Quantity(Decimal("2"), "h"),
]


def readme_table():
    text = (Path(__file__).resolve().parent / "README.md").read_text(encoding="utf-8")
    section = text.split("## Table layout", 1)[1]
    block = section.split("```text", 1)[1].split("```", 1)[0]
    return block.strip("\n")


def test_table_is_the_layout_in_the_readme():
    assert format_table(ROWS) == readme_table()


def test_one_line_per_quantity_in_row_order():
    lines = format_table(list(reversed(ROWS))).splitlines()
    assert len(lines) == len(ROWS)
    assert lines[0].endswith(" m") and "12.50" in lines[0]
