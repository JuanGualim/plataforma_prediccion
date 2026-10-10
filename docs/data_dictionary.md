# Diccionario de datos

> **Estado:** BORRADOR. Los campos se confirman al implementar el simulador (fase 1).
> Los datos son **sintéticos**, generados por un simulador documentado en este repositorio.
> Las métricas que se obtengan con ellos prueban que el sistema funciona, no que tenga
> valor de negocio validado.

## Por qué existe la columna "Disponible en"

El modelo de riesgo de SLA predice **en el momento de crear el ticket (T0)**. Cualquier
campo que se conozca después (duración, fecha de cierre, reasignaciones…) es **fuga de
información**: el modelo se vería excelente en validación y sería inútil en producción.

| Código | Significado | ¿Lo puede usar el modelo de SLA? |
|---|---|---|
| **T0** | Se conoce al crear el ticket | Sí |
| **T0\*** | Se calcula con información anterior a T0 (point-in-time) | Sí, si el cálculo solo mira el pasado |
| **T+** | Se conoce después de crear el ticket | **No** |
| **ETIQUETA** | Resultado que el modelo intenta predecir | Solo como variable objetivo |
| **ID** | Identificador técnico | No (no es una característica) |

## Tabla `support.tickets` (borrador)

| Campo | Tipo | Significado | Disponible en |
|---|---|---|---|
| `ticket_id` | uuid | Identificador único del ticket | ID |
| `created_at` | timestamptz | Momento de creación; define T0 | T0 |
| `channel` | text | Canal de entrada (email, chat, teléfono, portal) | T0 |
| `category` | text | Categoría declarada por el cliente | T0 |
| `priority` | text | Prioridad asignada al crear | T0 |
| `customer_tier` | text | Nivel de contrato del cliente | T0 |
| `product` | text | Producto afectado | T0 |
| `subject` | text | Asunto del ticket | T0 |
| `description` | text | Texto libre inicial (puede contener información personal) | T0 |
| `sla_hours` | int | Horas comprometidas para resolver, según prioridad y nivel | T0 |
| `open_tickets_in_queue` | int | Tickets abiertos en la cola en T0 | T0\* |
| `assigned_group` | text | Grupo que finalmente atiende el ticket | T+ |
| `first_response_at` | timestamptz | Primera respuesta de un agente | T+ |
| `reassignment_count` | int | Número de reasignaciones | T+ |
| `resolved_at` | timestamptz | Momento de resolución | T+ |
| `closed_at` | timestamptz | Momento de cierre administrativo | T+ |
| `status` | text | Estado actual | T+ |
| `sla_breached` | bool | `resolved_at - created_at > sla_hours` | ETIQUETA |

## Tabla `support.ticket_events` (borrador)

| Campo | Tipo | Significado | Disponible en |
|---|---|---|---|
| `event_id` | uuid | Identificador del evento | ID |
| `ticket_id` | uuid | Ticket al que pertenece | ID |
| `event_type` | text | created, assigned, responded, reassigned, resolved, closed | Según `event_at` |
| `event_at` | timestamptz | Momento del evento | T0 solo si `event_at <= created_at` |

## Tabla `monitoring.predictions` (fase 4, borrador)

| Campo | Tipo | Significado |
|---|---|---|
| `prediction_id` | uuid | Identificador de la predicción |
| `ticket_id` | uuid | Ticket evaluado |
| `model_name` / `model_version` | text | Modelo y versión que respondió |
| `score` | float | Probabilidad de incumplir el SLA |
| `decision` | bool | `score >= umbral` vigente |
| `predicted_at` | timestamptz | Momento de la predicción |

## Pendiente

- [ ] Confirmar los campos al implementar el simulador.
- [ ] Prueba automática: ningún campo T+ o ETIQUETA entra a las features del modelo de SLA.
