import httpx
import pytest

from ingest import bronze
from ingest.backfill_jugadores import ids_en_bronze
from ingest.biwenger_api import BiwengerAPI, LimiteSuperado


def test_ids_en_bronze_lee_la_clave_del_fichero(tmp_path, monkeypatch):
    monkeypatch.setenv("BRONZE_PATH", str(tmp_path))
    cuerpo = {"status": 200, "data": {"id": 1, "slug": "x", "prices": [], "reports": []}}
    bronze.guardar("jugador", cuerpo, "https://x", clave="11")
    bronze.guardar("jugador", cuerpo, "https://x", clave="11")  # mismo segundo -> sufijo -1
    bronze.guardar("jugador", cuerpo, "https://x", clave="742")
    assert ids_en_bronze() == {"11", "742"}


def test_429_lanza_limite_superado_sin_reintentar():
    llamadas = []

    def responder(request):
        llamadas.append(request.url)
        return httpx.Response(429, json={"status": 429, "message": "Too Many Requests"})

    api = BiwengerAPI(pausa_s=0)
    api._http = httpx.Client(transport=httpx.MockTransport(responder))
    with pytest.raises(LimiteSuperado):
        api.jugador("david-soria")
    assert len(llamadas) == 1
