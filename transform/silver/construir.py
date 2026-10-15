"""Construye todas las tablas silver desde bronze (Fase 2).

En local escribe un CSV por tabla en SILVER_PATH (por defecto data/silver),
sobrescribiéndolos: silver se recalcula entero desde bronze en cada ejecución.
En Databricks se usa construir() y cada lista de filas se escribe en Delta.

Uso:
    python -m transform.silver.construir
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from transform.silver import tablas
from transform.silver.lector import leer


def construir(base: Path | None = None) -> dict[str, list[dict]]:
    comp = leer("competicion", base)
    jug = leer("jugador", base)
    # /rounds/la-liga (última jornada) y /rounds/la-liga/{id} tienen la misma forma.
    jornadas = sorted(leer("jornadas", base) + leer("jornada", base), key=lambda r: r.ingest_ts)
    plantilla, mercado, liga = leer("plantilla", base), leer("mercado", base), leer("liga", base)

    return {
        "dim_jugador": tablas.dim_jugador(comp),
        "fact_valor_diario": tablas.fact_valor_diario(comp, jug),
        "fact_puntos_jornada": tablas.fact_puntos_jornada(jug, jornadas),
        "dim_calendario": tablas.dim_calendario(comp, jornadas, jug),
        "fact_once_probable": tablas.fact_once_probable(jornadas),
        "fact_mercado_dia": tablas.fact_mercado_dia(mercado),
        "mi_plantilla": tablas.mi_plantilla(plantilla),
        "mis_ventas": tablas.mis_ventas(plantilla),
        "mi_saldo": tablas.mi_saldo(plantilla, mercado, liga),
    }


def escribir_csv(resultado: dict[str, list[dict]], destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, filas in resultado.items():
        with open(destino / f"{nombre}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=tablas.ESQUEMAS[nombre])
            w.writeheader()
            w.writerows(filas)


def main() -> int:
    load_dotenv()
    resultado = construir()
    destino = Path(os.getenv("SILVER_PATH", "data/silver"))
    escribir_csv(resultado, destino)
    for nombre, filas in resultado.items():
        print(f"{nombre:<22} {len(filas):>7} filas")
    pendientes = tablas.ofertas_sin_mapear(leer("mercado"))
    if pendientes:
        print(f"[aviso] {pendientes} ofertas en bronze sin tabla: toca definir fact_ofertas")
    print(f"-> {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
