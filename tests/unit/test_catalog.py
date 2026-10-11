import pytest

from mlplatform.data.catalog import Availability, FieldCatalog, FieldSpec, LeakageError

CATALOG = FieldCatalog(
    [
        FieldSpec("id", "uuid", Availability.ID, "id"),
        FieldSpec("channel", "text", Availability.T0, "known at creation"),
        FieldSpec("queue", "int", Availability.T0_POINT_IN_TIME, "past-only aggregate"),
        FieldSpec("closed_at", "timestamptz", Availability.AFTER_T0, "future"),
        FieldSpec("label", "bool", Availability.LABEL, "target"),
    ]
)


def test_t0_fields_are_allowed() -> None:
    CATALOG.assert_features_allowed(["channel", "queue"])
    assert CATALOG.feature_safe() == ["channel", "queue"]


@pytest.mark.parametrize("column", ["closed_at", "label", "id"])
def test_non_t0_fields_are_rejected(column: str) -> None:
    with pytest.raises(LeakageError, match=column):
        CATALOG.assert_features_allowed(["channel", column])


def test_undeclared_fields_are_rejected() -> None:
    with pytest.raises(LeakageError, match="not declared"):
        CATALOG.assert_features_allowed(["channel", "brand_new_column"])


def test_duplicated_fields_are_rejected() -> None:
    spec = FieldSpec("x", "int", Availability.T0, "x")
    with pytest.raises(ValueError, match="Duplicated"):
        FieldCatalog([spec, spec])
