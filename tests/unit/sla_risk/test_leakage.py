"""Pruebas de fuga de información del modelo de SLA.

Regla: el modelo predice al CREAR el ticket (T0). Estas pruebas fallan si
(1) una columna posterior a T0 entra como feature, (2) el catálogo y el diccionario de datos
dejan de coincidir, o (3) una fila de entrenamiento usa un resultado que aún no se conocía.
"""

import re
from pathlib import Path

import pandas as pd
import pytest

from mlplatform.data.catalog import FEATURE_SAFE, LeakageError
from use_cases.sla_risk import dataset
from use_cases.sla_risk.dataset import build_splits, default_cutoffs, label_known_at
from use_cases.sla_risk.fields import FEATURES, TARGET, TICKETS

DATA_DICTIONARY = Path(__file__).resolve().parents[3] / "docs" / "data_dictionary.md"


def test_every_feature_is_available_at_prediction_time() -> None:
    for name in FEATURES:
        assert TICKETS[name].availability in FEATURE_SAFE, name
    assert TARGET not in FEATURES


@pytest.mark.parametrize(
    "leaky_column", [f.name for f in TICKETS if f.availability not in FEATURE_SAFE]
)
def test_adding_a_post_t0_column_breaks_the_dataset(monkeypatch, small_sim, leaky_column) -> None:
    monkeypatch.setattr(dataset, "FEATURES", [*FEATURES, leaky_column])

    with pytest.raises(LeakageError, match=leaky_column):
        dataset.select_features(small_sim.tickets)


def test_simulator_columns_are_all_catalogued(small_sim) -> None:
    assert list(small_sim.tickets.columns) == TICKETS.names


def test_data_dictionary_matches_catalog() -> None:
    """La documentación es honesta solo si coincide con el código."""
    text = DATA_DICTIONARY.read_text(encoding="utf-8")
    section = text.split("## Tabla `support.tickets`", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(
        r"^\|\s*`(\w+)`\s*\|\s*([^|]+?)\s*\|[^|]*\|\s*([^|]+?)\s*\|\s*$", section, re.M
    )
    documented = {name: (dtype, avail.replace("\\*", "*")) for name, dtype, avail in rows}

    in_code = {f.name: (f.dtype, f.availability.value) for f in TICKETS}

    assert documented == in_code


def test_each_split_only_uses_outcomes_known_when_it_is_used(small_sim) -> None:
    tickets = small_sim.tickets
    validation_cutoff, test_cutoff = default_cutoffs(tickets, validation_days=7, test_days=7)

    splits = build_splits(tickets, validation_cutoff, test_cutoff)

    train, validation, test = (s.rows for s in (splits.train, splits.validation, splits.test))
    assert train["created_at"].max() < validation_cutoff <= validation["created_at"].min()
    assert validation["created_at"].max() < test_cutoff <= test["created_at"].min()
    # train se usa en validation_cutoff; validation se usa en test_cutoff.
    assert label_known_at(train, validation_cutoff).all()
    assert label_known_at(validation, test_cutoff).all()
    assert test["sla_breached"].notna().all()
    # Había tickets cerca de cada corte con resultado aún abierto, y quedaron fuera.
    assert splits.excluded["train"] > 0
    assert splits.excluded["validation"] > 0
    for split in (splits.train, splits.validation, splits.test):
        assert list(split.X.columns) == FEATURES


def test_cutoffs_must_be_ordered(small_sim) -> None:
    validation_cutoff, test_cutoff = default_cutoffs(small_sim.tickets, 7, 7)
    with pytest.raises(ValueError, match="earlier"):
        build_splits(small_sim.tickets, test_cutoff, validation_cutoff)


def test_label_known_at_examples() -> None:
    created = pd.Timestamp("2025-01-01 08:00", tz="America/Bogota")
    tickets = pd.DataFrame(
        {
            "created_at": [created] * 3,
            "sla_hours": [4, 4, 48],
            "resolved_at": [created + pd.Timedelta(hours=2), pd.NaT, pd.NaT],
        }
    )
    moment = created + pd.Timedelta(hours=6)

    # resuelto antes del momento / vencido sin resolver / aún dentro del plazo
    assert label_known_at(tickets, moment).tolist() == [True, True, False]
