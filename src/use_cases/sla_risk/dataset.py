"""Construcción de los conjuntos de entrenamiento, validación y prueba del modelo de SLA.

Línea de tiempo (backtest):

    |------------ train ------------|---- validation ----|------ test ------|
                              validation_cutoff      test_cutoff        snapshot

- train: se entrena "como si hoy fuera validation_cutoff".
- validation: elige modelo y umbral "como si hoy fuera test_cutoff".
- test: se mira UNA vez, al final, con el modelo y el umbral ya decididos.

Dos protecciones contra "ver el futuro":

1. Columnas: solo entran las FEATURES, validadas contra el catálogo (T0 / T0*).
2. Filas: cada conjunto solo usa tickets cuyo resultado ya se conocía en el momento en que
   ese conjunto "se usa". Un ticket creado el día antes del corte y resuelto una semana
   después NO tenía etiqueta en el corte; usarlo sería aprender del periodo siguiente.
"""

import logging
from dataclasses import dataclass

import pandas as pd

from mlplatform.training.splits import temporal_split
from use_cases.sla_risk.fields import FEATURES, TARGET, TICKETS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Split:
    rows: pd.DataFrame  # filas completas, solo para análisis (nunca para el modelo)
    X: pd.DataFrame
    y: pd.Series

    @classmethod
    def from_rows(cls, rows: pd.DataFrame) -> "Split":
        return cls(rows=rows, X=select_features(rows), y=rows[TARGET].astype(int))


@dataclass(frozen=True)
class DatasetSplits:
    train: Split
    validation: Split
    test: Split
    validation_cutoff: pd.Timestamp
    test_cutoff: pd.Timestamp
    excluded: dict[str, int]  # filas descartadas por etiqueta aún desconocida, por conjunto


def select_features(df: pd.DataFrame) -> pd.DataFrame:
    """The only entry point from raw rows to model inputs."""
    TICKETS.assert_features_allowed(FEATURES)
    return df[FEATURES].copy()


def label_known_at(tickets: pd.DataFrame, moment: pd.Timestamp) -> pd.Series:
    """True if the SLA outcome was already determined at `moment`.

    Se sabe si el ticket ya estaba resuelto, o si su plazo ya había vencido sin resolverse
    (en ese caso el incumplimiento es seguro aunque siga abierto).
    """
    deadline = tickets["created_at"] + pd.to_timedelta(tickets["sla_hours"], unit="h")
    resolved = tickets["resolved_at"].notna() & (tickets["resolved_at"] <= moment)
    return resolved | (deadline <= moment)


def default_cutoffs(
    tickets: pd.DataFrame, validation_days: int = 30, test_days: int = 30
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(validation_cutoff, test_cutoff) counted back from the most recent ticket's day."""
    last_day = tickets["created_at"].max().normalize()
    test_cutoff = last_day - pd.Timedelta(days=test_days - 1)
    return test_cutoff - pd.Timedelta(days=validation_days), test_cutoff


def build_splits(
    tickets: pd.DataFrame, validation_cutoff: pd.Timestamp, test_cutoff: pd.Timestamp
) -> DatasetSplits:
    if not validation_cutoff < test_cutoff:
        raise ValueError("validation_cutoff must be earlier than test_cutoff")

    train_pool, rest = temporal_split(tickets, "created_at", validation_cutoff)
    validation_pool, test_pool = temporal_split(rest, "created_at", test_cutoff)

    train = train_pool[label_known_at(train_pool, validation_cutoff)]
    validation = validation_pool[label_known_at(validation_pool, test_cutoff)]
    test = test_pool[test_pool[TARGET].notna()]  # etiquetas conocidas en el snapshot

    for name, frame in (("train", train), ("validation", validation)):
        if frame[TARGET].isna().any():
            raise AssertionError(f"{name}: a ticket with a known outcome has a missing label")

    excluded = {
        "train": len(train_pool) - len(train),
        "validation": len(validation_pool) - len(validation),
        "test": len(test_pool) - len(test),
    }
    logger.info(
        "splits validation_cutoff=%s test_cutoff=%s train=%d validation=%d test=%d excluded=%s",
        validation_cutoff.date(),
        test_cutoff.date(),
        len(train),
        len(validation),
        len(test),
        excluded,
    )
    return DatasetSplits(
        train=Split.from_rows(train),
        validation=Split.from_rows(validation),
        test=Split.from_rows(test),
        validation_cutoff=validation_cutoff,
        test_cutoff=test_cutoff,
        excluded=excluded,
    )
