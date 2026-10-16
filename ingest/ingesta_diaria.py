"""Ingesta diaria a bronze (Fase 1).

Públicos, siempre: foto de la competición (precios y estado de los ~550
jugadores), jornada actual y, si hay una jornada en 'preview', sus onces
probables. Privados, solo si hay BIWENGER_TOKEN: cuenta, plantilla, mercado y liga.

Uso:
    python -m ingest.ingesta_diaria             # todo lo disponible
    python -m ingest.ingesta_diaria --solo-publicos

Sale con código 1 si algún endpoint falla o cambia de esquema, y manda el
resumen de los fallos por Telegram (si están TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID).
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from ingest import avisos, bronze
from ingest.biwenger_api import BiwengerAPI, BiwengerError


def _paso(
    api: BiwengerAPI, endpoint: str, llamada, errores: list[str], clave: str | None = None
) -> dict | None:
    try:
        cuerpo = llamada()
    except BiwengerError as e:
        errores.append(f"[ERROR] {endpoint}: {e}")
        print(errores[-1])
        return None
    try:
        ruta = bronze.guardar(endpoint, cuerpo, api.ultima_url, api.ultimos_params, clave=clave)
    except bronze.EsquemaCambiado as e:
        errores.append(f"[ESQUEMA] {e} (crudo guardado igualmente)")
        print(errores[-1])
        return None
    print(f"[ok] {endpoint} -> {ruta}")
    return cuerpo


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--solo-publicos", action="store_true")
    args = p.parse_args(argv)

    errores: list[str] = []
    codigo = _ingestar(BiwengerAPI(), args.solo_publicos, errores)
    if errores:
        avisos.enviar("⚠️ Ingesta de Biwenger con fallos:\n" + "\n".join(errores))
    return codigo


def _ingestar(api: BiwengerAPI, solo_publicos: bool, errores: list[str]) -> int:
    fallos = 0

    comp = _paso(api, "competicion", api.competicion, errores)
    fallos += comp is None
    fallos += _paso(api, "jornadas", api.jornadas, errores) is None

    # Jornada en preview: Biwenger publica ahí los onces probables, que son la
    # mejor señal pública de titularidad antes de alinear.
    if comp:
        for ev in comp["data"].get("activeEvents", []):
            if ev.get("type") == "round":
                r = _paso(api, "jornada", lambda: api.jornada(ev["id"]), errores, clave=str(ev["id"]))
                fallos += r is None

    if solo_publicos or not api.tiene_token:
        if not solo_publicos:
            print("[aviso] Sin BIWENGER_TOKEN: se omiten cuenta, plantilla, mercado y liga")
        return 1 if fallos else 0

    fallos += _paso(api, "cuenta", api.cuenta, errores) is None
    if not (api.league_id and api.user_id):
        errores.append("[aviso] Faltan BIWENGER_LEAGUE_ID / BIWENGER_USER_ID: mira raw_cuenta y rellénalos")
        print(errores[-1])
        return 1
    for endpoint, llamada in (
        ("plantilla", api.plantilla),
        ("mercado", api.mercado),
        ("liga", api.liga),
    ):
        fallos += _paso(api, endpoint, llamada, errores) is None
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
