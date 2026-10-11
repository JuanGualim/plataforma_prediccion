"""Separación de datos para entrenar y evaluar."""

import pandas as pd


def temporal_split(
    df: pd.DataFrame, time_col: str, cutoff: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split rows into [.., cutoff) for training and [cutoff, ..] for evaluation.

    Nunca se separa al azar datos con tiempo: el modelo en producción siempre predice
    el futuro con datos del pasado, y la evaluación debe imitar eso.
    """
    cutoff = pd.Timestamp(cutoff)
    train = df[df[time_col] < cutoff]
    test = df[df[time_col] >= cutoff]
    if train.empty or test.empty:
        raise ValueError(
            f"Cutoff {cutoff} leaves an empty side (train={len(train)}, test={len(test)})"
        )
    return train, test
