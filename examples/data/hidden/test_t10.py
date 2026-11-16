from decimal import Decimal

from unitcraft import Quantity, format_quantity


def test_values_that_round_to_zero_have_no_sign():
    for text, places in [("-0.001", 2), ("-0.004", 2), ("-0.5", 0), ("-0.0001", 3)]:
        out = format_quantity(Quantity(Decimal(text), "m"), places=places)
        assert not out.startswith("-"), out
        assert out.startswith("0"), out
