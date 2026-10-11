"""Catálogo de campos: qué significa cada columna y CUÁNDO se conoce.

Es la versión ejecutable de docs/data_dictionary.md (un test verifica que ambos coinciden).
La plataforma usa el catálogo para dos cosas:

1. Impedir fugas de información: solo los campos disponibles en T0 pueden ser features.
2. Validar datos: columnas esperadas, nulos permitidos y valores permitidos.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class Availability(StrEnum):
    """When a field becomes known. Values are the codes used in docs/data_dictionary.md."""

    T0 = "T0"  # known when the entity is created
    T0_POINT_IN_TIME = "T0*"  # computed at T0 using only information prior to T0
    AFTER_T0 = "T+"  # known only after T0: never a feature
    LABEL = "ETIQUETA"  # the prediction target
    ID = "ID"  # technical identifier, not a feature


FEATURE_SAFE = frozenset({Availability.T0, Availability.T0_POINT_IN_TIME})


class LeakageError(ValueError):
    """A column that would not exist at prediction time was requested as a feature."""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    dtype: str  # logical/SQL type, as written in the data dictionary
    availability: Availability
    description: str
    nullable: bool = False
    allowed_values: tuple[str, ...] | None = None


class FieldCatalog:
    """Ordered collection of FieldSpec with leakage guards."""

    def __init__(self, fields: Iterable[FieldSpec]) -> None:
        self._fields: dict[str, FieldSpec] = {}
        for spec in fields:
            if spec.name in self._fields:
                raise ValueError(f"Duplicated field in catalog: {spec.name}")
            self._fields[spec.name] = spec

    def __getitem__(self, name: str) -> FieldSpec:
        return self._fields[name]

    def __contains__(self, name: object) -> bool:
        return name in self._fields

    def __iter__(self):
        return iter(self._fields.values())

    @property
    def names(self) -> list[str]:
        return list(self._fields)

    def feature_safe(self) -> list[str]:
        """Fields that may be used as model inputs."""
        return [f.name for f in self if f.availability in FEATURE_SAFE]

    def assert_features_allowed(self, columns: Iterable[str]) -> None:
        """Raise LeakageError if any column is unknown or not available at T0.

        Las columnas desconocidas también se rechazan: un campo nuevo debe documentarse
        (y clasificarse) en el catálogo antes de poder usarse.
        """
        columns = list(columns)
        unknown = [c for c in columns if c not in self._fields]
        leaking = [
            f"{c} ({self._fields[c].availability.value})"
            for c in columns
            if c in self._fields and self._fields[c].availability not in FEATURE_SAFE
        ]
        problems = []
        if leaking:
            problems.append(f"not available at prediction time: {', '.join(leaking)}")
        if unknown:
            problems.append(f"not declared in the catalog: {', '.join(unknown)}")
        if problems:
            raise LeakageError("Invalid feature columns -> " + "; ".join(problems))
