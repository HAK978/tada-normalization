"""Numbers survive a read and a write unchanged, which float parsing can't guarantee."""
from decimal import Decimal

import pytest

from normalization import exactjson


def test_round_trip_keeps_every_digit():
    text = '{"rate": 0.123456789123456789, "amount": 1573.39, "count": 3, "items": [59.375, -0.10]}'
    value = exactjson.loads(text)
    assert value["rate"] == Decimal("0.123456789123456789") and value["count"] == 3
    out = exactjson.dumps(value)
    assert "0.123456789123456789" in out and "1573.39" in out and "-0.10" in out
    assert exactjson.loads(out) == value


def test_non_finite_and_unknown_types_are_refused():
    with pytest.raises(TypeError):
        exactjson.dumps({"x": Decimal("NaN")})
    with pytest.raises(TypeError):
        exactjson.dumps({"x": object()})
