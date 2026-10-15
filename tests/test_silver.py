from datetime import datetime, timezone

import pytest

from ingest import bronze
from transform.silver import tablas
from transform.silver.construir import construir
from transform.silver.lector import leer, ultimo_por_dia

D13 = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)
D14 = datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc)
D14_TARDE = datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def bronze_temporal(tmp_path, monkeypatch):
    monkeypatch.setenv("BRONZE_PATH", str(tmp_path))
    return tmp_path


def _guardar(endpoint, data, ahora, clave=None):
    bronze.guardar(endpoint, {"status": 200, "data": data}, "https://x", ahora=ahora,
                   clave=clave, validar_esquema=False)


def _competicion(precio, incremento, estado="ok"):
    return {
        "players": {"7": {"id": 7, "name": "Pepe", "slug": "pepe", "teamID": 1, "position": 3,
                          "price": precio, "priceIncrement": incremento, "status": estado}},
        "teams": {"1": {"id": 1, "name": "Athletic", "nextGames": []},
                  "2": {"id": 2, "name": "Betis", "nextGames": []}},
        "activeEvents": [],
    }


def _partido(id_, estado, goles=(None, None), reports=((), ())):
    return {"id": id_, "date": 1791500000, "status": estado,
            "home": {"id": 1, "name": "Athletic", "score": goles[0], "reports": list(reports[0])},
            "away": {"id": 2, "name": "Betis", "score": goles[1], "reports": list(reports[1])}}


def _report(jid, puntos, eventos=()):
    return {"player": {"id": jid}, "points": puntos,
            "events": [{"type": t, "metadata": m} for t, m in eventos]}


def test_lector_se_queda_con_la_ultima_foto_del_dia():
    _guardar("competicion", _competicion(100, 0), D14)
    _guardar("competicion", _competicion(120, 20), D14_TARDE)
    _guardar("competicion", _competicion(90, -10), D13)
    fotos = ultimo_por_dia(leer("competicion"))
    assert [(r.fecha, r.data["players"]["7"]["price"]) for r in fotos] == [
        ("2026-10-13", 90), ("2026-10-14", 120)]


def test_lector_lee_la_clave_del_nombre_del_fichero():
    _guardar("jugador", {"id": 7}, D14, clave="7")
    _guardar("jugador", {"id": 7}, D14, clave="7")  # mismo segundo: fichero con sufijo -1
    assert {r.clave for r in leer("jugador")} == {"7"}


def test_valor_diario_une_historico_y_foto():
    _guardar("jugador", {"id": 7, "prices": [[261012, 80], [261013, 90], [261014, 95]]}, D14, "7")
    _guardar("competicion", _competicion(100, 10), D14)
    filas = tablas.fact_valor_diario(leer("competicion"), leer("jugador"))
    assert filas == [
        {"jugador_id": 7, "fecha": "2026-10-12", "valor": 80, "variacion": None, "origen": "historico"},
        {"jugador_id": 7, "fecha": "2026-10-13", "valor": 90, "variacion": 10, "origen": "historico"},
        # La foto manda sobre el histórico y trae la variación oficial.
        {"jugador_id": 7, "fecha": "2026-10-14", "valor": 100, "variacion": 10, "origen": "foto"},
    ]


def test_puntos_con_titularidad_y_minutos_desde_la_jornada():
    jornada = {"id": 8, "name": "Jornada 8", "games": [_partido(
        500, "finished", (1, 0),
        ([_report(7, 6, [(4, 70)]), _report(8, 2, [(5, 60), (6, 66)])], [_report(9, 0)]),
    )]}
    _guardar("jornadas", jornada, D14)
    filas = {f["jugador_id"]: f for f in tablas.fact_puntos_jornada([], leer("jornadas"))}

    assert (filas[7]["titular"], filas[7]["minutos"], filas[7]["puntos"]) == (True, 70, 6)
    assert (filas[8]["titular"], filas[8]["minuto_entrada"], filas[8]["minutos"]) == (False, 60, 30)
    assert (filas[9]["local"], filas[9]["rival_id"], filas[9]["minutos"]) == (False, 1, 90)


def test_puntos_del_detalle_incluyen_partidos_no_jugados():
    match = {"id": 500, "date": 1791500000, "status": "finished", "round": {"id": 8, "name": "J8"},
             "home": {"id": 1}, "away": {"id": 2}}
    pendiente = {**match, "id": 501, "status": "pending"}
    _guardar("jugador", {"id": 7, "reports": [
        {"home": False, "match": match},  # sin 'points': no jugó
        {"home": False, "match": pendiente, "points": {"5": 3}},
    ]}, D14, "7")
    [fila] = tablas.fact_puntos_jornada(leer("jugador"), [])
    assert (fila["partido_id"], fila["jugo"], fila["puntos"], fila["rival_id"]) == (500, False, None, 1)


def test_calendario_no_pierde_datos_con_fuentes_incompletas():
    _guardar("jornadas", {"id": 8, "name": "Jornada 8", "games": [_partido(500, "finished", (2, 1))]}, D13)
    comp = _competicion(100, 0)
    # nextGames trae solo ids: no debe borrar goles, estado ni jornada.
    comp["teams"]["1"]["nextGames"] = [{"id": 500, "date": 1791500000, "home": {"id": 1},
                                        "away": {"id": 2}, "round": {"id": 8}}]
    _guardar("competicion", comp, D14)
    [p] = tablas.dim_calendario(leer("competicion"), leer("jornadas"), [])
    assert (p["jornada"], p["goles_local"], p["goles_visitante"], p["estado"], p["visitante"]) == (
        "Jornada 8", 2, 1, "finished", "Betis")


def test_once_probable_solo_de_partidos_sin_jugar():
    _guardar("jornada", {"id": 9, "name": "Jornada 9", "games": [
        _partido(600, "preview", reports=([_report(7, None)], [_report(9, None)])),
        _partido(601, "finished", reports=([_report(8, 4)], [])),
    ]}, D14, clave="9")
    filas = tablas.fact_once_probable(leer("jornada"))
    assert [(f["partido_id"], f["equipo_id"], f["jugador_id"]) for f in filas] == [(600, 1, 7), (600, 2, 9)]


def test_mi_liga_plantilla_saldo_y_mercado():
    _guardar("plantilla", {
        "id": 11, "balance": -500, "points": 30,
        "lineup": {"type": "3-4-3", "playersID": [7, None]},
        "market": [{"type": "sale", "playerID": 8, "price": 2100, "date": 1791500000,
                    "until": 1792040400, "player": None}],
        "players": [{"id": 7, "owner": {"date": 1791500000, "price": 1000}},
                    {"id": 8, "owner": {"date": 1791500000, "price": 2000}}],
    }, D14)
    _guardar("mercado", {"status": {"balance": -500, "maximumBid": 9000}, "offers": [], "sales": [
        {"player": {"id": 20}, "price": 300, "user": None, "date": 1791500000, "until": 1792040400},
        {"player": {"id": 21}, "price": 400, "user": {"id": 12}, "date": 1791500000, "until": 1792040400},
    ]}, D14)
    _guardar("liga", {"id": 1, "standings": [{"id": 12, "teamValue": 1, "position": 1},
                                              {"id": 11, "teamValue": 7000, "position": 2}]}, D14)
    r = construir()

    assert [(f["jugador_id"], f["alineado"], f["precio_compra"]) for f in r["mi_plantilla"]] == [
        (7, True, 1000), (8, False, 2000)]
    assert r["mi_saldo"] == [{"fecha": "2026-10-14", "saldo": -500, "puja_maxima": 9000,
                              "valor_equipo": 7000, "puntos": 30, "posicion_liga": 2}]
    assert [(f["jugador_id"], f["vendedor_id"], f["vendedor_es_biwenger"]) for f in
            r["fact_mercado_dia"]] == [(20, None, True), (21, 12, False)]
    assert r["fact_mercado_dia"][0]["cierre_utc"] == "2026-10-15T05:00:00Z"
    assert r["mis_ventas"] == [{"fecha": "2026-10-14", "jugador_id": 8, "precio_pedido": 2100,
                                "publicado_utc": "2026-10-08T22:53:20Z",
                                "cierre_utc": "2026-10-15T05:00:00Z"}]


def test_todas_las_tablas_respetan_su_esquema():
    _guardar("competicion", _competicion(100, 0, estado="injured"), D14)
    for nombre, filas in construir().items():
        for f in filas:
            assert list(f) == tablas.ESQUEMAS[nombre], nombre
