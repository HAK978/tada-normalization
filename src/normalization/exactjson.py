"""JSON that keeps numbers exact: decimals parse to Decimal and are written back unchanged.

json.loads turns 0.123456789123456789 into a float, and no later Decimal conversion can
recover the digits it dropped. Provider responses and fixtures are therefore read with
loads() and written with dumps(), which emits a Decimal as the same plain JSON number.
"""

from __future__ import annotations

import json
import re
import secrets
from decimal import Decimal
from typing import Any

# Decimals are written as marked strings, then unquoted. The marker carries a random per-call token, so
# a source string can't be mistaken for one, and only a well-formed number is ever unquoted.
_NUMBER = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"


def loads(text: str) -> Any:
    return json.loads(text, parse_float=Decimal)


def dumps(value: Any, **kwargs: Any) -> str:
    token = f"exact-number-{secrets.token_hex(8)}:"

    def mark(item: Any) -> str:
        if isinstance(item, Decimal) and item.is_finite():
            return token + str(item)
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    return re.sub(f'"{re.escape(token)}({_NUMBER})"', r"\1", json.dumps(value, default=mark, **kwargs))
