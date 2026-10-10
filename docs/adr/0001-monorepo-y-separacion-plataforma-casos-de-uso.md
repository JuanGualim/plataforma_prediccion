# ADR 0001: Monorepo con la plataforma y los casos de uso como paquetes separados

- **Estado:** Aceptada
- **Fecha:** 2026-10-10
- **Fase:** 1

## Contexto

El proyecto es una plataforma sobre la que varios "equipos cliente" despliegan modelos.
Hay que demostrar que la plataforma es genérica, sin la complejidad operativa de varios
repositorios o microservicios.

## Decisión

Un solo repositorio con dos paquetes Python en `src/`:

- `mlplatform/`: la plataforma (datos, training, registry, lifecycle, serving, monitoring).
- `use_cases/`: los modelos cliente (`sla_risk`, `ticket_routing`, `support_rag`).

La dependencia es en un solo sentido: `use_cases` → `mlplatform`. Un test
(`tests/unit/test_architecture.py`) falla si la plataforma importa un caso de uso.

Dentro de la plataforma, `registry` (mecanismo: habla con MLflow) está separado de
`lifecycle` (política: decide si se promueve). Así la puerta de promoción se prueba sin MLflow.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Un repositorio por modelo + uno para la plataforma | Exige versionar y publicar la plataforma como librería; agrega complejidad sin aportar al objetivo |
| Microservicios (un servicio por componente) | Complejidad operativa desproporcionada para el tamaño del proyecto |
| Un solo paquete con todo mezclado | No se puede demostrar ni verificar que la plataforma es genérica |
| Nombrar el módulo `platform/` | Choca con el módulo `platform` de la librería estándar de Python |

## Consecuencias

- Positivas: un solo `uv sync`, un solo lockfile y refactors atómicos. La separación se verifica con un test.
- Negativas: todos los casos de uso comparten dependencias (PyTorch se instala aunque solo lo use `ticket_routing`). Se puede mitigar con grupos de dependencias opcionales.
- Reconsiderar si: los casos de uso necesitan versiones incompatibles de una misma librería.
