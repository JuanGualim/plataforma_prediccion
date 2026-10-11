"""Huella digital de un dataset: identifica con exactitud qué datos se usaron.

Dos conjuntos con el mismo contenido producen el mismo hash, sin importar el orden de las
filas; un solo valor distinto produce un hash completamente distinto.
"""

import hashlib
from collections.abc import Sequence

import pandas as pd


def dataframe_fingerprint(df: pd.DataFrame, columns: Sequence[str], sort_by: Sequence[str]) -> str:
    canonical = df[list(columns)].sort_values(list(sort_by), kind="stable")
    payload = canonical.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%S.%f%z")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
