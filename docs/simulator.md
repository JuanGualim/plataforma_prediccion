# Simulador de tickets

> **Estado:** Ejecutado (fase 1). Código: `src/use_cases/sla_risk/simulator.py`.
> Comando: `make data` (genera, valida y carga en PostgreSQL).

## Para qué existe

No hay datos reales disponibles (ver [ADR 0003](adr/0003-datos-sinteticos-con-simulador.md)).
El simulador inventa un área de soporte con **reglas explícitas**. Eso permite:

- Controlar la línea de tiempo de cada ticket, y con ello probar que el modelo no "ve el futuro".
- Provocar cambios a propósito (drift) en la fase 5 para probar el monitoreo.
- Reproducir exactamente los mismos datos: misma configuración y misma semilla, mismos datos.

**Limitación honesta:** un modelo entrenado con estos datos aprende las reglas de este archivo.
Sus métricas prueban que la plataforma funciona, no que el modelo serviría en una empresa real.

## Configuración por defecto (`SimulationConfig`)

| Parámetro | Valor | Significado |
|---|---|---|
| `start` | 2025-01-06 (lunes) | Inicio del periodo simulado (zona America/Bogota) |
| `days` | 180 | Duración del periodo |
| `tickets_per_day` | 120 | Volumen base (se ajusta por día de la semana) |
| `seed` | 42 | Semilla del generador aleatorio |
| `channel_weights` | email 40 %, chat 25 %, phone 15 %, portal 20 % | Mezcla de canales |
| `misroute_rate` | 15 % | Tickets en los que el cliente declara mal la categoría |
| `queue_capacity` | 110 | Tickets abiertos que el equipo maneja sin degradarse |
| `as_of` | fin del periodo | Momento del snapshot: solo se registra lo ocurrido hasta aquí |

Resultado con la configuración por defecto: **18.792 tickets, 103.653 eventos, 14,9 % de
incumplimiento** y 94 tickets con resultado aún desconocido en el snapshot.

## Reglas del mundo simulado

### 1. Llegadas
- Volumen diario ~ Poisson(120 × factor del día): lunes 1,25 · martes 1,10 · miércoles y jueves 1,00 · viernes 0,95 · sábado 0,45 · domingo 0,30.
- Hora de llegada según un perfil con picos entre 9-11 h y 14-16 h.
- Dos tickets nunca comparten el mismo segundo, así el orden de llegada no es ambiguo.

### 2. Atributos al crear (T0)
- **Categoría real** (oculta): billing 25 %, network 25 %, account 20 %, hardware 10 %, software 20 %.
- **Categoría declarada** (visible): igual a la real, salvo en el 15 % de los casos, en que el cliente elige otra.
- **Prioridad:** depende de la categoría real (network y hardware tienden a ser más urgentes).
- **Nivel de cliente:** basic 60 %, business 30 %, enterprise 10 %.
- **SLA comprometido (horas):**

| Nivel \ Prioridad | low | medium | high | critical |
|---|---|---|---|---|
| basic | 72 | 48 | 24 | 8 |
| business | 48 | 24 | 12 | 6 |
| enterprise | 24 | 12 | 8 | 4 |

- **Texto:** asunto y descripción según la **categoría real** (útil para el clasificador de la fase 7). El 20 % incluye un teléfono o correo ficticio (`@example.com`), que se usará para probar el enmascarado de datos personales en la fase 8.

### 3. Tiempo de resolución (lo que el modelo NO ve)
Duración = mediana por prioridad × multiplicadores × ruido aleatorio:

| Factor | Efecto |
|---|---|
| Prioridad (mediana) | low 24 h · medium 11 h · high 5 h · critical 2 h |
| Complejidad de la categoría real | account 0,7 · billing 0,8 · software 1,1 · network 1,3 · hardware 1,6 |
| Canal | phone 0,80 · chat 0,85 · portal 1,00 · email 1,15 |
| Nivel de cliente | basic 1,00 · business 0,85 · enterprise 0,70 (atención preferente) |
| Fuera de horario (antes de 8 h, después de 18 h o fin de semana) | ×1,6 (low/medium) · ×1,4 (high) · ×1,1 (critical) |
| Categoría mal declarada | ×1,5 |
| Reasignaciones (Poisson; más probables si está mal declarada) | ×1,25 por cada una |
| Ruido | log-normal, σ = 0,6 |
| **Carga de la cola** | ×exp(0,5 × (cola / capacidad − 1)), con el exceso acotado entre −0,5 y +1 |

**Cola y retroalimentación.** `open_tickets_in_queue` cuenta los tickets creados antes y aún sin
resolver. Una cola alta alarga las resoluciones, y eso hace crecer la cola. Durante la calibración se
observó un **punto de quiebre**: con elasticidad 1,0 y capacidad ≤ 100 la cola colapsaba (~270
abiertos, 55 % de incumplimiento). Con los valores actuales el sistema es estable entre semillas.
Reducir `queue_capacity` es un escenario natural de drift para la fase 5 ("el equipo pierde personal").

### 4. Eventos y snapshot
Cada ticket genera: `created` → `assigned` → `first_response` → `reassigned` (0 o más) → `resolved` → `closed`.
Solo se registran los eventos ocurridos hasta `as_of`; los campos T+ de la tabla de tickets reflejan
ese mismo instante. La etiqueta `sla_breached` puede ser `NULL` si el resultado aún no se conoce
(ver [diccionario de datos](data_dictionary.md)).

## Qué no modela (a propósito)
- Agentes individuales, turnos o vacaciones.
- Reapertura de tickets.
- Clientes recurrentes (no hay `customer_id`).
- Estacionalidad anual o festivos.
