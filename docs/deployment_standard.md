# Estándar de despliegue

> **Estado:** borrador (fase 1). Se implementa y se hace cumplir de forma automática en la fase 3
> (`mlplatform.lifecycle`).

Este documento define qué debe cumplir **cualquier** modelo para desplegarse en la plataforma,
sin importar el equipo ni el tipo de modelo (tabular, texto o LLM).

## 1. Contrato del modelo (obligatorio)

Todo modelo registrado debe incluir:

| Elemento | Descripción | Cómo se verifica |
|---|---|---|
| Firma de entrada/salida | Esquema de las columnas o campos que recibe y devuelve | _Por definir (fase 3)_ |
| Model card | Propósito, datos, métricas, limitaciones, responsable | _Por definir_ |
| Métricas de validación | Calculadas sobre un conjunto de validación temporal | _Por definir_ |
| Referencia al dataset | Versión, hash o consulta, y rango de fechas usado | _Por definir_ |
| Commit de git | Commit exacto del código que lo entrenó (sin cambios sin commitear) | _Por definir_ |
| Dependencias fijadas | Versiones exactas (lockfile) | _Por definir_ |
| Umbral de decisión | Valor, criterio (p. ej. costo FN/FP) y conjunto donde se eligió. El preprocesamiento viaja dentro del mismo artefacto | Implementado en fase 2 (`report.json`); se formaliza en fase 3 |

## 2. Estados y alias

- **candidate:** registrado y con el contrato completo.
- **champion:** la versión que atiende el tráfico. Hay una sola por modelo.
- **archived:** versión retirada (se conserva por trazabilidad).

## 3. Puerta de promoción

Un candidato pasa a champion **solo si**:

1. Cumple el contrato completo.
2. Pasa los chequeos de datos (esquema, nulos, rangos).
3. Supera al champion actual en la métrica principal sobre el **mismo** conjunto de validación,
   sin empeorar las métricas de protección más allá de una tolerancia. _Métricas y tolerancias: por definir en la fase 2._

## 4. Rollback

- Un solo comando (`make rollback`) devuelve el alias champion a la versión anterior.
- Cada promoción y cada rollback se registran: quién, cuándo, de qué versión a cuál y por qué.

## 5. Serving

- Endpoints obligatorios: `/predict`, `/health`, `/ready`, `/metadata`.
- Toda respuesta de `/predict` incluye `model_name` y `model_version`.
