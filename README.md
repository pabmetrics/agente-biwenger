# Agente Biwenger

Agente que propone cada día fichajes y ventas orientados a revalorización y, la víspera de cada jornada, la alineación. En Biwenger solo ejecuta lo que se confirma por Telegram.

Stack: Databricks (ingesta, lakehouse Delta, scores) · API de Claude (agente con herramientas de solo lectura) · Bot de Telegram · Azure Function (ejecuta lo confirmado).

Diseño completo: [docs/diseno-agente-biwenger.md](docs/diseno-agente-biwenger.md). Lo que hay que preparar a mano (bot, claves, Databricks): [docs/puesta-en-marcha.md](docs/puesta-en-marcha.md).

## Puesta en marcha (local)

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # y rellena el token
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ingest.ingesta_diaria          # foto diaria a bronze
.venv\Scripts\python -m ingest.backfill_jugadores      # ~1 año de precios (por tandas de 150)
.venv\Scripts\python -m ingest.backfill_jornadas       # jornadas terminadas: titularidad y minutos
.venv\Scripts\python -m transform.silver.construir     # bronze -> silver (se recalcula entero)
.venv\Scripts\python -m transform.gold.construir       # bronze -> silver -> gold (features y scores)
.venv\Scripts\python -m agent.agente --no-enviar       # propuesta del día por pantalla (sin --no-enviar, por Telegram)
```

Bronze se escribe en `data/bronze/` (ignorado por git) o en `BRONZE_PATH`; silver, en `data/silver/` (un CSV por tabla en local) o en `SILVER_PATH`. Endpoints y campos: [docs/api-biwenger.md](docs/api-biwenger.md).

## Estado

- [x] Fase 1: ingesta — job `biwenger-diario` en Databricks cada día a las 7:30 (Madrid), bronze en `/Volumes/biwenger/bronze/raw`, avisos por Telegram
- [x] Fase 2: silver — 10 tablas en Delta (`biwenger.silver.*`), reconstruidas por el mismo job
- [x] Fase 3: gold con reglas — `features_jugador`, `score_revalorizacion` y `score_puntos_esperados` en `biwenger.gold.*`, con backtest en `transform/gold/reglas.py`; `log_acciones` creada vacía
- [x] Fase 4: agente de solo lectura — Claude (Sonnet 5, esfuerzo medio; configurable con `AGENTE_MODELO` / `AGENTE_ESFUERZO`) propone cada día a las 7:30 (compras, ventas, ofertas y, la víspera, la alineación) por Telegram; reglas duras validadas en código (`agent/validacion.py`); cada propuesta en `biwenger.gold.log_acciones`. ~0,18 $ por ejecución (~0,39 $ con Opus 5)
- [ ] Fase 5: confirmación y acciones
- [ ] Fase 6: modelo ML
