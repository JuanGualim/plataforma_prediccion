# ADR 0010: Sin feature store por ahora; variables T0* con un módulo propio y prueba de viaje en el tiempo

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Fase:** 6

## Contexto

El ADR 0004 dejó pendiente evaluar un feature store para las variables **T0\*** (agregados del
pasado calculados en T0). El riesgo que resuelve es real: una variable calculada distinto al
entrenar y al servir (*training/serving skew*), o que mira el futuro al entrenar, rompe el modelo
en silencio.

La fase 6 midió las tres cosas que importan para decidir (ver
[resultados](../results/fase6_features_sla_risk.md)):
- **Valor:** tres variables de contexto (llegadas 24 h, tasa de incumplimiento 7 días, cola por
  categoría) no aportan sin drift. Con drift mejoran el Brier ~1,6 %, pero no cambian el costo
  de forma distinguible del ruido.
- **Corrección:** Feast 0.66 dio valores idénticos a nuestra implementación en 31.027 de
  31.027 tickets.
- **Costo:** 488 MB y 68 paquetes; exige `pandas<3` (incompatible con la plataforma); join de
  67,7 s contra 0,13 s propio; dos fallas de configuración y un `ttl` que no protegió la lectura
  en línea.

## Decisión

1. **No adoptar Feast** ni otro feature store por ahora.
2. Las variables T0\* se calculan con `mlplatform.features.point_in_time`: una sola función para
   entrenar (muchos instantes) y para servir (un instante), que solo usa eventos **anteriores**
   a T0 y fechados cuando se supieron.
3. **Toda variable T0\* nueva requiere una prueba de viaje en el tiempo**: su valor en T con la
   historia completa debe ser igual al calculado con la historia que existía en T.
4. Las variables de contexto evaluadas **no entran al modelo**: exigirían calcularlas en línea al
   servir por una mejora que solo aparece con drift.
5. El spike queda reproducible (`make feast-export && make feast-spike`) en su propio entorno, para
   reevaluar cuando cambien las condiciones.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Adoptar Feast en la plataforma | Obliga a bajar pandas 3 → 2 en todo el proyecto, suma 488 MB y un registro, materializaciones y frescura que operar. Para 3 variables de una sola tabla no hay nada que no resuelvan ~150 líneas propias, más rápidas |
| Feast solo para el serving (almacén online) | Leer nuestra propia tabla horaria por clave primaria fue 7 veces más rápido (0,34 ms contra 2,5 ms p50) y no agrega dependencias |
| Calcular las variables al servir con SQL directo | Funciona y da los mismos valores, pero tarda 57 ms (p50) sin índices y crece con la historia. Si alguna vez se usan en línea, conviene materializarlas (tabla propia) |
| Que el cliente envíe las variables (como hoy `open_tickets_in_queue`) | Aceptable para la cola, que el sistema de tickets conoce. No para la tasa de incumplimiento: el cliente no la tiene y cada cliente podría calcularla distinto |
| Incorporar las variables al modelo igual ("por si hay drift") | La mejora no cambia decisiones y no habría evitado INC-001. El reentrenamiento (runbook C) resolvió el drift con menos piezas |

## Consecuencias

- Positivas:
  - Ninguna dependencia nueva en la plataforma ni en la imagen de serving.
  - La regla "el momento de la predicción es sagrado" ahora tiene una prueba automática también
    para variables agregadas, no solo para columnas.
  - La decisión se basa en mediciones y es reversible: el spike sigue disponible.
- Negativas / costos aceptados:
  - Sin catálogo central de variables ni servicio en línea genérico: cada caso de uso define las
    suyas. Con un solo modelo no hace falta.
  - `open_tickets_in_queue` sigue llegando calculada por el cliente; su consistencia depende del
    sistema de tickets (el monitoreo de datos de la fase 5 vigila su distribución).
- Qué haría que reconsideráramos esta decisión (se necesitan varias):
  1. Variables compartidas por dos o más modelos o equipos.
  2. Variables por entidad con muchas claves (p. ej., historial por cliente) que hay que servir
     en milisegundos y que el cliente no puede calcular.
  3. Muchas fuentes y uniones en el tiempo que mantener a mano.
  4. Variables de streaming con frescura de segundos.
  5. Un equipo que opere el feature store y una versión compatible con el stack (pandas 3).
