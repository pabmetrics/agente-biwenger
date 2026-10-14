"""Backfill del detalle de cada jugador a bronze (raw_jugador).

El detalle público trae ~1 año de precios diarios y los puntos de cada partido
en todas las puntuaciones. Con esto el histórico de valor existe desde el
primer día y el modelo de revalorización no tiene que esperar semanas.

Se lanza una vez y después, como mucho, semanalmente: la variación diaria ya
llega en la foto de `competicion`. ~550 llamadas a 1/s, unos 10 minutos.

Uso:
    python -m ingest.backfill_jugadores [--limite N]
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from ingest import bronze
from ingest.biwenger_api import BiwengerAPI, BiwengerError


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--limite", type=int, help="solo los N primeros jugadores (pruebas)")
    args = p.parse_args(argv)

    api = BiwengerAPI()
    jugadores = list(api.competicion()["data"]["players"].values())
    if args.limite:
        jugadores = jugadores[: args.limite]

    fallos = 0
    for i, j in enumerate(jugadores, 1):
        try:
            cuerpo = api.jugador(j["slug"])
            bronze.guardar("jugador", cuerpo, api.ultima_url, api.ultimos_params, clave=str(j["id"]))
        except (BiwengerError, bronze.EsquemaCambiado) as e:
            fallos += 1
            print(f"[ERROR] {j['slug']}: {e}")
        if i % 50 == 0:
            print(f"{i}/{len(jugadores)}")
    print(f"Hecho: {len(jugadores) - fallos}/{len(jugadores)} jugadores")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
