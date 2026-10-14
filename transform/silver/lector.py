"""Lectura de bronze para construir silver.

Cada fichero de bronze es una llamada. Silver se reconstruye entero desde
bronze en cada ejecución (bronze es pequeño), así que no hay estado intermedio:
si cambia una regla, basta con volver a ejecutar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ingest import bronze


@dataclass(frozen=True)
class Registro:
    fecha: str  # partición dt=AAAA-MM-DD (UTC de la ingesta)
    ingest_ts: str  # ISO, UTC
    clave: str | None  # id de jugador o de jornada en los endpoints con clave
    data: dict  # payload["data"]


def leer(endpoint: str, base: Path | None = None) -> list[Registro]:
    """Todas las llamadas guardadas de un endpoint, de la más antigua a la más reciente."""
    carpeta = (base or bronze.ruta_base()) / f"raw_{endpoint}"
    registros = []
    for f in carpeta.glob("dt=*/*.json"):
        contenido = json.loads(f.read_text(encoding="utf-8"))
        meta, data = contenido["_meta"], contenido["payload"].get("data")
        if not isinstance(data, dict):
            continue
        nombre = f.stem.split("-")[0]  # HHMMSS[_clave], sin el sufijo de duplicado
        clave = nombre.split("_", 1)[1] if "_" in nombre else None
        registros.append(Registro(f.parent.name[3:], meta["ingest_ts"], clave, data))
    return sorted(registros, key=lambda r: r.ingest_ts)


def ultimo_por_dia(registros: list[Registro]) -> list[Registro]:
    """La última llamada de cada día: es la foto que vale para ese día."""
    por_dia = {r.fecha: r for r in registros}  # vienen ordenados: gana la última
    return [por_dia[f] for f in sorted(por_dia)]


def ultimo_por_clave(registros: list[Registro]) -> list[Registro]:
    """La última llamada de cada clave (p. ej., el detalle más reciente de cada jugador)."""
    por_clave = {r.clave: r for r in registros}
    return list(por_clave.values())
