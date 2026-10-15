"""Backfill del detalle de cada jugador a bronze (raw_jugador).

El detalle público trae ~1 año de precios diarios y los puntos de cada partido
en todas las puntuaciones. Con esto el histórico de valor existe desde el
primer día y el modelo de revalorización no tiene que esperar semanas.

Límite real de Biwenger (14/10/2026): tras ~200 llamadas seguidas responde 429
y pide esperar "unas horas". Por eso el backfill va por tandas:
- se salta los jugadores que ya están en bronze (es reanudable);
- hace como mucho --max jugadores por ejecución, con 3 s entre llamadas;
- se para en el primer 429 en vez de seguir insistiendo;
- empieza por mi plantilla y el mercado, que son los que se necesitan antes.
Con los valores por defecto, 550 jugadores se completan en 4 tandas.

Uso:
    python -m ingest.backfill_jugadores [--max 150] [--pausa 3] [--todos]
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from ingest import bronze
from ingest.biwenger_api import BiwengerAPI, BiwengerError, LimiteSuperado


def ids_en_bronze() -> set[str]:
    """Ids de jugador con al menos un detalle guardado (clave del fichero)."""
    carpeta = bronze.ruta_base() / "raw_jugador"
    return {f.stem.split("_", 1)[1].split("-")[0] for f in carpeta.glob("dt=*/*_*.json")}


def ids_prioritarios() -> set[str]:
    """Mi plantilla y el mercado de la última foto: sus históricos se necesitan antes."""
    ids: set[str] = set()
    for endpoint, extraer in (
        ("plantilla", lambda d: [p["id"] for p in d.get("players", [])]),
        ("mercado", lambda d: [s["player"]["id"] for s in d.get("sales", [])]),
    ):
        ficheros = sorted((bronze.ruta_base() / f"raw_{endpoint}").glob("dt=*/*.json"))
        if ficheros:
            data = json.loads(ficheros[-1].read_text(encoding="utf-8"))["payload"]["data"]
            ids.update(str(i) for i in extraer(data))
    return ids


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--max", type=int, default=150, help="jugadores por ejecución")
    p.add_argument("--pausa", type=float, default=3.0, help="segundos entre llamadas")
    p.add_argument("--todos", action="store_true", help="refrescar también los ya guardados")
    args = p.parse_args(argv)

    api = BiwengerAPI(pausa_s=args.pausa)
    jugadores = list(api.competicion()["data"]["players"].values())
    hechos = set() if args.todos else ids_en_bronze()
    pendientes = [j for j in jugadores if str(j["id"]) not in hechos]
    prioritarios = ids_prioritarios()
    pendientes.sort(key=lambda j: str(j["id"]) not in prioritarios)  # estable: primero los míos
    tanda = pendientes[: args.max]
    print(f"{len(jugadores)} jugadores · {len(hechos)} ya en bronze · esta tanda: {len(tanda)}")

    ok = fallos = 0
    for j in tanda:
        try:
            cuerpo = api.jugador(j["slug"])
            bronze.guardar("jugador", cuerpo, api.ultima_url, api.ultimos_params, clave=str(j["id"]))
            ok += 1
        except LimiteSuperado as e:
            print(f"[PARADA] {e}. Vuelve a lanzarlo en unas horas: retoma donde lo dejó.")
            fallos += 1
            break
        except (BiwengerError, bronze.EsquemaCambiado) as e:
            fallos += 1
            print(f"[ERROR] {j['slug']}: {e}")
    quedan = len(pendientes) - ok
    print(f"Guardados: {ok} · fallos: {fallos} · quedan: {quedan}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
