# Agente Biwenger

Agente que propone cada día fichajes y ventas orientados a revalorización y, la víspera de cada jornada, la alineación. En Biwenger solo ejecuta lo que se confirma por Telegram.

Stack: Databricks (ingesta, lakehouse Delta, scores) · API de Claude (agente con herramientas de solo lectura) · Bot de Telegram · Azure Function (ejecuta lo confirmado).

Diseño completo: [docs/diseno-agente-biwenger.md](docs/diseno-agente-biwenger.md).

## Estado

- [ ] Fase 1: ingesta
- [ ] Fase 2: silver
- [ ] Fase 3: gold con reglas
- [ ] Fase 4: agente de solo lectura
- [ ] Fase 5: confirmación y acciones
- [ ] Fase 6: modelo ML
