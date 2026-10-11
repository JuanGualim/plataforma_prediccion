"""Catálogo de la tabla support.tickets y lista de features del modelo de SLA.

Fuente única de verdad: docs/data_dictionary.md debe reflejar exactamente este
catálogo (lo verifica tests/unit/sla_risk/test_leakage.py).
"""

from mlplatform.data.catalog import Availability, FieldCatalog, FieldSpec

CHANNELS = ("email", "chat", "phone", "portal")
CATEGORIES = ("billing", "network", "account", "hardware", "software")
PRIORITIES = ("low", "medium", "high", "critical")
TIERS = ("basic", "business", "enterprise")
PRODUCTS = ("fiber_home", "mobile_app", "web_portal", "router_x200", "business_plan")
GROUPS = ("billing_team", "network_team", "accounts_team", "field_service", "app_support")
STATUSES = ("open", "resolved", "closed")

T0 = Availability.T0
T0_PIT = Availability.T0_POINT_IN_TIME
AFTER = Availability.AFTER_T0

TICKETS = FieldCatalog(
    [
        FieldSpec("ticket_id", "uuid", Availability.ID, "Identificador único del ticket"),
        FieldSpec("created_at", "timestamptz", T0, "Momento de creación; define T0"),
        FieldSpec("channel", "text", T0, "Canal de entrada", allowed_values=CHANNELS),
        FieldSpec("category", "text", T0, "Categoría declarada", allowed_values=CATEGORIES),
        FieldSpec("priority", "text", T0, "Prioridad al crear", allowed_values=PRIORITIES),
        FieldSpec("customer_tier", "text", T0, "Nivel de contrato", allowed_values=TIERS),
        FieldSpec("product", "text", T0, "Producto afectado", allowed_values=PRODUCTS),
        FieldSpec("subject", "text", T0, "Asunto del ticket"),
        FieldSpec("description", "text", T0, "Texto libre inicial"),
        FieldSpec("sla_hours", "int", T0, "Horas comprometidas para resolver"),
        FieldSpec("open_tickets_in_queue", "int", T0_PIT, "Tickets abiertos en la cola en T0"),
        FieldSpec(
            "assigned_group",
            "text",
            AFTER,
            "Grupo que atiende el ticket",
            nullable=True,
            allowed_values=GROUPS,
        ),
        FieldSpec("first_response_at", "timestamptz", AFTER, "Primera respuesta", nullable=True),
        FieldSpec("reassignment_count", "int", AFTER, "Número de reasignaciones"),
        FieldSpec("resolved_at", "timestamptz", AFTER, "Momento de resolución", nullable=True),
        FieldSpec("closed_at", "timestamptz", AFTER, "Cierre administrativo", nullable=True),
        FieldSpec("status", "text", AFTER, "Estado en el snapshot", allowed_values=STATUSES),
        FieldSpec("sla_breached", "bool", Availability.LABEL, "¿Incumplió el SLA?", nullable=True),
    ]
)

TARGET = "sla_breached"

# Columnas crudas que recibe el modelo de SLA (el pipeline deriva el resto; ver features.py).
# `created_at` entra solo para derivar hora y día de la semana. Los campos de texto (subject,
# description) son T0, pero se reservan para el clasificador de la fase 7.
FEATURES = [
    "created_at",
    "channel",
    "category",
    "priority",
    "customer_tier",
    "product",
    "sla_hours",
    "open_tickets_in_queue",
]

# Falla al importar el módulo si alguien agrega una feature con fuga: el error aparece
# antes de entrenar, no después de desplegar.
TICKETS.assert_features_allowed(FEATURES)
