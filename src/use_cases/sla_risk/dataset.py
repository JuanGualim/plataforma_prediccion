"""Construcción del dataset de entrenamiento y evaluación del modelo de SLA.

Dos protecciones contra "ver el futuro":

1. Columnas: solo entran las FEATURES, validadas contra el catálogo (T0 / T0*).
2. Filas: un ticket solo entra al entrenamiento si su resultado ya se conocía en la fecha
   de corte. Un ticket creado el día anterior al corte y resuelto una semana después NO
   tenía etiqueta en ese momento; usarlo sería entrenar con información del periodo de prueba.
"""

import logging
from dataclasses import dataclass

import pandas as pd

from mlplatform.training.splits import temporal_split
from use_cases.sla_risk.fields import FEATURES, TARGET, TICKETS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrainTestData:
    X_train: pd.DataFrame
    y_train: pd.Series
    X_test: pd.DataFrame
    y_test: pd.Series
    train_rows: pd.DataFrame  # filas completas, solo para análisis (nunca para el modelo)
    test_rows: pd.DataFrame
    cutoff: pd.Timestamp
    excluded_immature: int  # tickets previos al corte sin etiqueta conocida en el corte


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


def default_cutoff(tickets: pd.DataFrame, test_days: int) -> pd.Timestamp:
    """Start of the day `test_days` before the most recent ticket."""
    return (tickets["created_at"].max() - pd.Timedelta(days=test_days)).normalize()


def build_train_test(tickets: pd.DataFrame, cutoff: pd.Timestamp) -> TrainTestData:
    train_pool, test_pool = temporal_split(tickets, "created_at", cutoff)

    mature = label_known_at(train_pool, cutoff)
    train = train_pool[mature]
    # En evaluación se usan las etiquetas conocidas en el snapshot; las pendientes se excluyen.
    test = test_pool[test_pool[TARGET].notna()]

    if train[TARGET].isna().any():
        raise AssertionError("A ticket with a label known at cutoff has a missing label")

    logger.info(
        "split cutoff=%s train=%d (excluded %d immature) test=%d (excluded %d unlabeled)",
        cutoff.date(),
        len(train),
        int((~mature).sum()),
        len(test),
        len(test_pool) - len(test),
    )
    return TrainTestData(
        X_train=select_features(train),
        y_train=train[TARGET].astype(int),
        X_test=select_features(test),
        y_test=test[TARGET].astype(int),
        train_rows=train,
        test_rows=test,
        cutoff=cutoff,
        excluded_immature=int((~mature).sum()),
    )
