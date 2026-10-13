# Fase 6: variables point-in-time y evaluación de Feast (demostración)

> **Estado:** Ejecutado el 2026-10-12 contra el stack local, con el mundo de la fase 5 cargado hasta
> el 2025-11-02 (`--days 300 --drift-start 2025-08-15 --drift-capacity 85`). Datos sintéticos.
> Las latencias son mediciones locales de referencia (laptop de desarrollo), no un benchmark.
> Decisión: [ADR 0010](../adr/0010-feature-store-feast-no-por-ahora.md).

## 1. La pregunta

El modelo de SLA ya usa una variable **T0\***: `open_tickets_in_queue`, un agregado del pasado
calculado en el instante de crear el ticket. Hoy la calcula el simulador y la envía el cliente.
Un *feature store* (Feast) promete resolver justo este tipo de variables:
- **offline:** unirlas "en el tiempo" con las filas de entrenamiento, sin mirar el futuro;
- **online:** servir el valor vigente con baja latencia;
- **una sola definición** para ambos lados.

La fase respondió tres preguntas en orden: ¿hay variables T0\* que valgan la pena?, ¿Feast
funciona y da lo mismo que una implementación propia?, ¿cuánto cuesta?

## 2. Lo que se construyó

| Pieza | Dónde | Para qué |
|---|---|---|
| Ventanas point-in-time genéricas | `mlplatform.features.point_in_time` | Conteos, promedios y colas en cada instante, usando solo eventos **anteriores** a ese instante |
| Variables de contexto del SLA | `use_cases.sla_risk.context_features` | `arrivals_24h`, `breach_rate_7d`, `category_queue` (ver el [diccionario](../data_dictionary.md#variables-de-contexto-operativo-fase-6-evaluadas-y-no-usadas-por-el-modelo)) |
| Prueba de viaje en el tiempo | `tests/unit/sla_risk/test_context_features.py` | Variables en T con toda la historia = variables con el mundo simulado hasta T |
| Experimento con bootstrap | `make feature-experiment` | ¿Mejoran el modelo? Con intervalos de confianza |
| Exportador + spike de Feast | `make feast-export`, `make feast-spike` | Feast real contra Postgres, en un entorno aislado |

### La prueba de viaje en el tiempo
El simulador puede mostrar el mismo mundo tal como se conocía en cualquier instante. Para tres
instantes T, las variables calculadas con la historia **completa** coinciden exactamente con las
calculadas con la historia **hasta T**. Una variante con fuga a propósito (fechar el resultado
al crear el ticket, en vez de cuando se supo) hace fallar la comparación. Esa variante es la
prueba de que la prueba detecta fugas.

## 3. ¿Las variables mejoran el modelo? (`make feature-experiment`)

Misma regresión logística de producción, mismos cortes, misma regla de madurez de etiquetas y
mismo umbral por costo; solo cambian las variables. Δ = variante − base (negativo = mejora).
IC95 = intervalo bootstrap pareado (1.000 remuestreos); ✱ = no incluye 0.

| Escenario (n prueba) | Variante | Brier | Brecha | Costo | Δ Brier IC95 | Δ costo IC95 |
|---|---|---|---|---|---|---|
| Sin drift (4.485) | base | 0,1031 | −0,003 | 0,457 | — | — |
| | + las tres | 0,1033 | −0,004 | 0,450 | [+0,0000, +0,0004] ✱ | [−0,016, +0,004] |
| Drift sin reentrenar (3.090) | base | 0,1641 | −0,073 | 0,593 | — | — |
| | + `arrivals_24h` | 0,1615 | −0,058 | 0,571 | [−0,0032, −0,0020] ✱ | [−0,047, +0,004] |
| | + `breach_rate_7d` | 0,1629 | −0,066 | 0,573 | [−0,0015, −0,0010] ✱ | [−0,043, +0,004] |
| | + las tres | 0,1619 | −0,060 | 0,574 | [−0,0028, −0,0016] ✱ | [−0,041, +0,002] |
| Drift reentrenado (1.459) | base | 0,1619 | −0,036 | 0,584 | — | — |
| | + las tres | 0,1610 | −0,023 | 0,582 | [−0,0018, −0,0002] ✱ | [−0,022, +0,018] |

El PR-AUC no cambió en ningún caso (±0,002). Reporte completo en `data/reports/features/`.

**Lectura:**
1. **Sin drift no aportan nada.** `open_tickets_in_queue` ya resume la carga; las demás son redundantes.
2. **Con drift ayudan un poco, y de forma medible en el Brier (−1,6 %).** Son la única "ventana"
   del modelo a la capacidad del equipo, que no se observa. Curiosamente, la que más ayuda es
   `arrivals_24h`, que **no** cambió con el drift. Hipótesis: junto con la cola, distingue "cola
   alta porque llegó mucho" de "cola alta porque el equipo es lento".
3. **No habrían evitado el INC-001.** La brecha de calibración seguiría en −0,058, fuera del
   límite de ±0,05. La mejora en costo (−2,2 puntos) no se distingue del ruido.
4. **Decisión: no se incorporan al modelo.** Usarlas exige calcularlas al servir: el cliente no
   conoce la tasa de incumplimiento de la semana. Una dependencia en línea nueva (frescura,
   latencia, fallas) por una mejora que solo aparece con drift y no cambia decisiones no se paga.

## 4. Feast, funcionando de verdad (`make feast-spike`)

**Por qué en un proyecto aparte:** Feast 0.66 exige `pandas<3` y la plataforma usa pandas 3.0.
Instalarlo en el proyecto obligaría a bajar pandas en toda la plataforma (un solo lockfile) por
un componente experimental. El spike vive en `experiments/feast_spike/` con su propio entorno.

**Cómo se conectó:** Feast **no calcula** ventanas temporales; guarda series ya calculadas y las
une o sirve. Nuestra función materializa cada hora (7.199 horas globales y 35.995 por categoría)
en el esquema desechable `feast_spike`. Feast usa Postgres como almacén offline (el join ocurre
en la base) y también como almacén online.

### Paridad: Feast da exactamente lo mismo

| Comparación (31.027 tickets) | `arrivals_24h` | `breach_rate_7d` | `category_queue` |
|---|---|---|---|
| Feast vs. nuestro cálculo en la hora en punto anterior | **100 % idénticas** | **100 %** | **100 %** |
| Feast vs. valor exacto en T0 (filas iguales) | 21,6 % | 21,0 % | 47,6 % |
| Error medio / máximo frente al valor exacto | 2,4 / 20 tickets | 0,0008 / 0,013 | 0,8 / 8 tickets |

La segunda fila es el **costo de materializar cada hora**: el valor tiene hasta 59 minutos de
atraso. En la lectura en línea, Feast, el SQL calculado al momento y nuestra tabla devolvieron
los mismos valores en la última hora.

### Costo y latencia

| Medición | Feast | Sin feature store |
|---|---|---|
| Entorno | 488 MB, 68 paquetes (incluye Dask) | 0 MB nuevos (numpy y pandas ya estaban) |
| Importar la librería | 7,4 s | — |
| Configuración específica | 70 líneas (YAML + definiciones) | — |
| Point-in-time join de 31.027 tickets | 67,7 s (SQL en Postgres) | 0,13 s (`context_features`, valor exacto en T0) |
| Materializar al almacén online | 0,33 s | — (tabla horaria propia: 4,7 s el export completo) |
| Lectura en línea, p50 / p95 | 2,5 / 3,7 ms | 0,34 / 0,51 ms (tabla propia por clave primaria) · 57 / 82 ms (SQL al momento, sin índices) |

### Fricciones encontradas

| Síntoma | Causa | Qué se hizo |
|---|---|---|
| `server does not support SSL, but SSL was required` | Feast pide SSL por defecto; el Postgres local no tiene TLS | `sslmode: disable` solo en local, con el motivo en el YAML |
| `Column __dummy_id not found in table` al materializar | Las vistas **sin entidad** (un valor global por instante) fallan al materializar con Postgres en Feast 0.66 | Entidad constante `team = "support"` |
| La lectura en línea devolvió un valor de hace 11 meses | Con nuestra configuración, la lectura en línea no aplicó el `ttl` de 2 h: el último valor materializado era del 2025-11-02 y se leyó el 2026-10-12 | Documentado: con un feature store hay que **monitorear la frescura** aparte |

## 5. Decisión y criterios

**No se adopta Feast por ahora** ([ADR 0010](../adr/0010-feature-store-feast-no-por-ahora.md)).
Funciona y es correcto, pero para este caso todo lo que aporta lo resuelven ~150 líneas propias (con su documentación),
más rápidas y sin dependencias nuevas. Lo que **sí** queda en la plataforma: el módulo
point-in-time, la prueba de viaje en el tiempo como requisito para cualquier variable T0\*
nueva y el spike reproducible para reevaluar.

Feast (u otro feature store) se justificaría si se cumplen **varias** de estas condiciones:
1. Varias variables **compartidas por dos o más modelos o equipos** (definición única, catálogo).
2. Variables por entidad con **muchas claves** (p. ej., historial por cliente con millones de
   clientes) que el cliente de la API no puede calcular y que hay que servir en milisegundos.
3. Muchas fuentes y uniones "en el tiempo" que mantener a mano.
4. Variables de **streaming** con requisitos de frescura en segundos.
5. Un equipo que opere la pieza (materializaciones, frescura, versiones) y un stack compatible.

Hoy no se cumple ninguna: un modelo, tres agregados globales o por cinco categorías, una tabla de
origen, y variables que ni siquiera se usan.
