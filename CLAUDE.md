# Agente Biwenger — contexto para Claude Code

El diseño completo está en @docs/diseno-agente-biwenger.md. Léelo antes de tocar nada: es la fuente de verdad.

## Cómo trabajar en este repo

- Seguimos el plan de implementación por fases del documento de diseño: Ingesta → Silver → Gold con reglas → Agente solo lectura → Confirmación y acciones → Modelo ML. No saltes de fase sin que la anterior entregue algo usable.
- Stack: Databricks (jobs, Delta, bronze/silver/gold), API de Claude para el agente, bot de Telegram y Azure Function para ejecutar acciones.
- Estructura:
  - `ingest/` — llamadas a la API interna de Biwenger → bronze (`raw_<endpoint>`, JSON crudo + fecha de carga). Bronze es append-only.
  - `transform/silver/`, `transform/gold/` — tablas normalizadas, features y scores.
  - `agent/` — llamada a la API de Claude y herramientas del agente.
  - `azure_function/` — webhook de Telegram y ejecución de acciones en Biwenger.
  - `tests/`, `docs/`.

## Reglas duras

- **El agente nunca tiene herramientas de escritura sobre Biwenger.** Solo lectura y `proponer_accion`. Pujar, vender, aceptar ofertas y alinear lo ejecuta únicamente la Azure Function tras un "Sí" en Telegram, antes del cierre del mercado.
- Los paquetes de compras + ventas se confirman enteros, nunca a medias.
- Nada de secretos en el repo (token de Biwenger, clave de Claude, token del bot): van en Azure Key Vault o en un secret scope de Databricks. En local, `.env` (ignorado por git).
- La API de Biwenger es interna y no oficial: llamadas mínimas (una o dos ingestas al día), validar el esquema en bronze y avisar si cambia.
- Toda propuesta queda en `log_acciones`, se confirme o no.
