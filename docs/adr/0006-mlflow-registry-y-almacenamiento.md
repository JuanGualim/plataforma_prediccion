# ADR 0006: MLflow como tracking y registry, con artefactos en SeaweedFS vía proxy

- **Estado:** Aceptada
- **Fecha:** 2026-10-11
- **Fase:** 3

## Contexto

La plataforma necesita:
- una bitácora de experimentos,
- un catálogo versionado de modelos con un puntero a "la versión en producción",
- un almacenamiento para los artefactos (modelos, reportes, model cards).

Todo debe correr en local con Docker Compose y poder trasladarse a la nube.

## Decisión

1. **MLflow 3.17** (servidor en Docker) para tracking y model registry. Los metadatos van en una base
   `mlflow` dentro del mismo PostgreSQL, que se crea de forma idempotente al arrancar.
2. **Alias `champion`** en lugar de los "stages" (Staging/Production), que MLflow declaró obsoletos.
   Cada versión lleva además un tag `status`: candidate, champion, rejected, archived o rolled_back.
3. **Artefactos en un almacenamiento S3** servido por **SeaweedFS**. El servidor de MLflow hace de
   **intermediario** (`--serve-artifacts`): los clientes solo conocen la URL de MLflow, nunca las
   credenciales del almacenamiento, y el almacenamiento no expone puertos al host.
4. **Cliente `mlflow-skinny`**, con la versión exacta del servidor, en lugar del paquete completo.
5. **Formato `skops`** para los modelos (el predeterminado de MLflow 3.17), con una lista blanca
   explícita de tipos confiables.
6. El adaptador de la plataforma desactiva la **telemetría** y fuerza la descarga de artefactos a
   través del servidor.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Registry propio (carpetas + JSON, como en la fase 2) | Reinventa versionado, UI y API; no es lo que usa la industria |
| Weights & Biases / Neptune | SaaS: requieren cuenta y envían datos fuera; no se pueden levantar en local |
| SageMaker / Vertex AI / Azure ML Model Registry | Requieren nube y costo; el mapeo queda documentado para la fase 10 |
| MinIO como almacenamiento | **Ya no publica imágenes de Docker libres** (comprobado: `docker pull minio/minio` falla) |
| RustFS (clon de MinIO) | Prometedor pero joven; se prefirió madurez |
| Garage | Requiere pasos de configuración del clúster; más complejo para un entorno local |
| Artefactos en un volumen local (sin S3) | No refleja producción; con S3 el cambio a AWS/GCS es solo de configuración |
| Paquete `mlflow` completo en el cliente | Arrastra servidor, UI y dependencias innecesarias; el cliente solo necesita la API |
| Guardar modelos con pickle/cloudpickle | Cargar un pickle puede ejecutar código arbitrario; skops no |

## Hallazgos durante la implementación (registrados por su valor)

- **SQLAlchemy 2.1 cambió su driver por defecto de PostgreSQL** a `psycopg` (v3): la imagen instala
  ese driver, no `psycopg2`.
- La imagen oficial de MLflow **no trae `curl`**: el healthcheck usa Python.
- MLflow 3.17 anuncia **descargas por URL prefirmada** cuando el almacenamiento es S3. Esas URLs
  apuntan al nombre interno `seaweedfs:8333`, inalcanzable desde el host, y el cliente reintentaba sin
  fin. Se resolvió del lado del cliente (`MLFLOW_ENABLE_PROXY_MULTIPART_DOWNLOAD=false`), en un único
  punto: el adaptador `mlplatform.registry.mlflow_registry`.
- skops marca como no confiable el `TreePredictor` del gradient boosting (un archivo manipulado podría
  provocar lecturas de memoria fuera de rango). Se autoriza **explícitamente** porque los modelos los
  produce la plataforma y solo se cargan desde el registry interno.

## Consecuencias

- Positivas: interfaz estándar (UI en http://localhost:5000), runs anidados por candidato y carga por
  alias (`models:/sla_risk@champion`). Trasladar los artefactos a S3 o GCS es cuestión de configuración.
- Negativas: tres contenedores más que mantener; el cliente y el servidor deben actualizarse juntos.
- Reconsiderar si: la organización ya tiene un registry gestionado en su nube, o se necesita control de
  acceso por usuario (MLflow OSS no lo trae; habría que poner un proxy de autenticación).
