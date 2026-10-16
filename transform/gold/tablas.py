"""Tablas gold a partir de silver (Fase 3): features y scores por reglas.

Como en silver, funciones puras sobre listas de filas. Todo se calcula "a
fecha": las features de un día solo usan partidos anteriores a ese día, así que
los scores de días pasados se pueden recalcular y comparar con lo que pasó.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta

from transform.gold import reglas

ESQUEMAS: dict[str, list[str]] = {
    "features_jugador": [
        "jugador_id", "fecha", "valor", "var_1d_pct", "media_3d_pct", "media_7d_pct",
        "var_30d_pct", "dias_subiendo", "estado", "partidos_temporada", "media_puntos_temp",
        "forma5", "p_juega5", "minutos_ult3",
    ],
    "score_revalorizacion": [
        "jugador_id", "fecha", "valor", "subida_1d_pct", "subida_3d_pct", "subida_3d_eur",
        "estado", "disponible",
    ],
    "score_puntos_esperados": [
        "fecha_calculo", "jugador_id", "partido_id", "jornada_id", "jornada", "local",
        "rival_id", "dificultad", "estado", "en_once_probable", "media_puntos_temp", "forma5",
        "p_juega", "factor_rival", "puntos_esperados",
    ],
    # Lo escribe la Fase 4/5 (una fila por propuesta); aquí solo se define.
    "log_acciones": [
        "propuesta_id", "creada_utc", "tipo", "jornada_id", "paquete", "explicacion", "estado",
        "caduca_utc", "respondida_utc", "ejecutada_utc", "resultado",
    ],
}


def _dia(fecha: str, n: int) -> str:
    return (date.fromisoformat(fecha) + timedelta(days=n)).isoformat()


def _pct(actual: int | None, antes: int | None) -> float | None:
    if actual is None or not antes:
        return None
    return (actual - antes) / antes * 100


def _r(x: float | None, n: int = 3) -> float | None:
    return None if x is None else round(x, n)


def features_jugador(valor_diario: list[dict], puntos: list[dict]) -> list[dict]:
    """Una fila por jugador y día con valor: tendencias de valor y forma deportiva a esa fecha."""
    serie: dict[int, dict[str, dict]] = defaultdict(dict)
    for r in valor_diario:
        serie[r["jugador_id"]][r["fecha"]] = r

    partidos: dict[int, list[dict]] = defaultdict(list)
    for p in puntos:
        partidos[p["jugador_id"]].append(p)
    for ps in partidos.values():
        ps.sort(key=lambda p: p["fecha"])

    filas = []
    for jid, dias in serie.items():
        ps = partidos.get(jid, [])
        fechas_partido = [p["fecha"] for p in ps]
        racha = 0
        for fecha in sorted(dias):
            v = dias[fecha]["valor"]
            hace = lambda n: (dias.get(_dia(fecha, -n)) or {}).get("valor")  # noqa: E731
            var_1d = _pct(v, hace(1))
            racha = racha + 1 if var_1d is not None and var_1d > 0 else 0
            m3, m7 = _pct(v, hace(3)), _pct(v, hace(7))

            antes = ps[: bisect_left(fechas_partido, fecha)]  # solo partidos anteriores a ese día
            jugados = [p["puntos"] for p in antes if p["jugo"] and p["puntos"] is not None]
            ult = antes[-reglas.PARTIDOS_FORMA:]
            jug_ult = [p["puntos"] for p in ult if p["jugo"] and p["puntos"] is not None]
            minutos = [p["minutos"] for p in antes if p.get("minutos") is not None][-3:]

            filas.append({
                "jugador_id": jid,
                "fecha": fecha,
                "valor": v,
                "var_1d_pct": _r(var_1d),
                "media_3d_pct": _r(m3 / 3 if m3 is not None else None),
                "media_7d_pct": _r(m7 / 7 if m7 is not None else None),
                "var_30d_pct": _r(_pct(v, hace(30))),
                "dias_subiendo": racha,
                "estado": dias[fecha].get("estado"),
                "partidos_temporada": len(antes),
                "media_puntos_temp": _r(sum(jugados) / len(jugados)) if jugados else None,
                "forma5": _r(sum(jug_ult) / len(jug_ult)) if jug_ult else None,
                "p_juega5": _r(len(jug_ult) / len(ult)) if ult else None,
                "minutos_ult3": _r(sum(minutos) / len(minutos), 1) if minutos else None,
            })
    return sorted(filas, key=lambda f: (f["jugador_id"], f["fecha"]))


def score_revalorizacion(features: list[dict]) -> list[dict]:
    """Subida esperada del valor a 1 y 3 días, por inercia (ver reglas.py)."""
    filas = []
    for f in features:
        if f["var_1d_pct"] is None or f["media_3d_pct"] is None:
            continue
        s1 = reglas.subida_1d(f["var_1d_pct"], f["media_3d_pct"])
        s3 = reglas.subida_3d(f["var_1d_pct"], f["media_3d_pct"])
        filas.append({
            "jugador_id": f["jugador_id"],
            "fecha": f["fecha"],
            "valor": f["valor"],
            "subida_1d_pct": round(s1, 3),
            "subida_3d_pct": round(s3, 3),
            "subida_3d_eur": round(f["valor"] * s3 / 100),
            "estado": f["estado"],
            "disponible": f["estado"] not in reglas.NO_DISPONIBLE,
        })
    return filas


def score_puntos_esperados(
    features: list[dict], calendario: list[dict], once: list[dict], jugadores: list[dict]
) -> list[dict]:
    """Puntos esperados en el siguiente partido de cada jugador, para cada día con foto.

    Solo se calcula en los días con foto de la competición (los que tienen
    estado), porque son los únicos con estado y once probable de ese día.
    """
    equipo = {j["jugador_id"]: j["equipo_id"] for j in jugadores}
    partidos_equipo: dict[int, list[dict]] = defaultdict(list)
    for p in calendario:
        if p["estado"] == "postponed" or p["fecha"] is None:
            continue
        for lado in ("local_id", "visitante_id"):
            partidos_equipo[p[lado]].append(p)
    for ps in partidos_equipo.values():
        ps.sort(key=lambda p: (p["fecha"], p["partido_id"]))

    en_once: dict[tuple[str, int], set[int]] = defaultdict(set)
    for o in once:
        en_once[(o["fecha"], o["partido_id"])].add(o["jugador_id"])

    filas = []
    for f in features:
        if f["estado"] is None:  # sin foto ese día
            continue
        eq = equipo.get(f["jugador_id"])
        siguiente = next((p for p in partidos_equipo.get(eq, []) if p["fecha"] >= f["fecha"]), None)
        if siguiente is None:
            continue
        local = siguiente["local_id"] == eq
        dificultad = siguiente["dificultad_local" if local else "dificultad_visitante"]
        onces = en_once.get((f["fecha"], siguiente["partido_id"]))
        sale = (f["jugador_id"] in onces) if onces else None  # None = no hay once publicado

        base = None
        if f["media_puntos_temp"] is not None:
            base = (reglas.PESO_MEDIA_TEMPORADA * f["media_puntos_temp"]
                    + reglas.PESO_FORMA * (f["forma5"] if f["forma5"] is not None else f["media_puntos_temp"]))
        p = reglas.p_juega(f["p_juega5"], sale, f["estado"])
        factor = reglas.factor_rival(dificultad)
        filas.append({
            "fecha_calculo": f["fecha"],
            "jugador_id": f["jugador_id"],
            "partido_id": siguiente["partido_id"],
            "jornada_id": siguiente["jornada_id"],
            "jornada": siguiente["jornada"],
            "local": local,
            "rival_id": siguiente["visitante_id" if local else "local_id"],
            "dificultad": dificultad,
            "estado": f["estado"],
            "en_once_probable": sale,
            "media_puntos_temp": f["media_puntos_temp"],
            "forma5": f["forma5"],
            "p_juega": round(p, 3),
            "factor_rival": round(factor, 3),
            "puntos_esperados": round(base * p * factor, 2) if base is not None else 0.0,
        })
    return filas
