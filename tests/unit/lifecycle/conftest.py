"""Dobles en memoria del registry y la bitácora, y una fábrica de contratos válidos."""

import pytest

from mlplatform.lifecycle.contract import REQUIRED_MODEL_CARD_SECTIONS, DeploymentContract
from mlplatform.lifecycle.service import RegistryEvent

VALID_CARD = "\n\n".join(f"{section}\ntexto" for section in REQUIRED_MODEL_CARD_SECTIONS)


def build_contract(**overrides) -> DeploymentContract:
    base = {
        "model_name": "toy",
        "use_case": "toy",
        "owner": "equipo-toy",
        "created_at": "2025-07-01T00:00:00+00:00",
        "signature": {"inputs": [{"name": "x", "dtype": "float"}], "output": "probability"},
        "model_card": VALID_CARD,
        "primary_metric": "pr_auc",
        "validation_metrics": {"pr_auc": 0.4},
        "test_metrics": {"pr_auc": 0.4},
        "baseline_test_metrics": {"pr_auc": 0.2},
        "threshold": {"value": 0.2, "criterion": "min cost", "chosen_on": "validation"},
        "dataset": {
            "source": "postgres:toy",
            "fingerprint": "a" * 64,
            "data_start": "2025-01-01",
            "data_end": "2025-07-01",
            "train_end": "2025-05-01",
            "validation_end": "2025-06-01",
            "n_rows": {"train": 100, "validation": 20, "test": 20},
        },
        "code": {"git_commit": "abc123", "git_dirty": False},
        "dependencies": {"lockfile_sha256": "b" * 64, "packages": {"scikit-learn": "1.9"}},
        "data_checks": {"passed": True, "issues": []},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return DeploymentContract(**base)


class InMemoryRegistry:
    def __init__(self) -> None:
        self.contracts: dict[str, DeploymentContract] = {}
        self.aliases: dict[str, str] = {}
        self.tags: dict[str, dict[str, str]] = {}

    def add_version(self, version: str, contract: DeploymentContract) -> None:
        self.contracts[version] = contract
        self.tags[version] = {"status": "candidate"}

    def get_alias(self, model_name, alias):
        return self.aliases.get(alias)

    def set_alias(self, model_name, alias, version):
        self.aliases[alias] = version

    def set_version_tag(self, model_name, version, key, value):
        self.tags[version][key] = value

    def get_contract(self, model_name, version):
        return self.contracts[version]

    def load_model(self, model_name, version):
        return f"model-v{version}"


class InMemoryEventLog:
    def __init__(self) -> None:
        self.events: list[RegistryEvent] = []

    def append(self, event):
        self.events.append(event)

    def history(self, model_name):
        return [e for e in self.events if e.model_name == model_name]


@pytest.fixture
def make_contract():
    return build_contract


@pytest.fixture
def registry():
    return InMemoryRegistry()


@pytest.fixture
def event_log():
    return InMemoryEventLog()
