# Diccionario de datos

> **Estado:** Ejecutado (fase 1). La tabla `support.tickets` coincide con el catálogo en código
> (`src/use_cases/sla_risk/fields.py`); la prueba `test_data_dictionary_matches_catalog` falla
> si alguno de los dos cambia sin el otro.
>
> Los datos son **sintéticos**, generados por el simulador descrito en [simulator.md](simulator.md).
> Las métricas obtenidas con ellos prueban que el sistema funciona, no que tenga valor de
> negocio validado.

## Por qué existe la columna "Disponible en"

El modelo de riesgo de SLA predice **en el momento de crear el ticket (T0)**. Cualquier
campo que se conozca después (duración, fecha de cierre, reasignaciones…) es **fuga de
información**: el modelo se vería excelente en validación y sería inútil en producción.

| Código | Significado | ¿Lo puede usar el modelo de SLA? |
|---|---|---|
| **T0** | Se conoce al crear el ticket | Sí |
| **T0\*** | Se calcula en T0 usando solo información anterior (point-in-time) | Sí, si el cálculo solo mira el pasado |
| **T+** | Se conoce después de crear el ticket | **No** |
| **ETIQUETA** | Resultado que el modelo intenta predecir | Solo como variable objetivo |
| **ID** | Identificador técnico | No (no es una característica) |

## Tabla `support.tickets`

Una fila por ticket, tal como se ve en el momento del snapshot (`as_of`).

| Campo | Tipo | Significado | Disponible en |
|---|---|---|---|
| `ticket_id` | uuid | Identificador único del ticket | ID |
| `created_at` | timestamptz | Momento de creación; define T0 (zona America/Bogota) | T0 |
| `channel` | text | Canal de entrada: email, chat, phone, portal | T0 |
| `category` | text | Categoría **declarada por el cliente**: billing, network, account, hardware, software. Es incorrecta en ~15 % de los casos | T0 |
| `priority` | text | Prioridad al crear: low, medium, high, critical | T0 |
| `customer_tier` | text | Nivel de contrato: basic, business, enterprise | T0 |
| `product` | text | Producto afectado: fiber_home, mobile_app, web_portal, router_x200, business_plan | T0 |
| `subject` | text | Asunto del ticket | T0 |
| `description` | text | Texto libre inicial; ~20 % contiene datos personales ficticios (teléfono o correo) | T0 |
| `sla_hours` | int | Horas comprometidas para resolver, según prioridad y nivel de cliente | T0 |
| `open_tickets_in_queue` | int | Tickets creados antes de este y aún sin resolver en su instante de creación | T0\* |
| `assigned_group` | text | Equipo que atiende el ticket (según la categoría real, no la declarada) | T+ |
| `first_response_at` | timestamptz | Primera respuesta de un agente (NULL si aún no ocurre) | T+ |
| `reassignment_count` | int | Reasignaciones ocurridas hasta el snapshot. **Trampa de fuga**: predice mucho, pero no existe en T0 | T+ |
| `resolved_at` | timestamptz | Momento de resolución (NULL si sigue abierto) | T+ |
| `closed_at` | timestamptz | Cierre administrativo (NULL si no ha ocurrido) | T+ |
| `status` | text | Estado en el snapshot: open, resolved, closed | T+ |
| `sla_breached` | bool | ¿Incumplió el SLA? Ver semántica abajo | ETIQUETA |

### Semántica de la etiqueta `sla_breached`

| Situación en el snapshot | Valor |
|---|---|
| Resuelto y `resolved_at - created_at > sla_hours` | `true` |
| Resuelto dentro del plazo | `false` |
| Sin resolver y el plazo ya venció | `true` (el incumplimiento ya es seguro) |
| Sin resolver y el plazo aún no vence | `NULL` (todavía no se sabe) |

Al construir el dataset de entrenamiento con una fecha de corte, solo entran tickets cuyo
resultado **ya se conocía en esa fecha** (`label_known_at` en `use_cases/sla_risk/dataset.py`).

## Entradas del modelo de SLA (fase 2)

El modelo recibe solo estas columnas crudas (`FEATURES` en `fields.py`), todas T0 o T0\*. El
pipeline (`use_cases/sla_risk/features.py`) las transforma así:

| Columna cruda | Transformación dentro del pipeline |
|---|---|
| `channel`, `category`, `priority`, `customer_tier`, `product` | One-hot; una categoría nunca vista se codifica como "ninguna" (no rompe la predicción) |
| `sla_hours`, `open_tickets_in_queue` | Estandarizadas (regresión logística) o sin cambio (boosting) |
| `created_at` | Se derivan `hour_sin`, `hour_cos`, `weekday_sin`, `weekday_cos`, `is_weekend` e `is_off_hours` en hora de Bogotá. **La fecha absoluta nunca llega al modelo** |

## Tabla `support.ticket_events`

Historial de lo ocurrido a cada ticket hasta el snapshot. No se usa como feature en la fase 1.

| Campo | Tipo | Significado |
|---|---|---|
| `event_id` | uuid | Identificador del evento |
| `ticket_id` | uuid | Ticket al que pertenece (llave foránea) |
| `event_type` | text | created, assigned, first_response, reassigned, resolved, closed |
| `event_at` | timestamptz | Momento del evento; un evento es T0 solo si `event_at <= created_at` del ticket |

## Tabla `monitoring.predictions` (fase 4, diseño)

| Campo | Tipo | Significado |
|---|---|---|
| `prediction_id` | uuid | Identificador de la predicción |
| `ticket_id` | uuid | Ticket evaluado |
| `model_name` / `model_version` | text | Modelo y versión que respondió |
| `score` | float | Probabilidad de incumplir el SLA |
| `decision` | bool | `score >= umbral` vigente |
| `predicted_at` | timestamptz | Momento de la predicción |
