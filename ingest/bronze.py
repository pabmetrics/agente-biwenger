"""Escritura de bronze: JSON crudo + metadatos, append-only.

Ruta: <BRONZE_PATH>/raw_<endpoint>/dt=<AAAA-MM-DD>/<HHMMSS>[_<clave>].json

BRONZE_PATH es una carpeta local (por defecto data/bronze) o, en Databricks, un
Volume de Unity Catalog (/Volumes/<catalogo>/bronze/raw), que se escribe como
un sistema de ficheros normal. Así el mismo código corre en los dos sitios.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Claves que tiene que traer cada endpoint. Si faltan, la API ha cambiado:
# se guarda igual (bronze no pierde nada) pero la ingesta falla y avisa.
ESQUEMA_MINIMO: dict[str, set[str]] = {
    "competicion": {"players", "teams", "season", "scoreID"},
    "jornadas": {"id", "status", "games"},
    "jornada": {"id", "status", "games"},
    "jugador": {"id", "slug", "prices", "reports"},
    # Privados: sin esquema hasta verlos con el token (docs/api-biwenger.md).
    "cuenta": set(),
    "plantilla": set(),
    "mercado": set(),
    "liga": set(),
}

CLAVES_JUGADOR = {"id", "name", "teamID", "position", "price", "priceIncrement", "status", "fitness"}


class EsquemaCambiado(ValueError):
    pass


def ruta_base() -> Path:
    return Path(os.getenv("BRONZE_PATH", "data/bronze"))


def validar(endpoint: str, cuerpo: dict) -> None:
    data = cuerpo.get("data")
    if not isinstance(data, dict):
        raise EsquemaCambiado(f"{endpoint}: 'data' no es un objeto")
    faltan = ESQUEMA_MINIMO.get(endpoint, set()) - data.keys()
    if faltan:
        raise EsquemaCambiado(f"{endpoint}: faltan claves {sorted(faltan)}")
    if endpoint == "competicion":
        jugadores = data["players"]
        if not jugadores:
            raise EsquemaCambiado("competicion: lista de jugadores vacía")
        muestra = next(iter(jugadores.values()))
        faltan = CLAVES_JUGADOR - muestra.keys()
        if faltan:
            raise EsquemaCambiado(f"competicion: jugadores sin {sorted(faltan)}")


def _hash(cuerpo: dict) -> str:
    return hashlib.sha256(json.dumps(cuerpo, sort_keys=True).encode()).hexdigest()


def _ultimo_hash(carpeta_endpoint: Path, clave: str | None) -> str | None:
    sufijo = f"_{clave}.json" if clave else ".json"
    ficheros = sorted(
        (f for f in carpeta_endpoint.glob("dt=*/*.json") if f.name.endswith(sufijo)),
        key=lambda f: (f.parent.name, f.name),
    )
    if not ficheros:
        return None
    return json.loads(ficheros[-1].read_text(encoding="utf-8"))["_meta"]["sha256"]


def guardar(
    endpoint: str,
    cuerpo: dict,
    url: str,
    params: dict | None = None,
    clave: str | None = None,
    ahora: datetime | None = None,
    validar_esquema: bool = True,
) -> Path:
    """Guarda una respuesta en bronze y devuelve la ruta. Nunca sobreescribe."""
    ahora = ahora or datetime.now(timezone.utc)
    carpeta_endpoint = ruta_base() / f"raw_{endpoint}"
    sha = _hash(cuerpo)
    anterior = _ultimo_hash(carpeta_endpoint, clave)

    carpeta = carpeta_endpoint / f"dt={ahora:%Y-%m-%d}"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = f"{ahora:%H%M%S}" + (f"_{clave}" if clave else "")
    ruta = carpeta / f"{nombre}.json"
    n = 1
    while ruta.exists():
        ruta = carpeta / f"{nombre}-{n}.json"
        n += 1

    meta = {
        "source": "biwenger",
        "endpoint": endpoint,
        "url": url,
        "params": params or {},
        "ingest_ts": ahora.isoformat(),
        "sha256": sha,
        "sin_cambios": anterior == sha,
    }
    ruta.write_text(
        json.dumps({"_meta": meta, "payload": cuerpo}, ensure_ascii=False), encoding="utf-8"
    )
    # Se valida después de guardar: si la API cambia, el crudo queda para analizarlo.
    if validar_esquema:
        validar(endpoint, cuerpo)
    return ruta
