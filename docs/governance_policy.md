# Política de gobierno de modelos de ML y GenAI

> **Estado:** parcial. Secciones 2, 3 y 6 implementadas en la fase 3; logs de predicción (4) en la fase 4.
> El resto se completa en las fases 5 y 8.
> Es una política breve y aplicable, no un documento legal.

## 1. Alcance

Aplica a todos los modelos desplegados en la plataforma: modelos predictivos (tabulares y de
texto) y aplicaciones con LLM (RAG).

## 2. Roles

| Rol | Responsabilidad |
|---|---|
| Dueño del modelo (equipo de Data Science) | Entrenar y registrar candidatos con contrato completo; mantener la model card; solicitar la promoción con un motivo |
| Equipo de plataforma (MLOps) | Mantener la puerta, el registry y la bitácora; ejecutar rollbacks en incidentes |
| Aprobador de negocio | Validar los supuestos de costo del umbral y las limitaciones por segmento de la model card. _El flujo de aprobación con firma queda fuera de alcance; hoy la evidencia queda en la bitácora._ |

## 3. Aprobaciones

- Ningún modelo llega a producción sin pasar la **puerta de promoción automática** (ver
  [estándar de despliegue](deployment_standard.md)). No existe un mecanismo para saltársela.
- Toda promoción, rechazo y rollback queda en `governance.model_events` con actor, motivo y evidencia.
- El **rollback** puede ejecutarlo plataforma sin aprobación previa (prioridad: restaurar el servicio),
  pero exige un motivo y se revisa después en el post-mortem.

## 4. Información personal

- **Datos de entrenamiento:** _por definir_.
- **Prompts y contexto enviados a LLM:** _por definir (fase 8): enmascarado de información personal antes de enviar el texto, qué proveedores están permitidos._
- **Logs de predicción (fase 4):** se guardan las 8 entradas del modelo, el puntaje, la decisión y la
  versión. **No** se guardan el texto libre del ticket (`subject`, `description`, que pueden contener
  datos personales) ni otros campos: la API rechaza cualquier campo no declarado. El `ticket_id` se
  guarda solo para unir con el resultado real. El tráfico de prueba se marca como `synthetic`.
  **Retención (propuesta, no ejecutada):** 13 meses para `monitoring.predictions` y
  `monitoring.requests`. Alcanza para comparar con el mismo mes del año anterior y para auditar
  cualquier versión servida en el último año. Después se conservan solo los agregados semanales del
  reporte de monitoreo. Hoy no hay un proceso de purga: es un volumen local de demostración.

## 5. Monitoreo obligatorio

Todo modelo que se sirve en la plataforma queda cubierto por estos mínimos (implementados en
`mlplatform.monitoring`; ver [ADR 0009](adr/0009-monitoreo-en-tres-niveles.md)):

| Nivel | Requisito | Alerta mínima |
|---|---|---|
| Servicio | Toda llamada a `/predict` queda en `monitoring.requests` | SEV1 con 5xx > 1 %; SEV3 con p95 > 200 ms |
| Datos y puntaje | La versión registra `reference_profile.json` al entrenar | SEV3 con PSI ≥ 0,25 en una entrada o en el puntaje, o con una categoría nunca vista |
| Modelo | Las predicciones guardan un identificador para unirlas con el resultado real | SEV2 si PR-AUC, Brier, calibración o costo se salen de la tolerancia del contrato (≥ 300 etiquetas, ≥ 50 % de cobertura) |

- El reporte siempre muestra la **cobertura de etiquetas**: sin ella no se concluye nada del modelo.
- El tráfico de prueba (`synthetic`) nunca entra al monitoreo.
- Hoy el reporte se ejecuta a mano (`make monitor`). La ejecución semanal programada queda para la fase 10.

## 6. Retiro de modelos

- Una versión reemplazada pasa a `archived` y una revertida a `rolled_back`. **Nunca se borra**: su
  contrato, model card, métricas y artefactos se conservan en MLflow para auditoría y para poder volver a ella.
- **Degradación sostenida (fase 5):** si una versión acumula un SEV2 en dos reportes semanales
  seguidos y ni el rollback ni el reentrenamiento la devuelven a su contrato, el dueño decide entre
  (a) un nuevo contrato aprobado con métricas peores pero explícitas, o (b) **apagar el uso del modelo**
  y volver a la regla de negocio (el baseline). Un modelo que falla en silencio es peor que no tener
  modelo. En INC-001 alcanzó con reentrenar.

## 7. Específico de GenAI

_Por definir (fase 8): versionado de prompts, evaluación antes de desplegar, límites de costo por consulta._
