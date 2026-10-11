"""Promoción y rollback: orquesta registry, evaluación, política y bitácora de auditoría.

Este módulo no conoce MLflow ni PostgreSQL: recibe "puertos" (interfaces) y la plataforma
le inyecta los adaptadores reales (mlplatform.registry). Por eso se prueba con dobles en memoria.

Semántica:
- promote: evalúa con la puerta; si aprueba, mueve el alias `champion`. Aprobado o no,
  queda registrado en la bitácora.
- rollback: devuelve `champion` a la versión que lo era ANTES de la promoción vigente.
  No pasa por la puerta (en un incidente la prioridad es restaurar rápido una versión que
  ya fue aprobada), pero exige un motivo y queda registrado.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from mlplatform.lifecycle.contract import DeploymentContract
from mlplatform.lifecycle.promotion import (
    Evaluation,
    PromotionDecision,
    PromotionPolicy,
    evaluate_promotion,
)

CHAMPION = "champion"


class LifecycleError(RuntimeError):
    """Operation not allowed in the current registry state."""


@dataclass(frozen=True)
class RegistryEvent:
    model_name: str
    event_type: str  # promoted | rejected | rolled_back
    from_version: str | None
    to_version: str | None
    actor: str
    reason: str
    details: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class LoadedVersion:
    version: str
    contract: DeploymentContract
    model: Any


class ModelRegistry(Protocol):
    def get_alias(self, model_name: str, alias: str) -> str | None: ...
    def set_alias(self, model_name: str, alias: str, version: str) -> None: ...
    def set_version_tag(self, model_name: str, version: str, key: str, value: str) -> None: ...
    def get_contract(self, model_name: str, version: str) -> DeploymentContract: ...
    def load_model(self, model_name: str, version: str) -> Any: ...


class EventLog(Protocol):
    def append(self, event: RegistryEvent) -> None: ...
    def history(self, model_name: str) -> list[RegistryEvent]: ...


# El caso de uso sabe cómo evaluar sus modelos (qué datos, qué features, qué umbral).
Evaluator = Callable[[LoadedVersion, LoadedVersion | None], Evaluation]


class LifecycleService:
    def __init__(
        self,
        registry: ModelRegistry,
        events: EventLog,
        policy: PromotionPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.events = events
        self.policy = policy or PromotionPolicy()

    def _load(self, model_name: str, version: str) -> LoadedVersion:
        return LoadedVersion(
            version=version,
            contract=self.registry.get_contract(model_name, version),
            model=self.registry.load_model(model_name, version),
        )

    def promote(
        self, model_name: str, version: str, evaluator: Evaluator, actor: str, reason: str
    ) -> PromotionDecision:
        current = self.registry.get_alias(model_name, CHAMPION)
        if current == version:
            raise LifecycleError(f"version {version} is already the champion")

        candidate = self._load(model_name, version)
        champion = self._load(model_name, current) if current else None
        evaluation = evaluator(candidate, champion)
        decision = evaluate_promotion(
            candidate.contract, champion.contract if champion else None, evaluation, self.policy
        )
        details = {
            "checks": [c.__dict__ for c in decision.checks],
            "evaluation": evaluation.__dict__,
        }

        if decision.approved:
            self.registry.set_alias(model_name, CHAMPION, version)
            self.registry.set_version_tag(model_name, version, "status", "champion")
            if current:
                self.registry.set_version_tag(model_name, current, "status", "archived")
            event_type = "promoted"
        else:
            self.registry.set_version_tag(model_name, version, "status", "rejected")
            event_type = "rejected"

        self.events.append(
            RegistryEvent(model_name, event_type, current, version, actor, reason, details)
        )
        return decision

    def rollback(self, model_name: str, actor: str, reason: str) -> RegistryEvent:
        if not reason.strip():
            raise LifecycleError("a rollback requires a reason")
        current = self.registry.get_alias(model_name, CHAMPION)
        if current is None:
            raise LifecycleError("there is no champion to roll back")

        promotions = [
            e
            for e in self.events.history(model_name)
            if e.event_type == "promoted" and e.to_version == current
        ]
        target = promotions[-1].from_version if promotions else None
        if target is None:
            raise LifecycleError(f"version {current} has no previous champion to return to")

        self.registry.set_alias(model_name, CHAMPION, target)
        self.registry.set_version_tag(model_name, current, "status", "rolled_back")
        self.registry.set_version_tag(model_name, target, "status", "champion")
        event = RegistryEvent(model_name, "rolled_back", current, target, actor, reason)
        self.events.append(event)
        return event
