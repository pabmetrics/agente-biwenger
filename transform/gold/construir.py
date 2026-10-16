"""Construye las tablas gold desde silver (Fase 3).

Recibe las filas de silver ya construidas (las de transform.silver.construir),
así que en local y en Databricks se calcula todo en memoria de una pasada:
bronze -> silver -> gold. log_acciones no se construye aquí: es un registro
que solo crece, y lo escriben las Fases 4 y 5.

Uso:
    python -m transform.gold.construir      # reconstruye silver y gold en data/
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from transform.gold import tablas


def construir(silver: dict[str, list[dict]]) -> dict[str, list[dict]]:
    features = tablas.features_jugador(silver["fact_valor_diario"], silver["fact_puntos_jornada"])
    return {
        "features_jugador": features,
        "score_revalorizacion": tablas.score_revalorizacion(features),
        "score_puntos_esperados": tablas.score_puntos_esperados(
            features, silver["dim_calendario"], silver["fact_once_probable"], silver["dim_jugador"]
        ),
    }


def main() -> int:
    from transform.silver import construir as silver_construir

    load_dotenv()
    silver = silver_construir.construir()
    silver_construir.escribir_csv(silver, Path(os.getenv("SILVER_PATH", "data/silver")))
    gold = construir(silver)
    destino = Path(os.getenv("GOLD_PATH", "data/gold"))
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, filas in gold.items():
        with open(destino / f"{nombre}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=tablas.ESQUEMAS[nombre])
            w.writeheader()
            w.writerows(filas)
        print(f"{nombre:<24} {len(filas):>7} filas")
    print(f"-> {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
