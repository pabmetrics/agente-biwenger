"""Ingesta diaria a bronze (Fase 1).

Públicos, siempre: foto de la competición (precios y estado de los ~550
jugadores), jornada actual y, si hay una jornada en 'preview', sus onces
probables. Privados, solo si hay BIWENGER_TOKEN: cuenta, plantilla, mercado y liga.

Uso:
    python -m ingest.ingesta_diaria             # todo lo disponible
    python -m ingest.ingesta_diaria --solo-publicos

Sale con código 1 si algún endpoint falla o cambia de esquema (el job avisa).
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from ingest import bronze
from ingest.biwenger_api import BiwengerAPI, BiwengerError


def _paso(api: BiwengerAPI, endpoint: str, llamada, clave: str | None = None) -> dict | None:
    try:
        cuerpo = llamada()
    except BiwengerError as e:
        print(f"[ERROR] {endpoint}: {e}")
        return None
    try:
        ruta = bronze.guardar(endpoint, cuerpo, api.ultima_url, api.ultimos_params, clave=clave)
    except bronze.EsquemaCambiado as e:
        print(f"[ESQUEMA] {e} (crudo guardado igualmente)")
        return None
    print(f"[ok] {endpoint} -> {ruta}")
    return cuerpo


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--solo-publicos", action="store_true")
    args = p.parse_args(argv)

    api = BiwengerAPI()
    fallos = 0

    comp = _paso(api, "competicion", api.competicion)
    fallos += comp is None
    fallos += _paso(api, "jornadas", api.jornadas) is None

    # Jornada en preview: Biwenger publica ahí los onces probables, que son la
    # mejor señal pública de titularidad antes de alinear.
    if comp:
        for ev in comp["data"].get("activeEvents", []):
            if ev.get("type") == "round":
                r = _paso(api, "jornada", lambda: api.jornada(ev["id"]), clave=str(ev["id"]))
                fallos += r is None

    if args.solo_publicos or not api.tiene_token:
        if not args.solo_publicos:
            print("[aviso] Sin BIWENGER_TOKEN: se omiten cuenta, plantilla, mercado y liga")
        return 1 if fallos else 0

    fallos += _paso(api, "cuenta", api.cuenta) is None
    if not (api.league_id and api.user_id):
        print("[aviso] Faltan BIWENGER_LEAGUE_ID / BIWENGER_USER_ID: mira raw_cuenta y rellénalos")
        return 1
    for endpoint, llamada in (
        ("plantilla", api.plantilla),
        ("mercado", api.mercado),
        ("liga", api.liga),
    ):
        fallos += _paso(api, endpoint, llamada) is None
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
