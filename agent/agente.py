"""Agente de solo lectura (Fase 4): propone el paquete del día y lo manda por Telegram.

Lee silver y gold (nunca llama a Biwenger), razona con Claude y termina con una
única llamada a proponer_accion, que valida el paquete, lo guarda en
log_acciones y lo envía por Telegram. En esta fase el mensaje es informativo:
los botones Sí/No y la ejecución llegan en la Fase 5.

Uso local (reconstruye silver/gold desde data/bronze):
    python -m agent.agente               # propone y envía por Telegram
    python -m agent.agente --no-enviar   # propone y lo imprime, sin Telegram
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import anthropic
from dotenv import load_dotenv

from agent import herramientas
from agent.datos import FORMACIONES_GRATIS, FORMACIONES_PAGO, Datos
from agent.validacion import validar
from ingest import avisos

# Configurables para ajustar coste y calidad sin tocar código. Prueba del
# 16/10/2026 con los mismos datos: Opus 5 (high) ~0,39 $ por ejecución y Sonnet 5
# (medium) ~0,18 $, con las mismas decisiones; Opus razonaba algo mejor a varios días.
MODELO = os.getenv("AGENTE_MODELO", "claude-sonnet-5")
ESFUERZO = os.getenv("AGENTE_ESFUERZO", "medium")  # low | medium | high | xhigh | max
MAX_VUELTAS = 20

SISTEMA = f"""Eres el asistente de mi equipo de Biwenger (LaLiga, puntuación "Media AS + SofaScore").
Cada día propones un único paquete: compras, ventas, ofertas a aceptar y, si la jornada está
cerca, la alineación. Yo decido; tú no ejecutas nada en Biwenger.

Objetivos:
- Mercado: ganar valor de equipo (revalorización). Compra lo que más va a subir por euro invertido
  y vende lo que va a bajar, sin dejar la plantilla sin un once válido.
- Alineación: el once con más puntos esperados. Mandan los puntos: si un jugador está para
  venderse pero es de los que más puntos esperan, se alinea y se vende después de que juegue.

Reglas de la liga:
- No hay cláusulas. Biwenger ofrece cada día a las 7:00 (Madrid) el valor de mercado ±5 % por
  cada jugador que tengo a la venta, así que vender está garantizado de un día para otro. Se pone
  a la venta al valor de mercado.
- Lo que vende un mánager se compra al instante pagando su precio; lo que vende Biwenger se
  resuelve en el siguiente cambio de mercado (7:00), con la puja más alta.
- Sin tope de compras al día ni de saldo negativo entre jornadas, pero el saldo tiene que ser
  >= 0 al empezar cada jornada (si no, no puntúo). Cuenta las ventas al 95 % de su valor.
- Formaciones gratis: {", ".join(FORMACIONES_GRATIS)}. De pago, 1 crédito (lo consigo fácil
  viendo un vídeo): {", ".join(FORMACIONES_PAGO)}. Siempre 1 portero; cada jugador solo cuenta en
  su posición. Los suplentes no puntúan. Hay que elegir un ariete entre los alineados.

Cómo leer los scores (reglas con backtest, no un modelo entrenado):
- subida_esperada_*: inercia del valor. Muy fiable: acierta si sube o baja al día siguiente en
  ~96 % de los casos y está bien calibrada incluso en subidas grandes. Los porcentajes altos
  suelen ser jugadores baratos.
- puntos_esperados: (media + forma)/2 × probabilidad de jugar. Ruidoso: el error medio es de
  ~2 puntos por partido. El once probable y la dificultad del rival (0-100, más alto = más
  difícil) aún no están validados: tómalos como orientación.

Cómo trabajar:
- Empieza por leer_plantilla_y_saldo, leer_mercado_con_scores y leer_ofertas_recibidas.
- Usa leer_jugador para mirar en detalle a los candidatos que dudes.
- Una jornada dura varios días: mira siguiente_partido.inicio_utc de cada jugador antes de dar
  por hecho que ya ha jugado o que juega pronto.
- Usa la búsqueda web solo para jugadores dudosos de la alineación (lesión, rotación, no salen
  en el once probable) y solo si cambia la decisión.
- No propongas por proponer: si nada compensa, deja las listas vacías y dilo en el resumen.
- Termina SIEMPRE llamando a proponer_accion una vez. Si devuelve errores, corrígelos y vuelve a
  llamarla. Cada motivo, en una línea y con el dato que lo justifica.
- Escribe en español, directo y sin relleno."""


def _contexto_del_dia(d: Datos, ahora: datetime) -> str:
    jornada = d.proxima_jornada(ahora)
    toca_alinear = False
    if jornada is None:
        linea = "No hay jornadas pendientes en el calendario."
    elif jornada["empezada"]:
        linea = f"La {jornada['jornada']} ya ha empezado: no propongas alineación (alineacion = null)."
    else:
        horas = (datetime.fromisoformat(jornada["inicio_utc"].replace("Z", "+00:00")) - ahora).total_seconds() / 3600
        toca_alinear = horas <= 36
        linea = (f"Próxima jornada: {jornada['jornada']}, empieza {jornada['inicio_utc']} (en {horas:.0f} h). "
                 + ("Propón también la alineación." if toca_alinear else "Aún no toca alineación (alineacion = null)."))
    return (f"Hoy es {d.hoy}; ahora son las {ahora.strftime('%H:%M')} UTC. {linea}\n"
            "Prepara la propuesta del día.")


def formatear(d: Datos, paquete: dict, info: dict) -> str:
    """El mensaje de Telegram: corto, una línea por acción."""
    nombre = lambda jid: d.jugadores.get(jid, {}).get("nombre", str(jid))  # noqa: E731
    m = lambda e: f"{e / 1e6:.2f} M"  # noqa: E731
    lineas = [f"⚽ Propuesta del {d.hoy}", "", paquete["resumen"]]
    if paquete["compras"]:
        lineas += ["", "🟢 Comprar"] + [f"• {nombre(c['jugador_id'])} por {m(c['puja'])}: {c['motivo']}" for c in paquete["compras"]]
    if paquete["ventas"]:
        lineas += ["", "🔴 Poner a la venta"] + [f"• {nombre(v['jugador_id'])}: {v['motivo']}" for v in paquete["ventas"]]
    if paquete["aceptar_ofertas"]:
        lineas += ["", "🤝 Aceptar ofertas"]
        for a in paquete["aceptar_ofertas"]:
            o = d.ofertas[a["oferta_id"]]
            lineas.append(f"• {nombre(o['jugador_id'])} por {m(o['importe'])}: {a['motivo']}")
    if not (paquete["compras"] or paquete["ventas"] or paquete["aceptar_ofertas"]):
        lineas += ["", "Mercado: hoy no propongo movimientos."]
    a = paquete["alineacion"]
    if a:
        pos = {"POR": [], "DEF": [], "MED": [], "DEL": []}
        for jid in a["jugadores"]:
            p = d.ficha(jid)["posicion"]
            pos.setdefault(p, []).append(nombre(jid) + (" (A)" if jid == a["ariete_id"] else ""))
        pago = " · 1 crédito" if info["formacion_de_pago"] else ""
        lineas += ["", f"📋 Alineación {a['formacion']}{pago}"] + [f"{k}: {', '.join(v)}" for k, v in pos.items() if v]
        lineas.append(f"Ariete: {nombre(a['ariete_id'])}")
        if a["dudas"]:
            lineas.append(f"⚠️ Dudas: {a['dudas']}")
    lineas += ["", f"Saldo: {m(info['saldo_actual'])} → {m(info['saldo_al_empezar_la_jornada'])} al empezar la jornada (ventas al 95 %).",
               "Solo informativo: todavía no se ejecuta nada."]
    return "\n".join(lineas)


def ejecutar(
    d: Datos,
    registrar: Callable[[dict], None],
    enviar: Callable[[str], bool],
    cliente: anthropic.Anthropic | None = None,
    ahora: datetime | None = None,
) -> dict | None:
    """Corre el agente hasta que propone un paquete válido. Devuelve la fila de log_acciones."""
    cliente = cliente or anthropic.Anthropic()
    ahora = ahora or datetime.now(timezone.utc)
    mensajes: list = [{"role": "user", "content": _contexto_del_dia(d, ahora)}]
    propuesta = None
    gasto = {"llamadas": 0, "entrada": 0, "cache_leida": 0, "cache_escrita": 0, "salida": 0}

    def informar_gasto() -> None:
        print(f"Modelo {MODELO}, esfuerzo {ESFUERZO}. Tokens: " + ", ".join(f"{k} {v}" for k, v in gasto.items()))

    # La reserva automática ante rechazos es para Opus y Fable; en Sonnet no se pide.
    reserva = (dict(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
               if MODELO.startswith(("claude-opus", "claude-fable")) else {})

    for _ in range(MAX_VUELTAS):
        r = cliente.beta.messages.create(
            model=MODELO,
            max_tokens=16000,
            system=SISTEMA,
            tools=[*herramientas.DEFINICIONES, herramientas.WEB_SEARCH],
            messages=mensajes,
            thinking={"type": "adaptive"},
            output_config={"effort": ESFUERZO},
            cache_control={"type": "ephemeral"},
            **reserva,
        )
        u = getattr(r, "usage", None)
        if u is not None:
            gasto["llamadas"] += 1
            gasto["entrada"] += u.input_tokens or 0
            gasto["cache_leida"] += u.cache_read_input_tokens or 0
            gasto["cache_escrita"] += u.cache_creation_input_tokens or 0
            gasto["salida"] += u.output_tokens or 0
        if r.stop_reason == "refusal":
            raise RuntimeError(f"Claude rechazó la petición: {r.stop_details}")
        mensajes.append({"role": "assistant", "content": r.content})
        if r.stop_reason == "pause_turn":  # la búsqueda web pidió más tiempo: se reanuda
            continue
        if r.stop_reason == "max_tokens":
            raise RuntimeError("La respuesta se cortó por max_tokens")
        usos = [b for b in r.content if b.type == "tool_use"]
        if not usos:
            if propuesta:
                informar_gasto()
                return propuesta
            mensajes.append({"role": "user", "content": "Falta la propuesta: termina llamando a proponer_accion."})
            continue

        resultados = []
        for b in usos:
            try:
                if b.name == "proponer_accion":
                    errores, info = validar(d, b.input, ahora)
                    if errores:
                        resultados.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                           "content": "Corrige y vuelve a proponer:\n- " + "\n- ".join(errores)})
                        continue
                    jornada = d.proxima_jornada(ahora)
                    propuesta = {
                        "propuesta_id": str(uuid.uuid4()),
                        "creada_utc": ahora.isoformat().replace("+00:00", "Z"),
                        "tipo": "mercado+alineacion" if b.input["alineacion"] else "mercado",
                        "jornada_id": jornada["jornada_id"] if jornada else None,
                        "paquete": json.dumps(b.input, ensure_ascii=False),
                        "explicacion": b.input["resumen"],
                        "estado": "informativa",  # Fase 4: sin botones ni ejecución
                        "caduca_utc": None,
                        "respondida_utc": None,
                        "ejecutada_utc": None,
                        "resultado": None,
                    }
                    registrar(propuesta)
                    enviado = enviar(formatear(d, b.input, info))
                    resultados.append({"type": "tool_result", "tool_use_id": b.id,
                                       "content": f"Propuesta registrada ({propuesta['propuesta_id']}); "
                                                  f"enviada por Telegram: {enviado}. Ya has terminado."})
                else:
                    datos = herramientas.LECTURA[b.name](d, b.input)
                    resultados.append({"type": "tool_result", "tool_use_id": b.id,
                                       "content": json.dumps(datos, ensure_ascii=False, default=str)})
            except Exception as e:  # el error vuelve a Claude en vez de tumbar el agente
                resultados.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                   "content": f"{type(e).__name__}: {e}"})
        mensajes.append({"role": "user", "content": resultados})
        if propuesta:
            informar_gasto()
            return propuesta
    raise RuntimeError(f"El agente no terminó en {MAX_VUELTAS} vueltas")


def _registrar_local(fila: dict) -> None:
    ruta = Path(os.getenv("GOLD_PATH", "data/gold")) / "log_acciones.jsonl"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a", encoding="utf-8") as f:  # solo se añade: nunca se reescribe
        f.write(json.dumps(fila, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    from transform.gold import construir as gold
    from transform.silver import construir as silver

    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--no-enviar", action="store_true", help="imprime la propuesta en vez de enviarla")
    args = p.parse_args(argv)

    s = silver.construir()
    d = Datos(s, gold.construir(s))

    def imprimir(texto: str) -> bool:
        print(texto)
        return False

    fila = ejecutar(d, _registrar_local, imprimir if args.no_enviar else avisos.enviar)
    print(f"Propuesta {fila['propuesta_id']} registrada en log_acciones.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
