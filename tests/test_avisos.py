import json

import httpx

from ingest import avisos, ingesta_diaria
from ingest.biwenger_api import BiwengerAPI


def test_sin_bot_configurado_no_envia(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def no_llamar(request):
        raise AssertionError("no debería llamar a Telegram")

    assert avisos.enviar("hola", httpx.Client(transport=httpx.MockTransport(no_llamar))) is False


def test_envia_al_chat_configurado(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    enviados = []

    def responder(request):
        enviados.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    assert avisos.enviar("hola", httpx.Client(transport=httpx.MockTransport(responder)))
    assert enviados == [("https://api.telegram.org/bot123:abc/sendMessage", {"chat_id": "42", "text": "hola"})]


def test_un_fallo_de_red_al_avisar_no_rompe_nada(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    def caer(request):
        raise httpx.ConnectError("sin red")

    assert avisos.enviar("hola", httpx.Client(transport=httpx.MockTransport(caer))) is False


def test_la_ingesta_avisa_de_los_fallos(monkeypatch, tmp_path):
    monkeypatch.setenv("BRONZE_PATH", str(tmp_path))
    monkeypatch.setattr(ingesta_diaria, "load_dotenv", lambda: None)

    def api_bloqueada():
        api = BiwengerAPI(token=None, pausa_s=0)
        api._http = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, json={"status": 429})))
        return api

    mensajes = []
    monkeypatch.setattr(ingesta_diaria, "BiwengerAPI", api_bloqueada)
    monkeypatch.setattr(ingesta_diaria.avisos, "enviar", mensajes.append)

    assert ingesta_diaria.main(["--solo-publicos"]) == 1
    [mensaje] = mensajes
    assert "competicion: 429" in mensaje and "jornadas: 429" in mensaje
