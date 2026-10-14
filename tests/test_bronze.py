import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingest import bronze

FIXTURES = Path(__file__).parent / "fixtures"


def _cargar(nombre):
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def bronze_temporal(tmp_path, monkeypatch):
    monkeypatch.setenv("BRONZE_PATH", str(tmp_path))
    return tmp_path


def test_valida_respuestas_reales():
    bronze.validar("competicion", _cargar("competicion.json"))
    bronze.validar("jugador", _cargar("jugador.json"))


def test_detecta_esquema_cambiado():
    cuerpo = _cargar("competicion.json")
    del cuerpo["data"]["players"]
    with pytest.raises(bronze.EsquemaCambiado):
        bronze.validar("competicion", cuerpo)


def test_detecta_jugador_sin_precio():
    cuerpo = _cargar("competicion.json")
    for j in cuerpo["data"]["players"].values():
        del j["price"]
    with pytest.raises(bronze.EsquemaCambiado):
        bronze.validar("competicion", cuerpo)


def test_guarda_con_metadatos_y_no_sobreescribe(bronze_temporal):
    cuerpo = _cargar("competicion.json")
    ahora = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)
    r1 = bronze.guardar("competicion", cuerpo, "https://x", {"score": 5}, ahora=ahora)
    r2 = bronze.guardar("competicion", cuerpo, "https://x", {"score": 5}, ahora=ahora)

    assert r1 != r2 and r1.exists() and r2.exists()
    assert r1.parent == bronze_temporal / "raw_competicion" / "dt=2026-10-14"
    m1 = json.loads(r1.read_text(encoding="utf-8"))["_meta"]
    m2 = json.loads(r2.read_text(encoding="utf-8"))["_meta"]
    assert m1["sin_cambios"] is False
    assert m2["sin_cambios"] is True
    assert m1["params"] == {"score": 5} and len(m1["sha256"]) == 64


def test_esquema_cambiado_guarda_el_crudo_igualmente(bronze_temporal):
    with pytest.raises(bronze.EsquemaCambiado):
        bronze.guardar("competicion", {"status": 200, "data": {}}, "https://x")
    assert list((bronze_temporal / "raw_competicion").glob("dt=*/*.json"))


def test_sin_cambios_se_compara_por_clave(bronze_temporal):
    a, b = _cargar("jugador.json"), _cargar("jugador.json")
    b["data"]["price"] += 1
    bronze.guardar("jugador", a, "https://x", clave="11")
    r = bronze.guardar("jugador", b, "https://x", clave="22")
    assert json.loads(r.read_text(encoding="utf-8"))["_meta"]["sin_cambios"] is False
