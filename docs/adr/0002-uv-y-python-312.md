# ADR 0002: uv como gestor de dependencias y Python 3.12

- **Estado:** Aceptada
- **Fecha:** 2026-10-10
- **Fase:** 1

## Contexto

El proyecto debe poder levantarse desde un entorno limpio con pocos comandos, con las mismas
versiones de todas las dependencias (también las transitivas). El sistema del autor trae
Python 3.14.

## Decisión

- `uv` gestiona el entorno virtual, el lockfile (`uv.lock`) y la versión de Python.
- Python fijado a 3.12 (`.python-version` y `requires-python = ">=3.12,<3.13"`).

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| pip + requirements.txt | No fija las dependencias transitivas sin herramientas extra (pip-tools) y no gestiona la versión de Python |
| Poetry | Válido, pero más lento y no instala Python por sí mismo |
| conda | Útil para dependencias nativas complejas; no es necesario aquí y es más pesado |
| Python 3.14 (el del sistema) | Parte del ecosistema de ML (PyTorch, Feast) tarda en publicar versiones para la última versión de Python |

## Consecuencias

- Positivas: `uv sync` reproduce el entorno exacto, el lockfile queda versionado y la instalación es rápida.
- Negativas: hay que instalar `uv` (una dependencia más en la máquina).
- Reconsiderar si: todas las dependencias de las fases 7 a 9 soportan una versión más nueva de Python.
