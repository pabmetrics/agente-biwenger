# API de Biwenger — diccionario de endpoints y campos

Explorada el 14/10/2026 (temporada 2026/2027, jornada 9 en preview). La API es interna y no oficial: puede cambiar sin aviso. Por eso `ingest/bronze.py` valida un esquema mínimo y la ingesta falla, conservando el crudo, si falta alguna clave.

Todas las respuestas vienen envueltas como `{"status": 200, "data": {...}}`. Las fechas son epoch en segundos, salvo los precios, que usan el formato `AAMMDD`.

## Hallazgo principal

**Casi todo lo que necesita el modelo es público y no requiere token.** Hay tres datos que lo cambian todo respecto al documento de diseño:

1. **Histórico de precios de ~1 año** en el detalle de cada jugador (366 puntos diarios). El riesgo "modelo de revalorización sin histórico" desaparece: el backfill lo trae desde el primer día.
2. **Puntos por partido en todas las puntuaciones**, incluida la de la liga (`score=5`, "Media AS y SofaScore").
3. **Onces probables** de la jornada en preview, para los 20 equipos (11 por equipo). Es la señal de titularidad para la alineación, antes de recurrir a `web_search`.

Lo único que exige token es lo propio de mi liga: plantilla, saldo, mercado de la liga y ofertas.

## Endpoints públicos (`https://cf.biwenger.com/api/v2`)

Parámetros comunes: `lang=es` y `score=5`. Basta con la cabecera `User-Agent`.

| Método en `biwenger_api.py` | Ruta | Bronze | Qué trae |
| --- | --- | --- | --- |
| `competicion()` | `/competitions/la-liga/data` | `raw_competicion` | Foto del día: 550 jugadores, 20 equipos con próximos partidos, temporada con sus jornadas, `activeEvents` (jornada en curso) |
| `jornadas()` | `/rounds/la-liga` | `raw_jornadas` | Última jornada: partidos, clasificación de LaLiga, MVP, once ideal |
| `jornada(id)` | `/rounds/la-liga/{id}` | `raw_jornada` (clave = id) | Partidos de una jornada; en `preview`, los onces probables en `games[].home/away.reports[]` |
| `jugador(slug)` | `/players/la-liga/{slug}` + `fields=*,team,fitness,reports(...),prices,competition,seasons` | `raw_jugador` (clave = id) | Detalle: precios diarios, puntos por partido, temporadas, noticias |

### Jugador en `competicion.data.players[<id>]`

| Campo | Significado |
| --- | --- |
| `id`, `slug`, `name`, `teamID` | Identidad. `slug` es lo que pide `jugador()` |
| `position` | 1 portero · 2 defensa · 3 centrocampista · 4 delantero · 5 entrenador (la liga los tiene activados: `config.coaches`) |
| `altPositions` | Posiciones alternativas (opcional) |
| `price` | Valor de mercado actual (€) |
| `priceIncrement` | Variación del valor desde ayer (€). **Es el dato clave para la revalorización** |
| `fantasyPrice` | Precio en el modo "fantasy". No se usa |
| `status` | `ok`, `injured`, `doubt`, `warned` (apercibido), `sanctioned`, `unknown`. Hoy: 479 / 39 / 19 / 7 / 5 / 1 |
| `statusInfo`, `statusChange` | Texto de la lesión o sanción (con retorno estimado si lo hay) y epoch del cambio de estado |
| `fitness` | Puntos de los **últimos 5 partidos, el más reciente primero**. `null` = no jugó; texto (`injured`, `doubt`, `sanctioned`) = no disponible ese partido |
| `points`, `pointsHome`, `pointsAway`, `playedHome`, `playedAway` | Acumulados de la temporada con la puntuación pedida (`score`) |
| `pointsLastSeason` | Puntos de la temporada anterior |

### Detalle de jugador (`jugador()`)

| Campo | Significado |
| --- | --- |
| `prices` | `[[AAMMDD, precio], ...]`, ~366 días. Ej.: `[261014, 5690000]` = 14/10/2026 |
| `reports[]` | Un elemento por partido: `match` (rival, marcador, jornada, fecha), `home` (bool) y `points`: un objeto con una entrada por puntuación, cuya clave es su id: `{"1": AS, "2": SofaScore, "3": Estadísticas, "5": Media AS+SofaScore, "6": Social, "7": Feeberse, "8": Media AS+Feeberse}` |
| `seasons[]` | Partidos y puntos por temporada, por puntuación |

En `reports[]`, un partido **sin `points` es un partido que no jugó**. No traen eventos, porque `jugador()` pide `events.type(0)`, así que los minutos salen de las jornadas.

### Partidos de una jornada (`jornadas()` / `jornada(id)`)

En una jornada terminada, `games[].home/away.reports[]` trae solo a los que jugaron: `player`, `points` (de la puntuación pedida, la 5), `events[]`, `star`, `mvp`, etc. Cada evento es `{type, period, metadata}`, donde `metadata` es el minuto.

| `type` | Significado | Cómo se sabe |
| --- | --- | --- |
| 4 | Sale (sustituido) | Mismo número que los tipo 5 en la jornada 8 (86) |
| **5** | **Entra (suplente)** | En cada equipo, los jugadores sin tipo 5 son exactamente 11 |
| 1, 6, … | Sin confirmar (6 parece amarilla; 1, gol) | Pendiente; los minutos no los usan |

Con 4 y 5, silver calcula `titular` y unos `minutos` aproximados: no cuentan el descuento ni las expulsiones. En `preview`, `reports[]` es el once probable: `{player, points: null}`, 11 por equipo.
| `birthday`, `country`, `team` | Datos del jugador |

### Puntuaciones (`competicion.data.scores`)

| id | Nombre |
| --- | --- |
| 1 | Diario AS |
| 2 | SofaScore |
| 3 | Estadísticas |
| **5** | **Media AS y SofaScore (la de mi liga)** |
| 6 | Biwenger Social |
| 7 | Feeberse Score |
| 8 | Media AS y Feeberse |

## Endpoints privados (`https://biwenger.as.com/api/v2`)

Sin token devuelven `401 Authorization required` (comprobado). Cabeceras: `Authorization: Bearer <token>`, `X-League: <id liga>`, `X-User: <id usuario en la liga>`, `X-Lang: es`.

**Rutas verificadas con token el 14/10/2026:** las cuatro responden 200. Las claves en negrita son las que exige `bronze.ESQUEMA_MINIMO`.

| Método | Ruta | Bronze | Para qué |
| --- | --- | --- | --- |
| `cuenta()` | `GET /account` | `raw_cuenta` | Mis ligas y mi id de usuario en cada una → `BIWENGER_LEAGUE_ID`, `BIWENGER_USER_ID` |
| `plantilla()` | `GET /user?fields=*,lineup(type,playersID),players(id,owner),market` | `raw_plantilla` | `mi_plantilla`, `mi_saldo`, alineación actual, cláusulas |
| `mercado()` | `GET /market` | `raw_mercado` | `fact_mercado_dia` (jugadores en venta) y `fact_ofertas` (ofertas recibidas) |
| `liga()` | `GET /league?include=all&fields=*,standings` | `raw_liga` | Clasificación y mánagers |

El token es un JWT HS256 de 125 caracteres (`cabecera.datos.firma`, con una firma de 43). Solo trae `iss` e `iat`, **sin `exp`**: no caduca por fecha, sino cuando Biwenger cierra la sesión. La firma puede contener `-` y `_`, así que hay que copiarlo entero.

### `cuenta()` → `data`

| Campo | Contenido |
| --- | --- |
| **`account`** | Mi cuenta: `id`, `name`, `email`, `phone`, `birthday`, `credits`, `locale`, `created`, `lastAccess`, `status`… **Datos personales: no pasan de bronze a silver** |
| **`leagues[]`** | Una por liga: `id`, `name`, `competition`, `mode`, `marketMode`, `scoreID`, `type`, `upgrades`, `user` (mi usuario en esa liga, de donde sale `X-User`) y `settings` (reglas: cláusula, préstamos, alineación…). `settings.secret` es el código de invitación: no pasa a silver |
| `location`, `notifications`, `version`, `lastOfficialLeagueChange` | No se usan |

### `plantilla()` → `data`

| Campo | Contenido |
| --- | --- |
| **`id`**, `name`, `icon`, `role`, `joinDate`, `lastAccess`, `points` | Mi usuario en la liga |
| **`balance`** | Saldo → `mi_saldo` |
| **`players[]`** | `{id, owner: {date, price}}`: mis jugadores con fecha y precio de compra. **No trae la cláusula**: la liga tiene `settings.clause = "salePrice"`, así que probablemente se derive del valor de mercado (pendiente de confirmar) |
| **`lineup`** | `{type, playersID, date}`: formación y once actual. Un hueco sin jugador viene como `null` en `playersID` |
| `market` | Lista: mis jugadores puestos en venta |

### `mercado()` → `data`

| Campo | Contenido |
| --- | --- |
| **`sales[]`** | En venta hoy: `player`, `price`, `user` (vendedor; vacío si es Biwenger), `date`, `until` (cierre) |
| **`offers`** | Lista de ofertas recibidas. Falta ver la forma de un elemento: hay que mirarla en bronze el primer día que haya una oferta |
| **`status`** | `{balance, maximumBid}`: saldo y puja máxima permitida |

### `liga()` → `data`

| Campo | Contenido |
| --- | --- |
| **`id`**, `name`, `mode`, `marketMode`, `scoreID`, `type`, `created`, `icon`, `cover` | La liga |
| **`standings[]`** | Por mánager: `id`, `name`, `position`, `points`, `teamValue`, `teamValueInc`, `teamSize`, `lastPositions`, `lastTrophy`, `role`, `lastAccess` |

Escritura (Fase 5, solo desde la Azure Function, nunca desde el agente): pujar, vender, aceptar oferta y alinear. Sin explorar: se documentarán al llegar a esa fase observando las peticiones que hace la web.

## Ritmo y volumen

- Ingesta diaria: 3 llamadas públicas + 4 privadas.
- **Límite de peticiones (comprobado el 14/10/2026):** tras ~200 llamadas seguidas a 1/s, `cf.biwenger.com` responde `429 Too Many Requests` ("vuelva a intentarlo en unas horas"). El cliente lanza `LimiteSuperado` y no reintenta.
- Backfill de jugadores: ~550 llamadas, en tandas de 150 con 3 s entre llamadas. Es reanudable (se salta los jugadores ya guardados en bronze) y se para en el primer 429. Se hace una vez; después, como mucho, se refresca por tandas semanales: la variación diaria ya llega en `competicion`.
- El cliente espera 1 s entre llamadas (3 s en el backfill) y reintenta los 5xx y los errores de red con espera exponencial.
