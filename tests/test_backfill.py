import httpx
import pytest

from ingest import backfill_jornadas, bronze
from ingest.backfill_jugadores import ids_en_bronze, ids_prioritarios
from ingest.biwenger_api import BiwengerAPI, LimiteSuperado


def test_ids_en_bronze_lee_la_clave_del_fichero(tmp_path, monkeypatch):
    monkeypatch.setenv("BRONZE_PATH", str(tmp_path))
    cuerpo = {"status": 200, "data": {"id": 1, "slug": "x", "prices": [], "reports": []}}
    bronze.guardar("jugador", cuerpo, "https://x", clave="11")
    bronze.guardar("jugador", cuerpo, "https://x", clave="11")  # mismo segundo -> sufijo -1
    bronze.guardar("jugador", cuerpo, "https://x", clave="742")
    assert ids_en_bronze() == {"11", "742"}


def test_prioritarios_son_mi_plantilla_y_el_mercado(tmp_path, monkeypatch):
    monkeypatch.setenv("BRONZE_PATH", str(tmp_path))
    assert ids_prioritarios() == set()  # sin bronze privado no hay prioridad
    bronze.guardar("plantilla", {"status": 200, "data": {"players": [{"id": 1}, {"id": 2}]}},
                   "https://x", validar_esquema=False)
    bronze.guardar("mercado", {"status": 200, "data": {"sales": [{"player": {"id": 3}}]}},
                   "https://x", validar_esquema=False)
    assert ids_prioritarios() == {"1", "2", "3"}


def test_jornadas_pendientes_salen_de_la_competicion(tmp_path, monkeypatch):
    monkeypatch.setenv("BRONZE_PATH", str(tmp_path))
    rondas = [{"id": 1, "status": "finished"}, {"id": 2, "status": "finished"},
              {"id": 3, "status": "pending"}]
    bronze.guardar("competicion", {"status": 200, "data": {"season": {"rounds": rondas}}},
                   "https://x", validar_esquema=False)
    # La 1 ya está terminada en bronze; la 2 solo como preview, así que sigue pendiente.
    bronze.guardar("jornadas", {"status": 200, "data": {"id": 1, "status": "finished"}},
                   "https://x", validar_esquema=False)
    bronze.guardar("jornada", {"status": 200, "data": {"id": 2, "status": "pending"}},
                   "https://x", clave="2", validar_esquema=False)
    assert backfill_jornadas.jornadas_terminadas() == [1, 2]
    assert backfill_jornadas.jornadas_en_bronze() == {1}


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
