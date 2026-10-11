"""Contrato de despliegue: lo que TODO modelo debe declarar para entrar a la plataforma.

Dos niveles de validación:
1. Estructura (pydantic): campos obligatorios y tipos. Un contrato incompleto ni se construye.
2. Política (`contract_violations`): reglas que la estructura no expresa, como "el código no
   puede tener cambios sin commitear" o "la model card debe tener sección de limitaciones".

Ver docs/deployment_standard.md.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Secciones mínimas de cualquier model card de la plataforma.
REQUIRED_MODEL_CARD_SECTIONS = (
    "## Propósito",
    "## Uso previsto y fuera de alcance",
    "## Datos",
    "## Métricas",
    "## Umbral de decisión",
    "## Limitaciones",
    "## Responsable",
)


class SignatureField(BaseModel):
    name: str
    dtype: str


class ModelSignature(BaseModel):
    inputs: list[SignatureField] = Field(min_length=1)
    output: str


class DatasetReference(BaseModel):
    source: str
    fingerprint: str = Field(min_length=64, max_length=64)  # sha256 hex
    data_start: str
    data_end: str
    train_end: str  # filas de entrenamiento creadas antes de este instante
    validation_end: str  # = inicio de la ventana de prueba
    n_rows: dict[str, int]


class DecisionThreshold(BaseModel):
    value: float = Field(gt=0, lt=1)
    criterion: str
    chosen_on: Literal["validation"]


class CodeVersion(BaseModel):
    git_commit: str | None
    git_dirty: bool | None


class Dependencies(BaseModel):
    lockfile_sha256: str = Field(min_length=64, max_length=64)
    packages: dict[str, str]


class DataChecks(BaseModel):
    passed: bool
    issues: list[str] = []


class DeploymentContract(BaseModel):
    contract_version: Literal["1"] = "1"
    model_name: str
    use_case: str
    owner: str
    created_at: str
    signature: ModelSignature
    model_card: str
    primary_metric: str
    validation_metrics: dict[str, float]
    test_metrics: dict[str, float]
    baseline_test_metrics: dict[str, float]
    threshold: DecisionThreshold
    dataset: DatasetReference
    code: CodeVersion
    dependencies: Dependencies
    data_checks: DataChecks


def contract_violations(contract: DeploymentContract) -> list[str]:
    """Policy rules on top of the schema. Empty list = the contract is acceptable."""
    violations = []
    if not contract.code.git_commit:
        violations.append("unknown git commit: the model cannot be reproduced")
    if contract.code.git_dirty is not False:
        violations.append("trained with uncommitted changes (or unknown state)")
    if not contract.data_checks.passed:
        violations.append(f"data checks failed: {contract.data_checks.issues}")
    reported = {"validation": contract.validation_metrics, "test": contract.test_metrics}
    for name, metrics in reported.items():
        if contract.primary_metric not in metrics:
            violations.append(f"primary metric '{contract.primary_metric}' missing in {name}")
    missing = [s for s in REQUIRED_MODEL_CARD_SECTIONS if s not in contract.model_card]
    if missing:
        violations.append(f"model card missing sections: {missing}")
    return violations
