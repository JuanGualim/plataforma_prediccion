# ADR 0009: Monitoreo en tres niveles con PSI, perfil de referencia por versión y reporte por lotes

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Fase:** 5

## Contexto

Con el modelo en producción (fase 4) hay que responder tres preguntas distintas, con fuentes y
tiempos distintos:

1. **Servicio:** ¿la API responde? Se sabe en segundos.
2. **Datos:** ¿lo que llega se parece a lo que el modelo conoció? Se sabe en cuanto llega el tráfico.
3. **Modelo:** ¿sigue acertando? Solo se sabe cuando vence el plazo del ticket, días después.

Restricciones: un solo desarrollador, laptop sin GPU, disco justo (se llenó dos veces), datos
sintéticos con drift provocado. La plataforma debe servir a otros modelos sin conocer el caso de SLA.

## Decisión

- **Tres niveles con severidades distintas:** servicio → SEV1, datos y puntaje → SEV3 (señal temprana),
  modelo con etiquetas reales → SEV2. Cada hallazgo apunta a un escenario del runbook.
- **Datos: PSI** por variable y del puntaje (alerta ≥ 0,25, aviso ≥ 0,10), más alerta por categoría
  nunca vista. Sin evaluar con menos de 200 filas.
- **Referencia por versión:** cada entrenamiento guarda `reference_profile.json` en MLflow, calculado
  sobre la **ventana de prueba** (datos que el modelo no usó) y las categorías vistas al entrenar. El
  monitoreo de una versión se compara con *su* perfil.
- **Modelo: contra el contrato.** PR-AUC, Brier, brecha de calibración y costo por ticket con el umbral
  vigente, con tolerancias fijas. Se juzga solo con ≥ 300 etiquetas y ≥ 50 % de cobertura, y la
  cobertura siempre se reporta.
- **Ventanas por fecha del evento** (`created_at`), no por la hora de la petición.
- **Reporte por lotes** (`make monitor` → Markdown + JSON) leyendo `monitoring.predictions`,
  `monitoring.requests` y `support.tickets`. No hay una pila de métricas en tiempo real.
- El código genérico vive en `mlplatform.monitoring`; el caso de uso solo declara qué variables
  vigilar y cómo armar la tabla (`use_cases.sla_risk.monitoring`), y usa las **mismas funciones** al
  entrenar y al monitorear.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Evidently / whylogs / NannyML | Resuelven mucho más de lo necesario (decenas de métricas, paneles) y suman dependencias pesadas a una imagen que ya llenó el disco. Se usan 4 métricas y el PSI, que caben en ~400 líneas con docstrings, todas probadas. Se reconsidera si hay muchos modelos con tipos de datos variados (texto, embeddings) |
| Prueba KS / chi-cuadrado | Con miles de filas, todo cambio mínimo da p < 0,05: alerta siempre. El PSI mide el **tamaño** del cambio y tiene umbrales de uso común |
| Prometheus + Grafana | Lo correcto para el nivel de servicio en tiempo real, pero sin tráfico continuo ni guardia es infraestructura sin uso. Se diseña para la fase 10 (Kubernetes) |
| Referencia = datos de entrenamiento | El entrenamiento cubre meses con estacionalidad mezclada y el modelo ya los "memorizó". La ventana de prueba es el último periodo **no visto**, el más parecido a producción |
| Una referencia fija para todo el modelo | Tras reentrenar con el mundo nuevo, el monitoreo seguiría alertando contra el mundo viejo. Con el perfil por versión, la v5 se comparó con su propia normalidad |
| Monitorear solo PR-AUC | En INC-001 el PR-AUC **subió** mientras el modelo empeoraba, porque aumentó la prevalencia. Brier, calibración y costo detectaron el problema |
| Ventanas por hora de la petición | Una reproducción de dos meses en 12 s quedaría en un solo minuto. En producción real coinciden casi siempre; la fecha del evento es correcta en ambos casos |

## Consecuencias

- Positivas:
  - El incidente simulado se detectó en orden (señal temprana → confirmación) y se pudo explicar
    por variable y por semana.
  - El monitoreo de cada versión nace con el entrenamiento: no hay que acordarse de configurar nada.
  - Sin dependencias nuevas.
- Negativas / costos aceptados:
  - Nadie ejecuta el reporte automáticamente: hoy es un comando manual. En la fase 10 pasa a CronJob.
  - Umbrales fijos (PSI 0,25; tolerancias del contrato), sin ajustar por modelo.
  - Las semanas parciales pueden dar falsos positivos de PSI.
  - Versiones registradas antes de la fase 5 (v1 a v3) no tienen perfil y no se pueden monitorear
    a nivel de datos.
- Qué haría que reconsideráramos esta decisión: tráfico continuo con guardia (→ Prometheus para el
  servicio), muchos modelos o datos no tabulares (→ una librería de monitoreo), o etiquetas que
  tarden semanas (→ métricas sustitutas, como estimar el desempeño sin etiquetas).
