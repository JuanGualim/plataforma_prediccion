# ADR 0004: Catálogo de campos en código como barrera contra fugas de información

- **Estado:** Aceptada
- **Fecha:** 2026-10-10
- **Fase:** 1

## Contexto

El modelo de SLA predice al crear el ticket. La tabla de tickets mezcla campos conocidos en ese
momento con campos que solo existen después (fechas de resolución, reasignaciones…). Algunos de
estos últimos predicen el resultado muy bien: `reassignment_count` sube el PR-AUC de 0,29 a 0,40
en el baseline. Por eso es fácil incluirlos por error y obtener un modelo que solo "funciona" en
validación.

## Decisión

1. Cada campo se declara en un `FieldCatalog` (`mlplatform.data.catalog`) con su **disponibilidad
   temporal**: T0, T0\*, T+, ETIQUETA o ID.
2. Las features solo pasan al modelo a través de `select_features`, que llama a
   `assert_features_allowed` y rechaza campos T+, ETIQUETA, ID **o no declarados**.
3. La lista `FEATURES` se valida también al importar el módulo (falla lo antes posible).
4. Un test compara el catálogo con `docs/data_dictionary.md`: la documentación no puede quedar desactualizada.
5. El dataset de entrenamiento excluye las **filas** cuyo resultado no se conocía en la fecha de
   corte (`label_known_at`), lo que evita fugas por filas además de por columnas.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Solo documentar los campos (sin código) | La documentación no detiene a nadie; la regla debe ejecutarse |
| Lista negra de columnas prohibidas | Un campo nuevo pasaría sin control; la lista blanca obliga a clasificarlo primero |
| Librería de contratos de datos (pandera, Great Expectations) | Útiles para validar tipos y rangos, pero no modelan "cuándo se conoce" un campo; se pueden sumar después para la validación |
| Feature store con point-in-time joins (Feast) | Resuelve la parte T0\* a escala; es excesivo para una sola tabla (se evalúa en la fase 6) |

## Consecuencias

- Positivas: la regla "el momento de la predicción es sagrado" se verifica en cada `make test`; la plataforma la ofrece a cualquier caso de uso.
- Negativas: cada campo nuevo exige actualizar el catálogo y el diccionario (es intencional).
- Reconsiderar si: hay muchas tablas y features derivadas compartidas entre modelos (entonces, feature store).
