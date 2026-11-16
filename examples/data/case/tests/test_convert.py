from decimal import Decimal

import pytest

from unitcraft import IncompatibleUnitsError, UnknownUnitError, convert, parse_quantity


def test_kilometres_to_metres():
    q = convert(parse_quantity("1 km"), "m")
    assert (q.value, q.unit) == (Decimal("1000"), "m")


def test_feet_to_metres():
    q = convert(parse_quantity("3 ft"), "m")
    assert (q.value, q.unit) == (Decimal("0.9144"), "m")


def test_hours_to_seconds():
    q = convert(parse_quantity("1 h"), "s")
    assert (q.value, q.unit) == (Decimal("3600"), "s")


def test_minutes_are_minutes():
    q = convert(parse_quantity("2 min"), "s")
    assert (q.value, q.unit) == (Decimal("120"), "s")


def test_prefixed_unit_still_works():
    q = convert(parse_quantity("2 mm"), "m")
    assert (q.value, q.unit) == (Decimal("0.002"), "m")


def test_length_to_mass_is_refused():
    with pytest.raises(IncompatibleUnitsError):
        convert(parse_quantity("1 m"), "kg")


def test_unknown_unit_is_refused():
    with pytest.raises(UnknownUnitError):
        convert(parse_quantity("1 furlong"), "m")
