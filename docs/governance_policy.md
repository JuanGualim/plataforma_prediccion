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
  _Retención: por definir (fase 5)._

## 5. Monitoreo obligatorio

_Por definir (fase 5): umbrales mínimos de alertas por nivel (servicio, datos, modelo)._

## 6. Retiro de modelos

- Una versión reemplazada pasa a `archived` y una revertida a `rolled_back`. **Nunca se borra**: su
  contrato, model card, métricas y artefactos se conservan en MLflow para auditoría y para poder volver a ella.
- _Por definir (fase 5): criterios para retirar un modelo por degradación sostenida._

## 7. Específico de GenAI

_Por definir (fase 8): versionado de prompts, evaluación antes de desplegar, límites de costo por consulta._
