"""Qué modelo está sirviendo y cómo se reemplaza en caliente.

El servicio no carga "la versión 3": carga "la versión que tenga el alias champion". Un hilo
revisa el alias cada cierto tiempo; si cambió (promoción o rollback), carga la nueva versión
y la intercambia de forma atómica. Si la carga falla, sigue sirviendo la anterior: un
registry con problemas nunca debe tumbar un servicio que funciona.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from mlplatform.lifecycle.contract import DeploymentContract

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelBundle:
    name: str
    version: str
    model: Any
    contract: DeploymentContract
    loaded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class ModelSource(Protocol):
    """Where served models come from (the registry, in production)."""

    def current_version(self) -> str | None: ...
    def load(self, version: str) -> ModelBundle: ...


class ModelHolder:
    def __init__(self, source: ModelSource, expected_inputs: list[str]) -> None:
        self.source = source
        self.expected_inputs = expected_inputs
        self.bundle: ModelBundle | None = None
        self.last_error: str | None = None
        self._lock = threading.Lock()  # evita dos cargas simultáneas, no bloquea predicciones

    def refresh(self) -> bool:
        """Load the alias' current version if it changed. Returns True if the model was swapped."""
        with self._lock:
            try:
                version = self.source.current_version()
            except Exception as error:  # el registry puede estar caído o el artefacto dañado
                self.last_error = f"cannot resolve alias: {error}"
                logger.warning(self.last_error)
                return False
            if version is None:
                if self.bundle is None:
                    self.last_error = "no champion registered yet"
                return False
            if self.bundle is not None and self.bundle.version == version:
                return False
            try:
                bundle = self.source.load(version)
                self._check_signature(bundle)
            except Exception as error:
                self.last_error = f"cannot load version {version}: {error}"
                logger.error(self.last_error)
                return False

            previous = self.bundle.version if self.bundle else None
            self.bundle = bundle  # intercambio atómico: una sola asignación
            self.last_error = None
            logger.info("serving %s v%s (previous: %s)", bundle.name, version, previous)
            return True

    def _check_signature(self, bundle: ModelBundle) -> None:
        """The service's input schema must match the model's contract exactly."""
        declared = [f.name for f in bundle.contract.signature.inputs]
        if declared != self.expected_inputs:
            raise ValueError(
                f"contract inputs {declared} do not match service inputs {self.expected_inputs}"
            )


class RegistryModelSource:
    """ModelSource backed by any registry exposing get_alias/load_model/get_contract."""

    def __init__(self, registry: Any, model_name: str, alias: str = "champion") -> None:
        self.registry = registry
        self.model_name = model_name
        self.alias = alias

    def current_version(self) -> str | None:
        return self.registry.get_alias(self.model_name, self.alias)

    def load(self, version: str) -> ModelBundle:
        return ModelBundle(
            name=self.model_name,
            version=version,
            model=self.registry.load_model(self.model_name, version),
            contract=self.registry.get_contract(self.model_name, version),
        )
