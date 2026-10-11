# ADR 0005: Protocolo de evaluación temporal, desbalance vía umbral y umbral por costo

- **Estado:** Aceptada
- **Fecha:** 2026-10-10
- **Fase:** 2

## Contexto

Hay que elegir entre varios modelos y convertir una probabilidad en una decisión ("¿escalo este
ticket?"). La clase de interés es minoritaria (~15 %). Si la misma información se usa para entrenar,
elegir y medir, el resultado reportado es optimista y no anticipa lo que pasará en producción.

## Decisión

1. **Tres conjuntos temporales consecutivos:**
   - **Entrenamiento:** ajustar los modelos.
   - **Validación:** elegir el modelo y el umbral.
   - **Prueba:** medir una sola vez.

   Cada conjunto solo incluye tickets cuyo resultado se conocía en el momento en que se usa.
2. **Sin reentrenar sobre entrenamiento + validación** antes de la prueba. El modelo evaluado es
   exactamente el que se guarda, y el umbral sigue siendo válido para él.
3. **Desbalance:** se entrena sin pesos de clase ni remuestreo, para conservar probabilidades
   calibradas. La rareza de la clase se maneja al elegir el umbral.
4. **Umbral:** el que minimiza el costo esperado en validación, con costos explícitos y configurables
   (`cost_fn = 5`, `cost_fp = 1`). Se reporta junto al óptimo teórico de un modelo calibrado.
5. **Selección:** métrica principal PR-AUC. Entre los candidatos a menos de 0,005 del mejor, gana el más simple.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Validación cruzada aleatoria (k-fold) | Mezcla pasado y futuro; sobreestima el desempeño con datos temporales |
| Validación cruzada temporal (varias ventanas) | Más robusta, pero con 6 meses de datos agrega complejidad sin cambiar la decisión; candidata si hay más historia |
| Reentrenar con entrenamiento + validación antes de la prueba | Usa más datos, pero el modelo evaluado ya no es el que eligió el umbral; se puede adoptar con un umbral recalculado |
| `class_weight="balanced"` | Mismo ordenamiento (mismo PR-AUC) y Brier casi el doble: descalibra sin mejorar la detección |
| SMOTE / sobremuestreo | Inventa ejemplos sintéticos y también descalibra; agrega una dependencia sin beneficio |
| Umbral 0,5 por defecto | Ignora el desbalance y los costos; aquí produciría muy pocas alertas |
| Umbral que maximiza F1 | Trata igual una falsa alarma y un caso no detectado; el negocio no los valora igual |
| Umbral por capacidad (top-N diario) | Válido si el área tiene un cupo fijo de revisiones; se deja como opción documentada |

## Consecuencias

- Positivas: el número de la prueba es honesto. La decisión de umbral se explica en lenguaje de
  negocio ("cuesta 5 veces más no detectar"), y la teoría sirve de chequeo de cordura.
- Negativas: el modelo final no usa los últimos 30 días de validación para entrenar. Los costos son
  un **supuesto** y deben validarse con el área.
- Reconsiderar si: hay más historia (ventanas múltiples), la capacidad del área impone un cupo, o el
  costo de un incumplimiento varía por nivel de cliente (umbrales por segmento).
