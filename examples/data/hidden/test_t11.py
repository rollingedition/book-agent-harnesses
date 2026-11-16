from decimal import Decimal

from unitcraft import Quantity


def test_equal_across_units():
    assert Quantity(Decimal("1"), "kg") == Quantity(Decimal("1000"), "g")


def test_unequal_across_dimensions():
    assert Quantity(Decimal("1"), "kg") != Quantity(Decimal("1"), "m")


def test_equal_quantities_hash_alike():
    a = Quantity(Decimal("1"), "kg")
    b = Quantity(Decimal("1000"), "g")
    assert hash(a) == hash(b)


def test_set_holds_one_member():
    items = {Quantity(Decimal("1"), "kg"), Quantity(Decimal("1000"), "g")}
    assert len(items) == 1
