import pandas as pd
import pytest

from mlplatform.data.catalog import Availability, FieldCatalog, FieldSpec
from mlplatform.data.validation import (
    DataValidationError,
    check_chronological,
    validate_against_catalog,
)

CATALOG = FieldCatalog(
    [
        FieldSpec("channel", "text", Availability.T0, "c", allowed_values=("email", "chat")),
        FieldSpec("closed_at", "timestamptz", Availability.AFTER_T0, "c", nullable=True),
    ]
)


def test_valid_frame_passes() -> None:
    df = pd.DataFrame({"channel": ["email", "chat"], "closed_at": [pd.NaT, pd.Timestamp("2025")]})
    assert validate_against_catalog(df, CATALOG).ok


def test_reports_all_problems_at_once() -> None:
    df = pd.DataFrame({"channel": ["email", None, "fax"], "extra": [1, 2, 3]})

    report = validate_against_catalog(df, CATALOG)

    text = "\n".join(report.issues)
    assert "missing columns: ['closed_at']" in text
    assert "not declared in catalog: ['extra']" in text
    assert "channel: 1 null" in text
    assert "['fax']" in text  # categoría nueva
    with pytest.raises(DataValidationError):
        report.raise_if_failed()


def test_chronological_order() -> None:
    df = pd.DataFrame(
        {
            "a": pd.to_datetime(["2025-01-01", "2025-01-05", "2025-01-01"]),
            "b": pd.to_datetime(["2025-01-02", "2025-01-03", None]),
        }
    )

    report = check_chronological(df, ["a", "b"])

    assert report.issues == ["1 rows where a > b"]
