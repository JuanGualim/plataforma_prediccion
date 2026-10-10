-- Esquemas base. Las tablas se definen en la fase 1 junto con el simulador
-- (ver docs/data_dictionary.md).
--
-- support    : datos operativos de tickets y sus eventos (lo que "ocurre").
-- monitoring : predicciones servidas y resultados reales (lo que el modelo "dijo" y lo que pasó).
--
-- Separarlos evita que el pipeline de entrenamiento lea por error lo que el
-- modelo predijo en producción como si fuera un dato del negocio.

CREATE SCHEMA IF NOT EXISTS support;
CREATE SCHEMA IF NOT EXISTS monitoring;
