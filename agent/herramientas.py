"""Herramientas del agente: lectura de silver/gold y la única de propuesta.

Ninguna escribe en Biwenger (regla dura del proyecto). proponer_accion solo
valida el paquete, lo guarda en log_acciones y lo manda por Telegram; ejecutar
lo confirmado es cosa de la Azure Function (Fase 5).
"""

from __future__ import annotations

from agent.datos import Datos

_OBJ = {"type": "object", "additionalProperties": False}


def _sin_parametros(nombre: str, descripcion: str) -> dict:
    return {"name": nombre, "description": descripcion, "strict": True,
            "input_schema": {**_OBJ, "properties": {}, "required": []}}


DEFINICIONES = [
    _sin_parametros(
        "leer_plantilla_y_saldo",
        "Mi plantilla de hoy con la ficha de cada jugador (valor, subida esperada, puntos "
        "esperados en su siguiente partido, once probable, rival), si está alineado o a la venta, "
        "y mi saldo, la puja máxima permitida y mi posición en la liga.",
    ),
    _sin_parametros(
        "leer_mercado_con_scores",
        "Jugadores en venta hoy (sin los míos), con su precio, quién los vende (Biwenger o un "
        "mánager), cuándo cierra la venta y su ficha completa con los scores.",
    ),
    _sin_parametros(
        "leer_ofertas_recibidas",
        "Ofertas abiertas por mis jugadores: importe, % sobre el valor de mercado, quién la hace "
        "y cuándo caduca.",
    ),
    {
        "name": "leer_jugador",
        "description": "Detalle de un jugador: ficha, valor de los últimos 30 días y sus últimos "
                       "8 partidos (puntos, titularidad, minutos).",
        "strict": True,
        "input_schema": {**_OBJ, "properties": {"jugador_id": {"type": "integer"}},
                         "required": ["jugador_id"]},
    },
    {
        "name": "proponer_accion",
        "description": (
            "Propone el paquete del día. Llámala UNA vez al final, con todo junto: compras, "
            "ventas, ofertas a aceptar y, si toca, la alineación. Se valida con las reglas de la "
            "liga; si devuelve errores, corrige y vuelve a llamarla. Las listas pueden ir vacías "
            "si no conviene hacer nada."
        ),
        "strict": True,
        "input_schema": {
            **_OBJ,
            "properties": {
                "resumen": {"type": "string", "description": "2-3 frases con la idea del día."},
                "compras": {"type": "array", "items": {
                    **_OBJ, "properties": {
                        "jugador_id": {"type": "integer"},
                        "puja": {"type": "integer", "description": "Euros, como mínimo el precio de venta."},
                        "motivo": {"type": "string", "description": "Una línea."}},
                    "required": ["jugador_id", "puja", "motivo"]}},
                "ventas": {"type": "array", "items": {
                    **_OBJ, "properties": {
                        "jugador_id": {"type": "integer"},
                        "motivo": {"type": "string"}},
                    "required": ["jugador_id", "motivo"]}},
                "aceptar_ofertas": {"type": "array", "items": {
                    **_OBJ, "properties": {
                        "oferta_id": {"type": "integer"},
                        "motivo": {"type": "string"}},
                    "required": ["oferta_id", "motivo"]}},
                "alineacion": {
                    "anyOf": [
                        {"type": "null"},
                        {**_OBJ, "properties": {
                            "formacion": {"type": "string", "description": "p. ej. 4-3-3"},
                            "jugadores": {"type": "array", "items": {"type": "integer"},
                                          "description": "Los 11 jugador_id, portero incluido."},
                            "ariete_id": {"type": "integer"},
                            "dudas": {"type": "string", "description": "Jugadores dudosos y por qué; vacío si no hay."}},
                         "required": ["formacion", "jugadores", "ariete_id", "dudas"]},
                    ],
                },
            },
            "required": ["resumen", "compras", "ventas", "aceptar_ofertas", "alineacion"],
        },
    },
]

# Búsqueda web (herramienta de servidor de Anthropic), solo para jugadores dudosos.
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}


def leer_plantilla_y_saldo(d: Datos) -> dict:
    jugadores = []
    for jid, p in d.plantilla.items():
        venta = d.mis_ventas.get(jid)
        jugadores.append({
            **d.ficha(jid),
            "alineado": p["alineado"],
            "precio_compra": p["precio_compra"],
            "fecha_compra": p["fecha_compra"],
            "a_la_venta_por": venta["precio_pedido"] if venta else None,
        })
    jugadores.sort(key=lambda j: ("POR DEF MED DEL ENT".split().index(j["posicion"] or "ENT"), -(j["valor"] or 0)))
    return {
        "fecha": d.hoy,
        "saldo": d.saldo["saldo"],
        "puja_maxima": d.saldo["puja_maxima"],
        "valor_equipo": d.saldo["valor_equipo"],
        "posicion_liga": d.saldo["posicion_liga"],
        "jugadores": jugadores,
    }


def leer_mercado_con_scores(d: Datos) -> dict:
    en_venta = []
    for jid, m in d.mercado.items():
        if jid in d.plantilla:
            continue
        en_venta.append({
            **d.ficha(jid),
            "precio": m["precio"],
            "vendedor": "Biwenger" if m["vendedor_es_biwenger"] else "mánager",
            "cierre_utc": m["cierre_utc"],
        })
    en_venta.sort(key=lambda j: -(j["subida_esperada_3d_pct"] or -99))
    return {"fecha": d.hoy, "jugadores": en_venta}


def leer_ofertas_recibidas(d: Datos) -> dict:
    ofertas = []
    for o in d.ofertas.values():
        if o["estado"] != "waiting":
            continue
        valor = (d.features.get(o["jugador_id"]) or {}).get("valor")
        ofertas.append({
            "oferta_id": o["oferta_id"],
            "jugador_id": o["jugador_id"],
            "nombre": d.jugadores.get(o["jugador_id"], {}).get("nombre"),
            "importe": o["importe"],
            "pct_sobre_valor": round((o["importe"] - valor) / valor * 100, 2) if valor else None,
            "de": "Biwenger" if o["de_biwenger"] else f"mánager {o['de_id']}",
            "jugadores_en_la_oferta": o["n_jugadores"],
            "caduca_utc": o["caduca_utc"],
        })
    return {"fecha": d.hoy, "ofertas": ofertas}


def leer_jugador(d: Datos, jugador_id: int) -> dict:
    if jugador_id not in d.jugadores:
        raise ValueError(f"No existe el jugador {jugador_id}")
    valores = sorted(d.valor_hist.get(jugador_id, []))[-30:]
    partidos = sorted(d.partidos.get(jugador_id, []), key=lambda p: p["fecha"])[-8:]
    return {
        **d.ficha(jugador_id),
        "valor_ultimos_30_dias": [{"fecha": f, "valor": v} for f, v in valores],
        "ultimos_partidos": [{
            "fecha": p["fecha"], "jornada": p["jornada"],
            "rival": d.equipos.get(p["rival_id"]), "en_casa": p["local"],
            "jugo": p["jugo"], "puntos": p["puntos"], "titular": p["titular"], "minutos": p["minutos"],
        } for p in partidos],
    }


LECTURA = {
    "leer_plantilla_y_saldo": lambda d, _: leer_plantilla_y_saldo(d),
    "leer_mercado_con_scores": lambda d, _: leer_mercado_con_scores(d),
    "leer_ofertas_recibidas": lambda d, _: leer_ofertas_recibidas(d),
    "leer_jugador": lambda d, args: leer_jugador(d, args["jugador_id"]),
}
