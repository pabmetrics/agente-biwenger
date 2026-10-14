# Agente Biwenger

Agente que propone cada día fichajes y ventas orientados a revalorización y, la víspera de cada jornada, la alineación. En Biwenger solo ejecuta lo que se confirma por Telegram.

Stack: Databricks (ingesta, lakehouse Delta, scores) · API de Claude (agente con herramientas de solo lectura) · Bot de Telegram · Azure Function (ejecuta lo confirmado).

Diseño completo: [docs/diseno-agente-biwenger.md](docs/diseno-agente-biwenger.md).

## Puesta en marcha (local)

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # y rellena el token
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ingest.ingesta_diaria          # foto diaria a bronze
.venv\Scripts\python -m ingest.backfill_jugadores      # ~1 año de precios (una vez)
```

Bronze se escribe en `data/bronze/` (ignorado por git) o en `BRONZE_PATH`. Endpoints y campos: [docs/api-biwenger.md](docs/api-biwenger.md).

## Estado

- [ ] Fase 1: ingesta — cliente, bronze y endpoints públicos hechos; faltan verificar los privados con token y el job en Databricks
- [ ] Fase 2: silver
- [ ] Fase 3: gold con reglas
- [ ] Fase 4: agente de solo lectura
- [ ] Fase 5: confirmación y acciones
- [ ] Fase 6: modelo ML
