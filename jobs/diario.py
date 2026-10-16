"""Job diario en Databricks: ingesta a bronze y reconstrucción de silver y gold en Delta.

Corre como tarea Python serverless desde el Git folder del repo. Los secretos
salen del scope 'biwenger' y bronze vive en el Volume biwenger.bronze.raw, así
que el código de ingest/ y transform/ es el mismo que en local.

Si algo falla, avisa por Telegram y termina con error para que el job quede en
rojo. Silver y gold se reconstruyen igualmente con lo que haya en bronze: un
endpoint caído no debe dejar sin actualizar el resto.
"""

from __future__ import annotations

import inspect
import os
import sys
import traceback
from pathlib import Path


def _raiz_del_repo() -> Path:
    # En serverless el script se ejecuta con exec() y sin __file__, pero se
    # compila con su ruta real, que queda en co_filename.
    origen = Path(inspect.currentframe().f_code.co_filename)
    for base in (origen.resolve().parent, Path.cwd()):
        for p in (base, *base.parents):
            if (p / "ingest").is_dir() and (p / "transform").is_dir():
                return p
    raise RuntimeError(f"No encuentro la raíz del repo desde {origen} ni desde {Path.cwd()}")


sys.path.insert(0, str(_raiz_del_repo()))

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


def _escribir_capas() -> None:
    """Reconstruye silver y gold desde bronze y los reescribe enteros en Delta."""
    from databricks.sdk.runtime import spark

    from transform.gold import construir as gold
    from transform.silver import delta
    from transform.silver.construir import construir as construir_silver

    def escribir(esquema: str, tabla: str, filas: list[dict]) -> None:
        df = spark.createDataFrame(delta.filas_tipadas(tabla, filas), delta.esquema_ddl(tabla))
        (df.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
           .saveAsTable(f"{CATALOGO}.{esquema}.{tabla}"))
        print(f"{CATALOGO}.{esquema}.{tabla}: {len(filas)} filas")

    silver = construir_silver(Path(os.environ["BRONZE_PATH"]))
    for tabla, filas in silver.items():
        escribir("silver", tabla, filas)
    for tabla, filas in gold.construir(silver).items():
        escribir("gold", tabla, filas)
    # log_acciones solo crece (lo escriben las Fases 4 y 5): nunca se sobrescribe.
    spark.sql(f"CREATE TABLE IF NOT EXISTS {CATALOGO}.gold.log_acciones "
              f"({delta.esquema_ddl('log_acciones')}) USING DELTA")


def main() -> int:
    _preparar_entorno()
    from ingest import avisos, ingesta_diaria

    codigo = 0
    if "--sin-ingesta" in sys.argv:  # para probar silver/gold sin llamar a Biwenger
        print("[aviso] --sin-ingesta: solo se reconstruyen silver y gold")
    else:
        try:
            codigo = ingesta_diaria.main([])  # ya avisa por Telegram de sus propios fallos
        except Exception:
            avisos.enviar("❌ La ingesta de Biwenger ha fallado en Databricks:\n" + traceback.format_exc()[-1500:])
            codigo = 1
    try:
        _escribir_capas()
    except Exception:
        avisos.enviar("❌ La reconstrucción de silver/gold ha fallado en Databricks:\n" + traceback.format_exc()[-1500:])
        raise
    return codigo


if __name__ == "__main__":
    if main():
        raise SystemExit("La ingesta terminó con fallos (detalle en el log y en Telegram)")
