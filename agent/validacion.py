"""Validación de un paquete propuesto, con las reglas de docs/diseno-agente-biwenger.md.

Devuelve la lista de errores (vacía si el paquete es válido) y el saldo con
el que se llegaría a la jornada. Los errores vuelven a Claude para que corrija.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from agent.datos import FORMACIONES_GRATIS, FORMACIONES_PAGO, Datos

# La oferta automática de Biwenger es el valor de mercado ±5 %: se cuenta lo peor.
MARGEN_VENTA = 0.95
# Biwenger resuelve el mercado y hace sus ofertas cada mañana a las 7:00 de Madrid.
# 7:00 de Madrid son las 5:00 UTC en verano y las 6:00 en invierno; la hora de
# diferencia no importa porque ninguna jornada empieza a esas horas.
HORA_MERCADO_UTC = 5
NO_ALINEABLES = {"injured", "sanctioned"}


def proximo_cambio_de_mercado(ahora: datetime) -> datetime:
    cambio = ahora.replace(hour=HORA_MERCADO_UTC, minute=0, second=0, microsecond=0)
    return cambio if cambio > ahora else cambio + timedelta(days=1)


def validar(d: Datos, paquete: dict, ahora: datetime | None = None) -> tuple[list[str], dict]:
    ahora = ahora or datetime.now(timezone.utc)
    errores: list[str] = []
    nombre = lambda jid: d.jugadores.get(jid, {}).get("nombre", jid)  # noqa: E731

    compras, ventas = paquete.get("compras", []), paquete.get("ventas", [])
    aceptar, alineacion = paquete.get("aceptar_ofertas", []), paquete.get("alineacion")

    # --- compras ------------------------------------------------------------
    total_pujas = 0
    for c in compras:
        m = d.mercado.get(c["jugador_id"])
        if m is None:
            errores.append(f"Compra de {nombre(c['jugador_id'])}: no está en el mercado de hoy.")
            continue
        if c["jugador_id"] in d.plantilla:
            errores.append(f"Compra de {nombre(c['jugador_id'])}: ya es mío.")
        if c["puja"] < m["precio"]:
            errores.append(f"Compra de {nombre(c['jugador_id'])}: la puja ({c['puja']}) es menor que el precio ({m['precio']}).")
        if d.saldo["puja_maxima"] is not None and c["puja"] > d.saldo["puja_maxima"]:
            errores.append(f"Compra de {nombre(c['jugador_id'])}: la puja supera la puja máxima ({d.saldo['puja_maxima']}).")
        total_pujas += c["puja"]
    if len({c["jugador_id"] for c in compras}) != len(compras):
        errores.append("Hay jugadores repetidos en las compras.")

    # --- ventas y ofertas ---------------------------------------------------
    vendidos: set[int] = set()
    ingreso_ventas = 0
    for v in ventas:
        jid = v["jugador_id"]
        if jid not in d.plantilla:
            errores.append(f"Venta de {nombre(jid)}: no es de mi plantilla.")
            continue
        if jid in d.mis_ventas:
            errores.append(f"Venta de {nombre(jid)}: ya está a la venta.")
        vendidos.add(jid)
        ingreso_ventas += round((d.features.get(jid) or {}).get("valor", 0) * MARGEN_VENTA)

    ingreso_ofertas = 0
    for a in aceptar:
        o = d.ofertas.get(a["oferta_id"])
        if o is None or o["estado"] != "waiting":
            errores.append(f"Oferta {a['oferta_id']}: no existe o ya no está abierta.")
            continue
        if o["jugador_id"] in vendidos:
            errores.append(f"Oferta por {nombre(o['jugador_id'])}: se acepta y además se pone a la venta.")
        vendidos.add(o["jugador_id"])
        ingreso_ofertas += o["importe"]

    # --- saldo al empezar la jornada (regla dura: >= 0) ---------------------
    jornada = d.proxima_jornada(ahora)
    ventas_a_tiempo = True
    if jornada and not jornada["empezada"]:
        inicio = datetime.fromisoformat(jornada["inicio_utc"].replace("Z", "+00:00"))
        # Las ventas nuevas cobran con la oferta de Biwenger del siguiente cambio de mercado.
        ventas_a_tiempo = proximo_cambio_de_mercado(ahora) < inicio
    saldo_final = (d.saldo["saldo"] + ingreso_ofertas - total_pujas
                   + (ingreso_ventas if ventas_a_tiempo else 0))
    if saldo_final < 0:
        detalle = "" if ventas_a_tiempo else " (las ventas nuevas no cobran antes de que empiece la jornada)"
        errores.append(
            f"El saldo quedaría en {saldo_final} € al empezar la jornada{detalle}. Tiene que ser >= 0: "
            "añade ventas u ofertas, o quita compras. Las ventas cuentan al 95 % de su valor."
        )

    # --- alineación ---------------------------------------------------------
    if alineacion:
        errores += _validar_alineacion(d, alineacion, vendidos, nombre)

    return errores, {
        "saldo_actual": d.saldo["saldo"],
        "saldo_al_empezar_la_jornada": saldo_final,
        "ventas_cobran_antes_de_la_jornada": ventas_a_tiempo,
        "formacion_de_pago": bool(alineacion) and alineacion["formacion"] in FORMACIONES_PAGO,
    }


def _validar_alineacion(d: Datos, a: dict, vendidos: set[int], nombre) -> list[str]:
    errores = []
    if a["formacion"] not in FORMACIONES_GRATIS + FORMACIONES_PAGO:
        errores.append(f"Formación {a['formacion']} no permitida. Gratis: {FORMACIONES_GRATIS}; "
                       f"de pago (1 crédito): {FORMACIONES_PAGO}.")
        return errores
    ids = a["jugadores"]
    if len(ids) != 11 or len(set(ids)) != 11:
        errores.append(f"La alineación tiene que tener 11 jugadores distintos (tiene {len(set(ids))}).")
    ajenos = [nombre(j) for j in ids if j not in d.plantilla]
    if ajenos:
        errores.append(f"Alineados que no son de mi plantilla: {ajenos}.")
    vendiendo = [nombre(j) for j in ids if j in vendidos]
    if vendiendo:
        errores.append(f"Alineados que se venden en este paquete: {vendiendo}. Mandan los puntos: "
                       "véndelos después de que jueguen.")
    no_disponibles = [nombre(j) for j in ids if d.jugadores.get(j, {}).get("estado") in NO_ALINEABLES]
    if no_disponibles:
        errores.append(f"Alineados lesionados o sancionados: {no_disponibles}.")
    por_pos = Counter(d.jugadores.get(j, {}).get("posicion") for j in ids if j in d.plantilla)
    de, me, dl = (int(x) for x in a["formacion"].split("-"))
    esperado = {1: 1, 2: de, 3: me, 4: dl}
    real = {p: por_pos.get(p, 0) for p in (1, 2, 3, 4)}
    if real != esperado and not ajenos:
        errores.append(f"Las posiciones no cuadran con {a['formacion']}: hay {real[1]} POR, {real[2]} DEF, "
                       f"{real[3]} MED y {real[4]} DEL.")
    if a["ariete_id"] not in ids:
        errores.append("El ariete tiene que estar en la alineación.")
    return errores
