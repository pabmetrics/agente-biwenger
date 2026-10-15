# Agente Biwenger — Documento de diseño

14 de octubre de 2026 · Pablo

## Objetivo y alcance

El agente propone cada día fichajes y ventas orientados a revalorización, y la víspera de cada jornada la alineación; ejecuta en Biwenger solo lo que confirmo por Telegram.

- **Dentro:** compras, ventas (con su precio de venta), aceptar ofertas y alineación de la jornada. En la liga no hay cláusulas.
- **Fuera (de momento):** gestión de varias ligas, chat libre con el agente y cambios de formación por táctica del rival.
- **Punto de partida:** no hay datos ingestados; el proyecto empieza por la ingesta.

## Decisiones de diseño

| Tema | Decisión | Implicación |
| --- | --- | --- |
| Fuente de datos | API interna de Biwenger (JSON con token) | Automatizable; no oficial, puede cambiar |
| Puntuación de la liga | Media (Picas AS + SofaScore) | El modelo predice una nota con componente subjetiva |
| Objetivo en fichajes | Revalorización | El dato clave es el valor de mercado diario |
| Reglas de saldo | Negativo permitido si se acompaña de ventas | El agente propone compras y ventas como un paquete |
| Canal | Telegram | Permite confirmar con botones |
| Frecuencia | Diario (mercado) + víspera de jornada (alineación) | Dos ejecuciones distintas |
| Contexto extra | Búsqueda web | Solo para jugadores dudosos |
| Autonomía | Actúa con confirmación | Hace falta un bot que escuche respuestas |
| Predicción | Modelo ML en Databricks + Claude | Scores en gold; Claude razona y explica |

## Arquitectura

Todo corre en mi stack: Databricks ingesta y calcula scores, un job llama a la API de Claude, y una Azure Function ejecuta en Biwenger solo lo confirmado.

```
API Biwenger ──> Ingesta diaria (job Databricks) ──> Lakehouse Delta (bronze/silver/gold + ML) ──> Agente Claude (tools lectura + web search)
     ^                                                                                                   │ propuestas
     │ pujar, vender, alinear                                                                            v
Azure Function (ejecuta lo confirmado) <── Sí (webhook) ── Yo, en el móvil <── mensaje ── Bot de Telegram (botones Sí/No)
```

Claude nunca tiene herramientas de escritura: el único camino de vuelta a Biwenger pasa por mi Sí en Telegram.

## Modelo de datos

Una ingesta diaria vuelca el JSON crudo a bronze; silver lo normaliza en tablas Delta y gold guarda las features y los scores que lee el agente.

| Capa | Tabla | Grano | Contenido |
| --- | --- | --- | --- |
| Bronze | `raw_<endpoint>` | Llamada a la API | JSON crudo + fecha de carga |
| Silver | `dim_jugador` | Jugador | Equipo, posición, estado (lesionado, dudoso, sancionado) |
| Silver | `fact_valor_diario` | Jugador × día | Valor de mercado y variación diaria |
| Silver | `fact_puntos_jornada` | Jugador × partido | Puntos Media, jugó sí/no, titularidad y minutos aproximados. Por partido y no por jornada porque hay jornadas aplazadas |
| Silver | `fact_once_probable` | Día × partido × jugador | Onces probables de los partidos sin jugar, tal como estaban cada día |
| Silver | `fact_mercado_dia` | Jugador en venta × día | Precio de salida, vendedor (liga o mánager) |
| Silver | `mi_plantilla` | Jugador propio × día | Precio y fecha de compra, alineado sí/no. Sin cláusula: la liga no tiene |
| Silver | `mis_ventas` | Jugador propio a la venta × día | Precio pedido (un mánager que lo pague se lo lleva sin confirmación), publicación y cierre |
| Silver | `mi_saldo` | Día | Saldo, puja máxima, valor de equipo y posición en la liga |
| Silver | `fact_ofertas` | Oferta | Jugador, importe, fecha límite. Pendiente hasta ver una oferta real en bronze |
| Silver | `dim_calendario` | Partido | Jornada, rival, local/visitante, fecha |
| Gold | `features_jugador` | Jugador × día | Tendencia de valor 3/7 días, forma, minutos, dificultad del rival |
| Gold | `score_revalorizacion` | Jugador × día | Subida esperada a 1 y 3 días (%) |
| Gold | `score_puntos_esperados` | Jugador × jornada | Puntos Media esperados |
| Gold | `log_acciones` | Propuesta | Qué propuso el agente, si lo confirmé y el resultado |

`log_acciones` permite medir después si las recomendaciones acertaron.

## Herramientas del agente

Claude solo tiene herramientas de lectura y de propuesta; las acciones en Biwenger las ejecuta la Azure Function tras mi confirmación.

| Herramienta | Tipo | Qué hace | Quién la ejecuta |
| --- | --- | --- | --- |
| `leer_plantilla_y_saldo` | Lectura | Plantilla, jugadores a la venta y saldo actual | Claude (SQL a gold/silver) |
| `leer_mercado_con_scores` | Lectura | Jugadores en venta con score de revalorización y puntos esperados | Claude |
| `leer_ofertas_recibidas` | Lectura | Ofertas abiertas por mis jugadores | Claude |
| `leer_jugador` | Lectura | Histórico de valor, puntos y próximos rivales de un jugador | Claude |
| `web_search` | Lectura | Noticias y alineaciones probables de jugadores dudosos | Claude (tool integrada de la API) |
| `proponer_accion` | Propuesta | Envía a Telegram la propuesta con botones Sí/No y la guarda en `log_acciones` | Claude |
| `pujar` / `vender` / `aceptar_oferta` / `alinear` | Escritura | Llama al endpoint de Biwenger | Azure Function, solo tras el Sí |

## Lógica de decisión

El modelo ML pone los números; Claude decide con ellos, el saldo y el contexto, y explica cada propuesta en una línea.

### Mercado diario (cada mañana, tras el cambio de mercado)

1. Leer plantilla, saldo, ofertas y mercado con scores.
2. Ordenar el mercado por subida esperada a 1–3 días, descartando lesionados y sancionados.
3. Elegir compras: mayor subida esperada por euro invertido.
4. Si el saldo queda negativo, añadir ventas hasta volver a cero antes del cierre de la jornada. Biwenger ofrece cada día a las 7:00 aproximadamente el valor de mercado (±5 %) por cada jugador en venta, así que la venta está garantizada si se pone a la venta la víspera; para tener margen, cuenta con el −5 %:
   1. Primero aceptar ofertas recibidas por encima del valor de mercado.
   2. Después vender jugadores con bajada esperada.
   3. Nunca dejar la plantilla sin un once válido en alguna formación disponible: las gratuitas, o las de pago si hay créditos.
5. Enviar un único paquete (compras + ventas) para confirmar.

### Alineación (víspera de jornada)

1. Leer plantilla y puntos esperados de la jornada.
2. Para cada jugador dudoso, `web_search` de noticias y alineaciones probables.
3. Elegir el once con más puntos esperados que cumpla una formación válida: las 7 gratuitas, o también las 7 de pago si hay créditos (lista en `docs/api-biwenger.md`).
4. Enviar la alineación para confirmar, marcando las dudas.

### Pendiente de definir

- Peso de la revalorización frente a los puntos en la alineación cuando un jugador se vende pronto.
- Tope de compras por día y límite de saldo negativo en euros.

## Flujo de confirmación por Telegram

Cada propuesta es un mensaje con botones; la Azure Function recibe el webhook y solo ejecuta si pulso Sí antes del cierre del mercado.

```
Agente propone compras + ventas ──> Telegram muestra botones Sí/No ──> ¿Confirmo?
                                                                        ├─ Sí ──> Function ejecuta en Biwenger ──> Resultado a Telegram y log
                                                                        └─ No, o caduca al cierre ──> Descartada y registrada en log
```

El paquete de compras y ventas se confirma entero para no quedar en saldo negativo sin las ventas que lo cubren.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
| --- | --- |
| La API interna cambia sin aviso | Validar el esquema en bronze y avisar por Telegram si falla la ingesta |
| El token de sesión caduca | Login programático o renovación manual con aviso previo |
| Exceso de llamadas a Biwenger | Una o dos ingestas al día y solo las acciones confirmadas |
| Modelo de revalorización sin histórico | Usar reglas simples (tendencia de valor) hasta tener varias semanas de snapshots |
| Acción ejecutada por error | Botón de confirmación por propuesta y caducidad de la propuesta al cierre del mercado |
| Coste de la API de Claude | Búsqueda web solo para dudosos; contexto acotado a gold |
| Credenciales expuestas | Token y clave del bot en Azure Key Vault / secret scope de Databricks |

## Plan de implementación

Cada fase entrega algo usable; el agente recomienda antes de tener el modelo ML y antes de actuar.

- [ ] **Fase 1 — Ingesta:** explorar los endpoints de la API, notebook bronze y job diario en Databricks.
- [ ] **Fase 2 — Silver:** tablas normalizadas y snapshot diario de valor y mercado.
- [ ] **Fase 3 — Gold con reglas:** features y scores por reglas simples (tendencia de valor, minutos, rival).
- [ ] **Fase 4 — Agente solo lectura:** llamada a la API de Claude con las herramientas de lectura y mensaje por Telegram.
- [ ] **Fase 5 — Confirmación y acciones:** bot de Telegram con botones y Azure Function que ejecuta las acciones.
- [ ] **Fase 6 — Modelo ML:** sustituir las reglas por modelos entrenados con el histórico acumulado y medir aciertos con `log_acciones`.
