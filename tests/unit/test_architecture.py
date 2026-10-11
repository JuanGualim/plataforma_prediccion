"""Reglas de arquitectura verificadas automáticamente.

La plataforma (`mlplatform`) debe ser genérica: si importara de `use_cases`,
agregar un nuevo modelo obligaría a tocar la plataforma.
"""

import ast
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[2] / "src" / "mlplatform"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_platform_does_not_import_use_cases() -> None:
    offenders = [
        str(path.relative_to(PLATFORM_DIR))
        for path in PLATFORM_DIR.rglob("*.py")
        if any(m.split(".")[0] == "use_cases" for m in _imported_modules(path))
    ]

    assert not offenders, f"mlplatform no debe importar use_cases: {offenders}"


LIFECYCLE_DIR = PLATFORM_DIR / "lifecycle"
INFRASTRUCTURE_LIBRARIES = {"mlflow", "sqlalchemy", "psycopg", "boto3"}


def test_lifecycle_policy_does_not_depend_on_infrastructure() -> None:
    """La política de promoción se prueba sin MLflow ni base de datos (ver ADR 0001)."""
    offenders = {
        str(path.relative_to(PLATFORM_DIR)): sorted(
            m for m in _imported_modules(path) if m.split(".")[0] in INFRASTRUCTURE_LIBRARIES
        )
        for path in LIFECYCLE_DIR.rglob("*.py")
    }
    offenders = {path: mods for path, mods in offenders.items() if mods}

    assert not offenders, f"lifecycle imports infrastructure: {offenders}"
