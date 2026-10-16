"""Job diario en Databricks: ingesta a bronze y reconstrucción de silver en Delta.

Corre como tarea Python serverless desde el Git folder del repo. Los secretos
salen del scope 'biwenger' y bronze vive en el Volume biwenger.bronze.raw, así
que el código de ingest/ y transform/ es el mismo que en local.

Si algo falla, avisa por Telegram y termina con error para que el job quede en
rojo. Silver se reconstruye igualmente con lo que haya en bronze: un endpoint
caído no debe dejar sin actualizar el resto.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

CATALOGO = os.getenv("BIWENGER_CATALOGO", "biwenger")
SECRETOS = {
    "BIWENGER_TOKEN": "biwenger-token",
    "BIWENGER_LEAGUE_ID": "biwenger-league-id",
    "BIWENGER_USER_ID": "biwenger-user-id",
    "TELEGRAM_BOT_TOKEN": "telegram-bot-token",
    "TELEGRAM_CHAT_ID": "telegram-chat-id",
}


def _preparar_entorno() -> None:
    from databricks.sdk.runtime import dbutils

    for var, clave in SECRETOS.items():
        os.environ[var] = dbutils.secrets.get("biwenger", clave)
    os.environ["BRONZE_PATH"] = f"/Volumes/{CATALOGO}/bronze/raw"


def _escribir_silver() -> dict[str, int]:
    from databricks.sdk.runtime import spark

    from transform.silver import delta
    from transform.silver.construir import construir

    filas_por_tabla = {}
    for tabla, filas in construir(Path(os.environ["BRONZE_PATH"])).items():
        df = spark.createDataFrame(delta.filas_tipadas(tabla, filas), delta.esquema_ddl(tabla))
        (df.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
           .saveAsTable(f"{CATALOGO}.silver.{tabla}"))
        filas_por_tabla[tabla] = len(filas)
        print(f"{CATALOGO}.silver.{tabla}: {len(filas)} filas")
    return filas_por_tabla


def main() -> int:
    _preparar_entorno()
    from ingest import avisos, ingesta_diaria

    codigo = 0
    try:
        codigo = ingesta_diaria.main([])  # ya avisa por Telegram de sus propios fallos
    except Exception:
        avisos.enviar("❌ La ingesta de Biwenger ha fallado en Databricks:\n" + traceback.format_exc()[-1500:])
        codigo = 1
    try:
        _escribir_silver()
    except Exception:
        avisos.enviar("❌ La reconstrucción de silver ha fallado en Databricks:\n" + traceback.format_exc()[-1500:])
        raise
    return codigo


if __name__ == "__main__":
    if main():
        raise SystemExit("La ingesta terminó con fallos (detalle en el log y en Telegram)")
