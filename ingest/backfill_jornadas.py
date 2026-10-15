"""Backfill de las jornadas terminadas a bronze (raw_jornada, clave = id).

Las jornadas terminadas traen, por partido, los jugadores que jugaron con sus
eventos (entra/sale), de donde silver saca titularidad y minutos. La ingesta
diaria solo trae la última jornada; esto rellena las anteriores, incluidas las
aplazadas, que tienen su propio id.

La lista de jornadas sale de la última foto de la competición en bronze, así
que no gasta llamadas en averiguarla. Se salta las jornadas que ya están
guardadas como terminadas y se para en el primer 429.

Uso:
    python -m ingest.backfill_jornadas [--pausa 3]
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from ingest import bronze
from ingest.biwenger_api import BiwengerAPI, BiwengerError, LimiteSuperado


def _payloads(endpoint: str) -> list[dict]:
    carpeta = bronze.ruta_base() / f"raw_{endpoint}"
    return [
        json.loads(f.read_text(encoding="utf-8"))["payload"].get("data") or {}
        for f in sorted(carpeta.glob("dt=*/*.json"))
    ]


def jornadas_terminadas() -> list[int]:
    """Ids de las jornadas terminadas según la última foto de la competición."""
    fotos = _payloads("competicion")
    if not fotos:
        return []
    return [r["id"] for r in fotos[-1].get("season", {}).get("rounds", []) if r.get("status") == "finished"]


def jornadas_en_bronze() -> set[int]:
    """Jornadas ya guardadas en estado terminado (por /rounds o por /rounds/{id})."""
    return {
        d["id"] for d in _payloads("jornada") + _payloads("jornadas")
        if d.get("status") == "finished" and "id" in d
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--pausa", type=float, default=3.0, help="segundos entre llamadas")
    args = p.parse_args(argv)

    terminadas = jornadas_terminadas()
    if not terminadas:
        print("[aviso] No hay foto de la competición en bronze: lanza antes la ingesta diaria")
        return 1
    pendientes = [j for j in terminadas if j not in jornadas_en_bronze()]
    print(f"{len(terminadas)} jornadas terminadas · pendientes: {len(pendientes)}")

    api = BiwengerAPI(pausa_s=args.pausa)
    ok = fallos = 0
    for jid in pendientes:
        try:
            cuerpo = api.jornada(jid)
            bronze.guardar("jornada", cuerpo, api.ultima_url, api.ultimos_params, clave=str(jid))
            ok += 1
        except LimiteSuperado as e:
            print(f"[PARADA] {e}. Vuelve a lanzarlo en unas horas: retoma donde lo dejó.")
            fallos += 1
            break
        except (BiwengerError, bronze.EsquemaCambiado) as e:
            fallos += 1
            print(f"[ERROR] jornada {jid}: {e}")
    print(f"Guardadas: {ok} · fallos: {fallos} · quedan: {len(pendientes) - ok}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
