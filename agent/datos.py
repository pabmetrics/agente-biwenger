"""Vista de solo lectura sobre silver y gold para las herramientas del agente.

El agente nunca llama a Biwenger: lee las tablas que el job ya ha construido
ese día (en memoria, las mismas filas que se escriben en Delta). Todo se
refiere a "hoy", que es la última foto de mi plantilla.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

# Formaciones que permite la app (docs/api-biwenger.md). Las de pago cuestan 1
# crédito, que el usuario consigue fácilmente viendo vídeos.
FORMACIONES_GRATIS = ["3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-3-2", "5-4-1"]
FORMACIONES_PAGO = ["3-6-1", "3-3-4", "4-2-4", "4-6-0", "5-2-3", "3-2-5", "5-1-4"]
POSICIONES = {1: "POR", 2: "DEF", 3: "MED", 4: "DEL", 5: "ENT"}


class Datos:
    def __init__(self, silver: dict[str, list[dict]], gold: dict[str, list[dict]]):
        self.silver, self.gold = silver, gold
        self.hoy = max(r["fecha"] for r in silver["mi_saldo"])
        self.jugadores = {r["jugador_id"]: r for r in silver["dim_jugador"]}
        self.equipos = {r["equipo_id"]: r["equipo"] for r in silver["dim_jugador"]}

        def de_hoy(filas, campo="fecha"):
            return [r for r in filas if r[campo] == self.hoy]

        self.saldo = de_hoy(silver["mi_saldo"])[0]
        self.plantilla = {r["jugador_id"]: r for r in de_hoy(silver["mi_plantilla"])}
        self.mis_ventas = {r["jugador_id"]: r for r in de_hoy(silver["mis_ventas"])}
        self.mercado = {r["jugador_id"]: r for r in de_hoy(silver["fact_mercado_dia"])}
        self.ofertas = {r["oferta_id"]: r for r in de_hoy(silver["fact_ofertas"])}
        self.reval = {r["jugador_id"]: r for r in de_hoy(gold["score_revalorizacion"])}
        self.puntos = {r["jugador_id"]: r for r in de_hoy(gold["score_puntos_esperados"], "fecha_calculo")}
        self.features = {r["jugador_id"]: r for r in de_hoy(gold["features_jugador"])}
        self.calendario = {r["partido_id"]: r for r in silver["dim_calendario"]}

        self.valor_hist: dict[int, list[tuple[str, int]]] = defaultdict(list)
        for r in silver["fact_valor_diario"]:
            self.valor_hist[r["jugador_id"]].append((r["fecha"], r["valor"]))
        self.partidos: dict[int, list[dict]] = defaultdict(list)
        for r in silver["fact_puntos_jornada"]:
            self.partidos[r["jugador_id"]].append(r)

    # --- jornada ------------------------------------------------------------

    def proxima_jornada(self, ahora: datetime | None = None) -> dict | None:
        """La siguiente jornada con partidos sin jugar: id, nombre e inicio (UTC)."""
        ahora = ahora or datetime.now(timezone.utc)
        pendientes = [
            p for p in self.calendario.values()
            if p["estado"] not in ("finished", "postponed") and p["inicio_utc"]
        ]
        if not pendientes:
            return None
        jornada_id = min(pendientes, key=lambda p: p["inicio_utc"])["jornada_id"]
        partidos = [p for p in pendientes if p["jornada_id"] == jornada_id]
        inicio = min(p["inicio_utc"] for p in partidos)
        return {
            "jornada_id": jornada_id,
            "jornada": partidos[0]["jornada"],
            "inicio_utc": inicio,
            "empezada": datetime.fromisoformat(inicio.replace("Z", "+00:00")) <= ahora,
        }

    # --- fichas -------------------------------------------------------------

    def ficha(self, jid: int) -> dict:
        """Lo esencial de un jugador para decidir: valor, tendencia, puntos esperados y estado."""
        j = self.jugadores.get(jid, {})
        r, p, f = self.reval.get(jid, {}), self.puntos.get(jid, {}), self.features.get(jid, {})
        rival = None
        if p.get("rival_id") is not None:
            rival = {
                "equipo": self.equipos.get(p["rival_id"]),
                "en_casa": p.get("local"),
                "dificultad": p.get("dificultad"),
                "jornada": p.get("jornada"),
                "inicio_utc": (self.calendario.get(p["partido_id"]) or {}).get("inicio_utc"),
            }
        return {
            "jugador_id": jid,
            "nombre": j.get("nombre"),
            "posicion": POSICIONES.get(j.get("posicion")),
            "equipo": j.get("equipo"),
            "estado": j.get("estado"),
            "estado_info": j.get("estado_info"),
            "valor": f.get("valor"),
            "var_hoy_pct": f.get("var_1d_pct"),
            "var_30d_pct": f.get("var_30d_pct"),
            "subida_esperada_1d_pct": r.get("subida_1d_pct"),
            "subida_esperada_3d_pct": r.get("subida_3d_pct"),
            "subida_esperada_3d_eur": r.get("subida_3d_eur"),
            "puntos_esperados": p.get("puntos_esperados"),
            "en_once_probable": p.get("en_once_probable"),
            "p_juega": p.get("p_juega"),
            "media_puntos_temp": f.get("media_puntos_temp"),
            "forma5": f.get("forma5"),
            "minutos_ult3": f.get("minutos_ult3"),
            "siguiente_partido": rival,
        }
