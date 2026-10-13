# Spike de Feast (fase 6)

Evaluación **acotada** de Feast para las variables de contexto del modelo de SLA. No es parte de la
plataforma: vive aquí, con su propio entorno, porque Feast 0.66 exige `pandas<3` y la plataforma
usa pandas 3.

Decisión y números: [ADR 0010](../../docs/adr/0010-feature-store-feast-no-por-ahora.md) y
[resultados de la fase 6](../../docs/results/fase6_features_sla_risk.md).

```bash
make up                 # Postgres
make data ARGS="--days 300 --drift-start 2025-08-15 --drift-capacity 85"
make feast-export       # nuestro cálculo → serie horaria en el esquema feast_spike
make feast-spike        # instala este entorno (~490 MB) y corre run_spike.py
make feast-clean        # borra esquemas, registro y entorno
```

| Archivo | Qué es |
|---|---|
| `feature_repo/feature_store.yaml` | Postgres como almacén offline (historia) y online (último valor); credenciales del `.env` |
| `feature_repo/definitions.py` | Entidades (`team`, `category`) y vistas (`operations`, `category_context`) |
| `run_spike.py` | apply → join histórico + paridad → materialize → lectura en línea → alternativas sin Feast |

Resultado: `data/reports/features/feast_spike.json` del proyecto principal.
