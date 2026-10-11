"""Conversión a JSON estricto (reportes, contratos, bitácora)."""

import math
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Recursively convert to JSON-safe values (NaN/inf -> None, numpy scalars -> Python).

    JSON estricto (y el tipo JSONB de PostgreSQL) no admite NaN; una métrica indefinida
    se guarda como null.
    """
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "item"):  # escalares numpy
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
