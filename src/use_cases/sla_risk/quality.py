"""Chequeos de calidad de la tabla de tickets (se usan al cargar y al entrenar)."""

import pandas as pd

from mlplatform.data.validation import (
    ValidationReport,
    check_chronological,
    validate_against_catalog,
)
from use_cases.sla_risk.fields import TICKETS

LIFECYCLE_TIMESTAMPS = ["created_at", "first_response_at", "resolved_at", "closed_at"]


def validate_tickets(tickets: pd.DataFrame) -> ValidationReport:
    report = validate_against_catalog(tickets, TICKETS)
    return report.extend(check_chronological(tickets, LIFECYCLE_TIMESTAMPS))
