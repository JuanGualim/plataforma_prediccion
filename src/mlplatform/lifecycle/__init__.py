"""Contrato de despliegue, puerta de promoción y rollback.

Fase 3. Solo POLÍTICA: valida que un modelo cumpla el contrato
(docs/deployment_standard.md) y decide si un candidato puede ser champion.
Se prueba sin MLflow porque recibe datos, no habla con el registry directamente.
"""
