"""Job diario en Databricks: ingesta, silver y gold en Delta, y la propuesta del agente.

Opciones para probar: --sin-ingesta (no llama a Biwenger) y --sin-agente (no
llama a Claude ni manda la propuesta).

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
    "ANTHROPIC_API_KEY": "anthropic-api-key",
}


def _preparar_entorno() -> None:
    from databricks.sdk.runtime import dbutils

    for var, clave in SECRETOS.items():
        os.environ[var] = dbutils.secrets.get("biwenger", clave)
    os.environ["BRONZE_PATH"] = f"/Volumes/{CATALOGO}/bronze/raw"


def _escribir_capas() -> tuple[dict, dict]:
    """Reconstruye silver y gold desde bronze, los reescribe enteros en Delta y los devuelve."""
    from databricks.sdk.runtime import spark

    from transform.gold import construir as construir_gold
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
    gold = construir_gold.construir(silver)
    for tabla, filas in gold.items():
        escribir("gold", tabla, filas)
    # log_acciones solo crece (lo escriben las Fases 4 y 5): nunca se sobrescribe.
    spark.sql(f"CREATE TABLE IF NOT EXISTS {CATALOGO}.gold.log_acciones "
              f"({delta.esquema_ddl('log_acciones')}) USING DELTA")
    return silver, gold


def _registrar_propuesta(fila: dict) -> None:
    """Añade la propuesta a log_acciones (append: el registro nunca se reescribe)."""
    from databricks.sdk.runtime import spark

    from transform.silver import delta

    df = spark.createDataFrame(delta.filas_tipadas("log_acciones", [fila]), delta.esquema_ddl("log_acciones"))
    df.write.format("delta").mode("append").saveAsTable(f"{CATALOGO}.gold.log_acciones")
    print(f"{CATALOGO}.gold.log_acciones: +1 propuesta ({fila['propuesta_id']})")


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
        silver, gold = _escribir_capas()
    except Exception:
        avisos.enviar("❌ La reconstrucción de silver/gold ha fallado en Databricks:\n" + traceback.format_exc()[-1500:])
        raise

    # Fase 4: el agente propone el paquete del día. Solo con datos frescos: si la
    # ingesta ha fallado, propondría sobre la foto de ayer.
    if "--sin-agente" in sys.argv:
        print("[aviso] --sin-agente: no se lanza el agente")
    elif codigo:
        print("[aviso] La ingesta tuvo fallos: no se lanza el agente para no proponer con datos viejos")
    else:
        from agent.agente import ejecutar
        from agent.datos import Datos

        try:
            ejecutar(Datos(silver, gold), _registrar_propuesta, avisos.enviar)
        except Exception:
            avisos.enviar("❌ El agente ha fallado en Databricks:\n" + traceback.format_exc()[-1500:])
            codigo = 1
    return codigo


if __name__ == "__main__":
    if main():
        raise SystemExit("La ingesta terminó con fallos (detalle en el log y en Telegram)")
