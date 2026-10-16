"""Avisos por Telegram (solo enviar mensajes; los botones llegan en la Fase 5).

Lee TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID del entorno. Si faltan, no hace nada:
la ingesta funciona igual en local sin bot. Un fallo al avisar nunca debe tumbar
la ingesta, así que los errores de red se tragan y se devuelve False.
"""

from __future__ import annotations

import os

import httpx

URL = "https://api.telegram.org/bot{token}/sendMessage"


def enviar(texto: str, cliente: httpx.Client | None = None) -> bool:
    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return False
    cliente = cliente or httpx.Client(timeout=20)
    try:
        r = cliente.post(URL.format(token=token), json={"chat_id": chat_id, "text": texto[:4000]})
        return r.status_code == 200 and r.json().get("ok", False)
    except httpx.HTTPError:
        return False
