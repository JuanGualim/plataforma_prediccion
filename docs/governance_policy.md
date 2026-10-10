# Política de gobierno de modelos de ML y GenAI

> **Estado:** esqueleto (fase 1). Se completa principalmente en las fases 3, 5 y 8.
> Es una política breve y aplicable, no un documento legal.

## 1. Alcance

Aplica a todos los modelos desplegados en la plataforma: modelos predictivos (tabulares y de
texto) y aplicaciones con LLM (RAG).

## 2. Roles

| Rol | Responsabilidad |
|---|---|
| Dueño del modelo (equipo de Data Science) | _Por definir_ |
| Equipo de plataforma (MLOps) | _Por definir_ |
| Aprobador de negocio | _Por definir_ |

## 3. Aprobaciones

_Por definir: quién aprueba una promoción a champion y qué evidencia se exige._

## 4. Información personal

- **Datos de entrenamiento:** _por definir_.
- **Prompts y contexto enviados a LLM:** _por definir (fase 8): enmascarado de información personal antes de enviar el texto, qué proveedores están permitidos._
- **Logs:** _por definir: qué se guarda de cada request y qué no, y cuánto tiempo se retiene._

## 5. Monitoreo obligatorio

_Por definir (fase 5): umbrales mínimos de alertas por nivel (servicio, datos, modelo)._

## 6. Retiro de modelos

_Por definir: criterios para archivar un modelo y qué se conserva para auditoría._

## 7. Específico de GenAI

_Por definir (fase 8): versionado de prompts, evaluación antes de desplegar, límites de costo por consulta._
