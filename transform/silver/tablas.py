"""Tablas silver a partir de bronze (Fase 2).

Cada función recibe registros de bronze y devuelve filas (dicts) con las
columnas de ESQUEMAS. Son funciones puras: las mismas sirven en local y en
Databricks, donde las filas se pasan a spark.createDataFrame y se escriben en Delta.

Fechas como 'AAAA-MM-DD' y momentos como ISO en UTC. 'fecha' es siempre el día
de la foto (partición de bronze), no el de la llamada a la API.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from transform.silver.lector import Registro, ultimo_por_clave, ultimo_por_dia

ESQUEMAS: dict[str, list[str]] = {
    "dim_jugador": [
        "jugador_id", "nombre", "slug", "equipo_id", "equipo", "posicion", "posicion_nombre",
        "estado", "estado_info", "estado_desde", "fecha",
    ],
    "fact_valor_diario": ["jugador_id", "fecha", "valor", "variacion", "origen"],
    "fact_puntos_jornada": [
        "jugador_id", "partido_id", "jornada_id", "jornada", "fecha", "local", "rival_id",
        "jugo", "puntos", "titular", "minuto_entrada", "minuto_salida", "minutos",
    ],
    "dim_calendario": [
        "partido_id", "jornada_id", "jornada", "fecha", "inicio_utc", "local_id", "local",
        "visitante_id", "visitante", "goles_local", "goles_visitante", "estado",
    ],
    "fact_once_probable": ["fecha", "jornada_id", "partido_id", "equipo_id", "jugador_id"],
    "fact_mercado_dia": [
        "fecha", "jugador_id", "precio", "vendedor_id", "vendedor_es_biwenger",
        "publicado_utc", "cierre_utc",
    ],
    "mi_plantilla": ["fecha", "jugador_id", "fecha_compra", "precio_compra", "alineado"],
    "mis_ventas": ["fecha", "jugador_id", "precio_pedido", "publicado_utc", "cierre_utc"],
    "mi_saldo": ["fecha", "saldo", "puja_maxima", "valor_equipo", "puntos", "posicion_liga"],
}

POSICIONES = {1: "Portero", 2: "Defensa", 3: "Centrocampista", 4: "Delantero", 5: "Entrenador"}

# Eventos de partido en los reports de una jornada. Deducidos de la jornada 8:
# en cada equipo, los jugadores sin evento ENTRA son exactamente 11.
EVENTO_SALE = 4
EVENTO_ENTRA = 5
MINUTOS_PARTIDO = 90


def _fecha(epoch: int | None) -> str | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, timezone.utc).date().isoformat()


def _ts(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _fecha_aammdd(n: int) -> str:
    """Los históricos de precio usan AAMMDD: 261014 -> 2026-10-14."""
    return date(2000 + n // 10000, n // 100 % 100, n % 100).isoformat()


def _dia_anterior(fecha: str) -> str:
    return (date.fromisoformat(fecha) - timedelta(days=1)).isoformat()


# --- jugadores y valor -------------------------------------------------------


def dim_jugador(competicion: list[Registro]) -> list[dict]:
    """Foto más reciente de cada jugador: equipo, posición y estado."""
    if not competicion:
        return []
    r = competicion[-1]
    equipos = {int(k): v["name"] for k, v in r.data.get("teams", {}).items()}
    filas = []
    for j in r.data["players"].values():
        filas.append({
            "jugador_id": j["id"],
            "nombre": j["name"],
            "slug": j["slug"],
            "equipo_id": j.get("teamID"),
            "equipo": equipos.get(j.get("teamID")),
            "posicion": j["position"],
            "posicion_nombre": POSICIONES.get(j["position"]),
            "estado": j["status"],
            "estado_info": j.get("statusInfo"),
            "estado_desde": _fecha(j.get("statusChange")),
            "fecha": r.fecha,
        })
    return sorted(filas, key=lambda f: f["jugador_id"])


def fact_valor_diario(competicion: list[Registro], jugadores: list[Registro]) -> list[dict]:
    """Valor de mercado por jugador y día.

    Une dos fuentes: el histórico de ~1 año del detalle de cada jugador
    (backfill) y la foto diaria de la competición. Si coinciden en un día,
    manda la foto, que además trae la variación oficial.
    """
    valores: dict[tuple[int, str], dict] = {}
    for r in jugadores:  # en orden: el detalle más reciente sobrescribe
        jid = r.data["id"]
        for aammdd, precio in r.data.get("prices", []):
            valores[(jid, _fecha_aammdd(aammdd))] = {"valor": precio, "variacion": None, "origen": "historico"}
    for r in ultimo_por_dia(competicion):
        for j in r.data["players"].values():
            valores[(j["id"], r.fecha)] = {
                "valor": j["price"], "variacion": j.get("priceIncrement"), "origen": "foto",
            }

    filas = []
    for (jid, fecha), v in sorted(valores.items()):
        if v["variacion"] is None:
            previo = valores.get((jid, _dia_anterior(fecha)))
            if previo:
                v["variacion"] = v["valor"] - previo["valor"]
        filas.append({"jugador_id": jid, "fecha": fecha, **v})
    return filas


# --- partidos ----------------------------------------------------------------


def _partidos_de_jornadas(jornadas: list[Registro]) -> list[tuple[Registro, dict, dict]]:
    """(registro, jornada, partido) de cada partido de cada llamada a /rounds."""
    return [(r, r.data, g) for r in jornadas for g in r.data.get("games", [])]


def _minutos(eventos: list[dict]) -> tuple[bool, int | None, int | None, int]:
    """(titular, minuto de entrada, minuto de salida, minutos jugados aproximados).

    Aproximado: no cuenta el descuento ni las expulsiones (su código de evento
    aún no está identificado).
    """
    entra = next((e["metadata"] for e in eventos if e["type"] == EVENTO_ENTRA), None)
    sale = next((e["metadata"] for e in eventos if e["type"] == EVENTO_SALE), None)
    desde = min(entra or 0, MINUTOS_PARTIDO)
    hasta = min(sale if sale is not None else MINUTOS_PARTIDO, MINUTOS_PARTIDO)
    return entra is None, entra, sale, max(0, hasta - desde)


def fact_puntos_jornada(jugadores: list[Registro], jornadas: list[Registro]) -> list[dict]:
    """Puntos de la liga (puntuación 5) por jugador y partido terminado.

    Base: los reports del detalle de cada jugador (incluyen los partidos que no
    jugó). Las jornadas terminadas añaden titularidad y minutos, y los jugadores
    que aún no tienen detalle en bronze.
    """
    filas: dict[tuple[int, int], dict] = {}
    for r in ultimo_por_clave(jugadores):
        jid = r.data["id"]
        for rep in r.data.get("reports", []):
            m = rep["match"]
            if m.get("status") != "finished":
                continue
            local = rep["home"]
            puntos = rep.get("points", {}).get("5") if rep.get("points") else None
            filas[(jid, m["id"])] = {
                "jugador_id": jid,
                "partido_id": m["id"],
                "jornada_id": m["round"]["id"],
                "jornada": m["round"]["name"],
                "fecha": _fecha(m["date"]),
                "local": local,
                "rival_id": (m["away"] if local else m["home"])["id"],
                "jugo": "points" in rep,
                "puntos": puntos,
                "titular": None, "minuto_entrada": None, "minuto_salida": None, "minutos": None,
            }

    for _, jornada, g in _partidos_de_jornadas(jornadas):
        if g.get("status") != "finished":
            continue
        for lado, otro in (("home", "away"), ("away", "home")):
            for rep in g[lado].get("reports", []):
                jid = rep["player"]["id"]
                titular, entra, sale, minutos = _minutos(rep.get("events", []))
                fila = filas.setdefault((jid, g["id"]), {
                    "jugador_id": jid,
                    "partido_id": g["id"],
                    "jornada_id": jornada["id"],
                    "jornada": jornada["name"],
                    "fecha": _fecha(g["date"]),
                    "local": lado == "home",
                    "rival_id": g[otro]["id"],
                })
                fila.update({
                    "jugo": True,
                    "puntos": rep.get("points") if fila.get("puntos") is None else fila["puntos"],
                    "titular": titular,
                    "minuto_entrada": entra,
                    "minuto_salida": sale,
                    "minutos": minutos,
                })
    return [filas[k] for k in sorted(filas)]


def dim_calendario(
    competicion: list[Registro], jornadas: list[Registro], jugadores: list[Registro]
) -> list[dict]:
    """Un partido por fila, con la información más reciente de todas las fuentes."""
    vistos: list[tuple[str, dict]] = []  # (ingest_ts, campos del partido)

    def campos(g: dict, jornada: dict | None) -> dict:
        h, a = g.get("home", {}), g.get("away", {})
        return {
            "partido_id": g["id"],
            "jornada_id": (jornada or g.get("round") or {}).get("id"),
            "jornada": (jornada or g.get("round") or {}).get("name"),
            "fecha": _fecha(g.get("date")),
            "inicio_utc": _ts(g.get("date")),
            "local_id": h.get("id"),
            "local": h.get("name"),
            "visitante_id": a.get("id"),
            "visitante": a.get("name"),
            "goles_local": h.get("score"),
            "goles_visitante": a.get("score"),
            "estado": g.get("status"),
        }

    for r in jugadores:
        for rep in r.data.get("reports", []):
            vistos.append((r.ingest_ts, campos(rep["match"], None)))
    for r, jornada, g in _partidos_de_jornadas(jornadas):
        vistos.append((r.ingest_ts, campos(g, jornada)))
    equipos: dict[int, str] = {}
    for r in competicion:
        equipos.update({int(k): v["name"] for k, v in r.data.get("teams", {}).items()})
        for ev in r.data.get("activeEvents", []):
            if ev.get("type") == "round":
                for g in ev.get("games", []):
                    vistos.append((r.ingest_ts, campos(g, ev)))
        for t in r.data.get("teams", {}).values():
            for g in t.get("nextGames", []):
                vistos.append((r.ingest_ts, campos(g, None)))

    partidos: dict[int, dict] = {}
    for _, c in sorted(vistos, key=lambda x: x[0]):
        p = partidos.setdefault(c["partido_id"], dict.fromkeys(ESQUEMAS["dim_calendario"]))
        # Lo más reciente manda, pero un dato ausente no borra uno conocido.
        p.update({k: v for k, v in c.items() if v is not None})
    for p in partidos.values():
        p["local"] = p["local"] or equipos.get(p["local_id"])
        p["visitante"] = p["visitante"] or equipos.get(p["visitante_id"])
    return [partidos[k] for k in sorted(partidos)]


def fact_once_probable(jornadas: list[Registro]) -> list[dict]:
    """Onces probables publicados para los partidos aún sin jugar, por día de foto."""
    filas: dict[tuple, dict] = {}
    for r, jornada, g in _partidos_de_jornadas(jornadas):
        if g.get("status") == "finished":
            continue
        for lado in ("home", "away"):
            for rep in g[lado].get("reports", []):
                k = (r.fecha, g["id"], rep["player"]["id"])
                filas[k] = {
                    "fecha": r.fecha,
                    "jornada_id": jornada["id"],
                    "partido_id": g["id"],
                    "equipo_id": g[lado]["id"],
                    "jugador_id": rep["player"]["id"],
                }
    return [filas[k] for k in sorted(filas)]


# --- mi liga -----------------------------------------------------------------


def fact_mercado_dia(mercado: list[Registro]) -> list[dict]:
    """Jugadores en venta cada día. Sin vendedor = los pone Biwenger."""
    filas = []
    for r in ultimo_por_dia(mercado):
        for s in r.data.get("sales", []):
            vendedor = s.get("user")
            filas.append({
                "fecha": r.fecha,
                "jugador_id": s["player"]["id"],
                "precio": s["price"],
                "vendedor_id": vendedor["id"] if vendedor else None,
                "vendedor_es_biwenger": vendedor is None,
                "publicado_utc": _ts(s.get("date")),
                "cierre_utc": _ts(s.get("until")),
            })
    return filas


def ofertas_sin_mapear(mercado: list[Registro]) -> int:
    """fact_ofertas espera a ver una oferta real: hasta entonces solo se cuentan."""
    return sum(len(r.data.get("offers", [])) for r in ultimo_por_dia(mercado))


def mi_plantilla(plantilla: list[Registro]) -> list[dict]:
    """Mis jugadores cada día (la liga no tiene cláusulas)."""
    filas = []
    for r in ultimo_por_dia(plantilla):
        alineados = set(r.data.get("lineup", {}).get("playersID") or [])
        for p in r.data.get("players", []):
            owner = p.get("owner") or {}
            filas.append({
                "fecha": r.fecha,
                "jugador_id": p["id"],
                "fecha_compra": _fecha(owner.get("date")),
                "precio_compra": owner.get("price"),
                "alineado": p["id"] in alineados,
            })
    return filas


def mis_ventas(plantilla: list[Registro]) -> list[dict]:
    """Mis jugadores a la venta cada día y el precio que pido.

    Un mánager que pague precio_pedido se lo lleva sin que yo confirme nada.
    """
    filas = []
    for r in ultimo_por_dia(plantilla):
        for v in r.data.get("market") or []:
            if v.get("type", "sale") != "sale":
                continue
            filas.append({
                "fecha": r.fecha,
                "jugador_id": v["playerID"],
                "precio_pedido": v.get("price"),
                "publicado_utc": _ts(v.get("date")),
                "cierre_utc": _ts(v.get("until")),
            })
    return filas


def mi_saldo(plantilla: list[Registro], mercado: list[Registro], liga: list[Registro]) -> list[dict]:
    """Saldo diario, con la puja máxima del mercado y mi fila de la clasificación."""
    mercado_dia = {r.fecha: r.data for r in ultimo_por_dia(mercado)}
    liga_dia = {r.fecha: r.data for r in ultimo_por_dia(liga)}
    filas = []
    for r in ultimo_por_dia(plantilla):
        yo = next(
            (s for s in liga_dia.get(r.fecha, {}).get("standings", []) if s["id"] == r.data["id"]),
            {},
        )
        filas.append({
            "fecha": r.fecha,
            "saldo": r.data.get("balance"),
            "puja_maxima": mercado_dia.get(r.fecha, {}).get("status", {}).get("maximumBid"),
            "valor_equipo": yo.get("teamValue"),
            "puntos": r.data.get("points"),
            "posicion_liga": yo.get("position"),
        })
    return filas
