"""Chequeos de calidad de datos genéricos.

Cada chequeo devuelve un ValidationReport en vez de lanzar una excepción en el primer
problema: así se ven TODOS los problemas de una vez. Quien llama decide si son
bloqueantes con `raise_if_failed()`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import pandas as pd

from mlplatform.data.catalog import FieldCatalog


class DataValidationError(ValueError):
    """Data failed one or more quality checks."""


@dataclass
class ValidationReport:
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def extend(self, other: "ValidationReport") -> "ValidationReport":
        self.issues.extend(other.issues)
        return self

    def raise_if_failed(self) -> None:
        if self.issues:
            raise DataValidationError("Data validation failed:\n- " + "\n- ".join(self.issues))


def validate_against_catalog(df: pd.DataFrame, catalog: FieldCatalog) -> ValidationReport:
    """Check columns, non-nullable fields and allowed values (detects new categories)."""
    report = ValidationReport()

    missing = [name for name in catalog.names if name not in df.columns]
    unexpected = [col for col in df.columns if col not in catalog]
    if missing:
        report.issues.append(f"missing columns: {missing}")
    if unexpected:
        report.issues.append(f"columns not declared in catalog: {unexpected}")

    for spec in catalog:
        if spec.name not in df.columns:
            continue
        column = df[spec.name]
        n_null = int(column.isna().sum())
        if not spec.nullable and n_null:
            report.issues.append(f"{spec.name}: {n_null} null values in non-nullable field")
        if spec.allowed_values is not None:
            unseen = sorted(set(column.dropna().unique()) - set(spec.allowed_values))
            if unseen:
                report.issues.append(f"{spec.name}: values outside allowed set: {unseen}")
    return report


def check_chronological(df: pd.DataFrame, columns: Sequence[str]) -> ValidationReport:
    """Check that timestamp columns are in non-decreasing order where both are present."""
    report = ValidationReport()
    for earlier, later in zip(columns, columns[1:], strict=False):
        both = df[earlier].notna() & df[later].notna()
        n_bad = int((df.loc[both, earlier] > df.loc[both, later]).sum())
        if n_bad:
            report.issues.append(f"{n_bad} rows where {earlier} > {later}")
    return report
