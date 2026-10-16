import pytest

from transform.gold import reglas, tablas
from transform.silver import delta


def _valor(jid, fecha, valor, estado=None):
    return {"jugador_id": jid, "fecha": fecha, "valor": valor, "variacion": None,
            "origen": "foto" if estado else "historico", "estado": estado}


def _partido_jugado(jid, fecha, puntos, jugo=True, minutos=90):
    return {"jugador_id": jid, "partido_id": hash(fecha) % 1000, "fecha": fecha, "jugo": jugo,
            "puntos": puntos if jugo else None, "minutos": minutos if jugo else None}


def _calendario(pid, fecha, local_id, visitante_id, dif_local=50, dif_visitante=50, estado="pending"):
    return {"partido_id": pid, "jornada_id": 9, "jornada": "Jornada 9", "fecha": fecha,
            "local_id": local_id, "visitante_id": visitante_id, "estado": estado,
            "dificultad_local": dif_local, "dificultad_visitante": dif_visitante}


def test_features_de_valor_y_racha():
    valores = [_valor(7, f"2026-10-{d:02d}", v) for d, v in
               [(1, 100), (2, 100), (3, 110), (4, 121), (5, 120)]]
    f = {x["fecha"]: x for x in tablas.features_jugador(valores, [])}
    assert f["2026-10-04"]["var_1d_pct"] == 10.0
    assert f["2026-10-04"]["media_3d_pct"] == pytest.approx(7.0, abs=1e-3)  # +21 % en 3 días
    assert [f[k]["dias_subiendo"] for k in sorted(f)] == [0, 0, 1, 2, 0]
    assert f["2026-10-02"]["media_3d_pct"] is None  # no hay valor de hace 3 días


def test_features_solo_usan_partidos_anteriores_a_la_fecha():
    valores = [_valor(7, "2026-10-10", 100), _valor(7, "2026-10-11", 100)]
    puntos = [_partido_jugado(7, "2026-10-05", 4), _partido_jugado(7, "2026-10-10", 20)]
    f = {x["fecha"]: x for x in tablas.features_jugador(valores, puntos)}
    # El partido del mismo día 10 no cuenta para el día 10, solo desde el 11.
    assert (f["2026-10-10"]["partidos_temporada"], f["2026-10-10"]["media_puntos_temp"]) == (1, 4.0)
    assert (f["2026-10-11"]["partidos_temporada"], f["2026-10-11"]["media_puntos_temp"]) == (2, 12.0)


def test_forma_y_probabilidad_de_jugar_en_los_ultimos_5():
    puntos = [_partido_jugado(7, f"2026-09-{d:02d}", p, jugo=j) for d, p, j in
              [(1, 20, True), (2, 6, True), (3, 0, False), (4, 4, True), (5, 0, False), (6, 2, True)]]
    [f] = tablas.features_jugador([_valor(7, "2026-10-01", 100)], puntos)
    assert f["media_puntos_temp"] == 8.0  # (20+6+4+2)/4
    assert f["forma5"] == 4.0  # últimos 5: 6, -, 4, -, 2
    assert f["p_juega5"] == 0.6


def test_score_de_revalorizacion_sigue_la_regla():
    valores = [_valor(7, f"2026-10-{d:02d}", v) for d, v in [(1, 100), (2, 100), (3, 100), (4, 110)]]
    [s] = tablas.score_revalorizacion(tablas.features_jugador(valores, []))
    esperado = reglas.subida_3d(10.0, 10.0 / 3)
    assert s["subida_3d_pct"] == pytest.approx(esperado, abs=1e-3)
    assert s["subida_3d_eur"] == round(110 * esperado / 100)
    assert s["disponible"] is True


def test_lesionados_no_estan_disponibles_ni_puntuan():
    valores = [_valor(7, f"2026-10-{d:02d}", 100, "injured") for d in (1, 2, 3, 4)]
    puntos = [_partido_jugado(7, "2026-09-20", 10)]
    feats = tablas.features_jugador(valores, puntos)
    assert not tablas.score_revalorizacion(feats)[0]["disponible"]
    pe = tablas.score_puntos_esperados(
        feats, [_calendario(1, "2026-10-05", 1, 2)], [], [{"jugador_id": 7, "equipo_id": 1}])
    assert {r["puntos_esperados"] for r in pe} == {0.0}


def test_puntos_esperados_del_siguiente_partido_con_once_y_rival():
    feats = tablas.features_jugador(
        [_valor(7, "2026-10-04", 100, "ok"), _valor(8, "2026-10-04", 100, "ok")],
        [_partido_jugado(j, f"2026-09-{d:02d}", 6) for j in (7, 8) for d in (1, 2, 3, 4, 5)])
    calendario = [
        _calendario(1, "2026-09-28", 1, 2, estado="finished"),  # ya pasado: no cuenta
        _calendario(2, "2026-10-05", 2, 1, dif_local=20, dif_visitante=80),  # equipo 1 fuera, difícil
        _calendario(3, "2026-10-12", 1, 2),
    ]
    once = [{"fecha": "2026-10-04", "partido_id": 2, "jugador_id": 7}]
    jugadores = [{"jugador_id": 7, "equipo_id": 1}, {"jugador_id": 8, "equipo_id": 1}]
    pe = {r["jugador_id"]: r for r in tablas.score_puntos_esperados(feats, calendario, once, jugadores)}

    assert (pe[7]["partido_id"], pe[7]["local"], pe[7]["rival_id"], pe[7]["dificultad"]) == (2, False, 2, 80)
    assert pe[7]["en_once_probable"] is True and pe[8]["en_once_probable"] is False
    factor = reglas.factor_rival(80)
    assert factor < 1
    assert pe[7]["puntos_esperados"] == round(6 * 1.0 * factor, 2)
    assert pe[8]["puntos_esperados"] == round(6 * reglas.P_JUEGA_SI_FUERA_DEL_ONCE * factor, 2)


def test_sin_once_publicado_se_usa_la_probabilidad_historica():
    assert reglas.p_juega(0.6, None, "ok") == 0.6
    assert reglas.p_juega(0.6, None, "doubt") == 0.3
    assert reglas.p_juega(None, None, "ok") == 0.5


def test_tipos_delta_de_gold():
    assert delta.esquema_ddl("score_revalorizacion") == (
        "jugador_id BIGINT, fecha DATE, valor BIGINT, subida_1d_pct DOUBLE, subida_3d_pct DOUBLE, "
        "subida_3d_eur BIGINT, estado STRING, disponible BOOLEAN")
    assert "paquete STRING" in delta.esquema_ddl("log_acciones")
    # Un entero en una columna DOUBLE se convierte, para que Spark no lo rechace.
    [fila] = delta.filas_tipadas("score_puntos_esperados", [dict.fromkeys(
        tablas.ESQUEMAS["score_puntos_esperados"]) | {"puntos_esperados": 0, "fecha_calculo": "2026-10-16"}])
    assert isinstance(fila[-1], float)
