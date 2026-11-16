import unitcraft


def test_parse_quantity_still_exists():
    assert callable(unitcraft.parse_quantity)
