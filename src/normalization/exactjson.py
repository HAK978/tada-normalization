"""JSON that keeps numbers exact: decimals parse to Decimal and are written back unchanged.

json.loads turns 0.123456789123456789 into a float, and no later Decimal conversion can
recover the digits it dropped. Provider responses and fixtures are therefore read with
loads() and written with dumps(), which emits a Decimal as the same plain JSON number.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

_MARK = "\u0000exact-number:"
_MARKED = re.compile(r'"\\u0000exact-number:([^"]*)"')


def loads(text: str) -> Any:
    return json.loads(text, parse_float=Decimal)


def dumps(value: Any, **kwargs: Any) -> str:
    def mark(item: Any) -> str:
        if isinstance(item, Decimal) and item.is_finite():
            return _MARK + str(item)
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    return _MARKED.sub(r"\1", json.dumps(value, default=mark, **kwargs))
