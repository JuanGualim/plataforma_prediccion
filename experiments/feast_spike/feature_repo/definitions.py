"""Definiciones de Feast para las variables de contexto del SLA (spike de la fase 6).

- `operations`: variables globales del equipo. Son un solo valor por instante, pero llevan una
  entidad constante `team = "support"`: en Feast 0.66, materializar una vista SIN entidad falla
  con el almacenamiento Postgres (`Column __dummy_id not found`). Fricción encontrada en el spike.
- `category_context`: cola por categoría declarada (entidad `category`).

`ttl` = 2 h: si el último valor tiene más de 2 horas, Feast devuelve nulo en lugar de un dato
viejo. La serie se materializa cada hora, así que un hueco de una corrida todavía se tolera.
"""

from datetime import timedelta

from feast import Entity, FeatureView, Field, ValueType
from feast.infra.offline_stores.contrib.postgres_offline_store.postgres_source import (
    PostgreSQLSource,
)
from feast.types import Float64, Int64

TTL = timedelta(hours=2)

category = Entity(name="category", join_keys=["category"], value_type=ValueType.STRING)
team = Entity(name="team", join_keys=["team"], value_type=ValueType.STRING)

operations = FeatureView(
    name="operations",
    entities=[team],
    ttl=TTL,
    schema=[Field(name="arrivals_24h", dtype=Int64), Field(name="breach_rate_7d", dtype=Float64)],
    source=PostgreSQLSource(
        name="operations_hourly",
        query="SELECT 'support' AS team, * FROM feast_spike.operations_hourly",
        timestamp_field="event_timestamp",
    ),
)

category_context = FeatureView(
    name="category_context",
    entities=[category],
    ttl=TTL,
    schema=[Field(name="category_queue", dtype=Int64)],
    source=PostgreSQLSource(
        name="category_hourly",
        query="SELECT * FROM feast_spike.category_hourly",
        timestamp_field="event_timestamp",
    ),
)
