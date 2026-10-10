# ADR 0003: Datos sintéticos generados por un simulador propio

- **Estado:** Aceptada
- **Fecha:** 2026-10-10
- **Fase:** 1

## Contexto

El modelo de SLA necesita tickets con marca de tiempo de creación, eventos posteriores con su
fecha y hora, y un SLA definido. Además, la fase 5 necesita poder **provocar** drift a voluntad.

## Decisión

Construir un simulador documentado (`use_cases/sla_risk`) que genere tickets y eventos con
reglas explícitas, con una semilla fija para que sea reproducible y con parámetros para inyectar drift.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Dataset público de tickets | Rara vez trae eventos con fecha y hora y un SLA definido; no permite controlar el drift |
| Datos reales de una empresa | No disponibles y con información personal |

## Consecuencias

- Positivas: control total de la línea de tiempo (para probar fugas) y del drift (para probar el monitoreo).
- Negativas: **las métricas no demuestran valor de negocio**, porque el modelo aprende las reglas del simulador. Se declara así en el README.
- Reconsiderar si: aparece un dataset público con marcas de tiempo de eventos y SLA.
