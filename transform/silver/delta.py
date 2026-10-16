"""Tipos de las tablas silver para escribirlas en Delta.

Las filas de tablas.py usan tipos de Python simples (fechas como texto ISO)
para que sirvan también en CSV. Aquí se convierten a los tipos de Spark: el
esquema DDL de cada tabla y las filas como tuplas listas para
spark.createDataFrame(filas, esquema). Sin dependencias de Spark, así que se
puede probar en local.
"""

from __future__ import annotations

from datetime import date, datetime

from transform.silver.tablas import ESQUEMAS

BOOLEANOS = {"local", "jugo", "titular", "alineado", "vendedor_es_biwenger", "de_biwenger"}
FECHAS = {"fecha", "estado_desde", "fecha_compra"}
TEXTOS = {
    "nombre", "slug", "equipo", "posicion_nombre", "estado", "estado_info", "jornada", "local",
    "visitante", "origen", "tipo",
}


def tipo(columna: str, tabla: str) -> str:
    if columna in BOOLEANOS and not (tabla == "dim_calendario" and columna == "local"):
        return "BOOLEAN"
    if columna in FECHAS:
        return "DATE"
    if columna.endswith("_utc"):
        return "TIMESTAMP"
    if columna in TEXTOS:
        return "STRING"
    return "BIGINT"  # ids, importes en euros, puntos, minutos, posiciones


def esquema_ddl(tabla: str) -> str:
    return ", ".join(f"{c} {tipo(c, tabla)}" for c in ESQUEMAS[tabla])


def _convertir(valor, t: str):
    if valor is None:
        return None
    if t == "DATE":
        return date.fromisoformat(valor)
    if t == "TIMESTAMP":
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    return valor


def filas_tipadas(tabla: str, filas: list[dict]) -> list[tuple]:
    tipos = [(c, tipo(c, tabla)) for c in ESQUEMAS[tabla]]
    return [tuple(_convertir(f[c], t) for c, t in tipos) for f in filas]
