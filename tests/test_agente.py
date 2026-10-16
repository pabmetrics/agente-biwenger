import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent import agente, herramientas
from agent.datos import Datos
from agent.validacion import validar

HOY = "2026-10-16"
# Mi plantilla: 1 POR, 4 DEF, 3 MED, 4 DEL (ids por posición) + un DEL lesionado.
POS = {1: 1, **{i: 2 for i in (2, 3, 4, 5)}, **{i: 3 for i in (6, 7, 8)}, **{i: 4 for i in (9, 10, 11, 12, 13)}}
LESIONADO = 13


def _datos(saldo=100, inicio_jornada="2026-10-17T19:00:00Z"):
    jugadores = [{"jugador_id": j, "nombre": f"J{j}", "slug": f"j{j}", "equipo_id": 1, "equipo": "Eq",
                  "posicion": p, "posicion_nombre": "", "estado": "injured" if j == LESIONADO else "ok",
                  "estado_info": None, "estado_desde": None, "fecha": HOY} for j, p in {**POS, 50: 4, 51: 3}.items()]
    silver = {
        "dim_jugador": jugadores,
        "mi_saldo": [{"fecha": HOY, "saldo": saldo, "puja_maxima": 5000, "valor_equipo": 0, "puntos": 0, "posicion_liga": 1}],
        "mi_plantilla": [{"fecha": HOY, "jugador_id": j, "fecha_compra": HOY, "precio_compra": 1000,
                          "alineado": False} for j in POS],
        "mis_ventas": [],
        "fact_mercado_dia": [
            {"fecha": HOY, "jugador_id": 50, "precio": 1000, "vendedor_id": None, "vendedor_es_biwenger": True,
             "publicado_utc": None, "cierre_utc": "2026-10-17T05:00:00Z"},
            {"fecha": HOY, "jugador_id": 51, "precio": 300, "vendedor_id": 9, "vendedor_es_biwenger": False,
             "publicado_utc": None, "cierre_utc": "2026-10-17T05:00:00Z"}],
        "fact_ofertas": [{"fecha": HOY, "oferta_id": 77, "jugador_id": 12, "importe": 1050, "n_jugadores": 1,
                          "de_id": None, "de_biwenger": True, "estado": "waiting", "tipo": "purchase",
                          "creada_utc": None, "caduca_utc": None}],
        "dim_calendario": [{"partido_id": 1, "jornada_id": 9, "jornada": "Jornada 9", "fecha": inicio_jornada[:10],
                            "inicio_utc": inicio_jornada, "local_id": 1, "local": "Eq", "visitante_id": 2,
                            "visitante": "Otro", "goles_local": None, "goles_visitante": None, "estado": "pending",
                            "dificultad_local": 40, "dificultad_visitante": 60}],
        "fact_valor_diario": [{"jugador_id": j, "fecha": HOY, "valor": 1000, "variacion": 0, "origen": "foto",
                               "estado": "ok"} for j in [*POS, 50, 51]],
        "fact_puntos_jornada": [],
    }
    gold = {
        "features_jugador": [{"jugador_id": j, "fecha": HOY, "valor": 1000, "var_1d_pct": 1.0, "media_3d_pct": 1.0,
                              "media_7d_pct": 1.0, "var_30d_pct": 5.0, "dias_subiendo": 1, "estado": "ok",
                              "partidos_temporada": 5, "media_puntos_temp": 5.0, "forma5": 5.0, "p_juega5": 1.0,
                              "minutos_ult3": 90.0} for j in [*POS, 50, 51]],
        "score_revalorizacion": [{"jugador_id": j, "fecha": HOY, "valor": 1000, "subida_1d_pct": 0.8,
                                  "subida_3d_pct": 2.2, "subida_3d_eur": 22, "estado": "ok", "disponible": True}
                                 for j in [*POS, 50, 51]],
        "score_puntos_esperados": [],
    }
    return Datos(silver, gold)


AHORA = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)
ONCE_4_3_3 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]


def _paquete(**cambios):
    return {"resumen": "x", "compras": [], "ventas": [], "aceptar_ofertas": [], "alineacion": None, **cambios}


def test_paquete_vacio_es_valido():
    errores, info = validar(_datos(), _paquete(), AHORA)
    assert errores == [] and info["saldo_al_empezar_la_jornada"] == 100


def test_compra_sin_dinero_hay_que_cubrirla_con_ventas_al_95():
    d = _datos()
    compra = [{"jugador_id": 50, "puja": 1000, "motivo": ""}]
    errores, _ = validar(d, _paquete(compras=compra), AHORA)
    assert any("saldo quedaría en -900" in e for e in errores)
    # Vender uno de 1000 cubre 950: 100 + 950 - 1000 = 50 >= 0
    errores, info = validar(d, _paquete(compras=compra, ventas=[{"jugador_id": 12, "motivo": ""}]), AHORA)
    assert errores == [] and info["saldo_al_empezar_la_jornada"] == 50


def test_si_la_jornada_empieza_antes_del_mercado_las_ventas_no_cuentan():
    d = _datos(inicio_jornada="2026-10-16T19:00:00Z")  # hoy a las 21:00, antes de las 7:00 de mañana
    paquete = _paquete(compras=[{"jugador_id": 50, "puja": 1000, "motivo": ""}],
                       ventas=[{"jugador_id": 12, "motivo": ""}])
    errores, info = validar(d, paquete, AHORA)
    assert not info["ventas_cobran_antes_de_la_jornada"]
    assert any("no cobran antes" in e for e in errores)
    # Aceptar una oferta sí cuenta: el dinero entra al aceptarla.
    errores, _ = validar(d, _paquete(compras=[{"jugador_id": 51, "puja": 300, "motivo": ""}],
                                     aceptar_ofertas=[{"oferta_id": 77, "motivo": ""}]), AHORA)
    assert errores == []


def test_compras_imposibles():
    errores, _ = validar(_datos(saldo=10**7), _paquete(compras=[
        {"jugador_id": 50, "puja": 900, "motivo": ""},     # por debajo del precio
        {"jugador_id": 51, "puja": 6000, "motivo": ""},    # por encima de la puja máxima
        {"jugador_id": 99, "puja": 100, "motivo": ""},     # no está en el mercado
    ]), AHORA)
    assert len(errores) == 3


def test_alineacion_valida_y_errores_de_alineacion():
    d = _datos()
    ok = {"formacion": "4-3-3", "jugadores": ONCE_4_3_3, "ariete_id": 9, "dudas": ""}
    assert validar(d, _paquete(alineacion=ok), AHORA)[0] == []
    # De pago también vale, si las posiciones cuadran.
    pago = {**ok, "formacion": "4-2-4", "jugadores": [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12]}
    errores, info = validar(d, _paquete(alineacion=pago), AHORA)
    assert errores == [] and info["formacion_de_pago"]

    malas = {
        "formación inexistente": {**ok, "formacion": "2-4-4"},
        "posiciones que no cuadran": {**ok, "formacion": "4-4-2"},
        "lesionado": {**ok, "jugadores": [*ONCE_4_3_3[:10], LESIONADO]},
        "ariete fuera": {**ok, "ariete_id": 12},
        "solo 10": {**ok, "jugadores": ONCE_4_3_3[:10]},
    }
    for caso, alineacion in malas.items():
        assert validar(d, _paquete(alineacion=alineacion), AHORA)[0], caso
    # Alinear a alguien que se vende en el mismo paquete: mandan los puntos.
    errores, _ = validar(d, _paquete(alineacion=ok, ventas=[{"jugador_id": 9, "motivo": ""}]), AHORA)
    assert any("véndelos después" in e for e in errores)


def test_herramientas_de_lectura():
    d = _datos()
    plantilla = herramientas.leer_plantilla_y_saldo(d)
    assert plantilla["saldo"] == 100 and len(plantilla["jugadores"]) == len(POS)
    assert plantilla["jugadores"][0]["posicion"] == "POR"
    mercado = herramientas.leer_mercado_con_scores(d)
    assert {j["jugador_id"] for j in mercado["jugadores"]} == {50, 51}
    assert {j["vendedor"] for j in mercado["jugadores"]} == {"Biwenger", "mánager"}
    [oferta] = herramientas.leer_ofertas_recibidas(d)["ofertas"]
    assert oferta["pct_sobre_valor"] == 5.0
    with pytest.raises(ValueError):
        herramientas.leer_jugador(d, 12345)


def _uso(id_, nombre, entrada):
    return SimpleNamespace(type="tool_use", id=id_, name=nombre, input=entrada)


class ClienteFalso:
    """Responde con una secuencia fija y guarda lo que recibe."""

    def __init__(self, respuestas):
        self.respuestas, self.llamadas = list(respuestas), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.llamadas.append({**kw, "messages": list(kw["messages"])})  # foto: la lista sigue creciendo
        contenido = self.respuestas.pop(0)
        return SimpleNamespace(stop_reason="tool_use", stop_details=None, content=contenido)


def test_el_agente_corrige_un_paquete_invalido_y_lo_registra():
    d = _datos()
    invalido = _paquete(compras=[{"jugador_id": 50, "puja": 1000, "motivo": "sube"}])
    valido = _paquete(compras=invalido["compras"], ventas=[{"jugador_id": 12, "motivo": "baja"}])
    cliente = ClienteFalso([
        [_uso("a", "leer_plantilla_y_saldo", {}), _uso("b", "leer_mercado_con_scores", {})],
        [_uso("c", "proponer_accion", invalido)],
        [_uso("d", "proponer_accion", valido)],
    ])
    registradas, enviados = [], []
    fila = agente.ejecutar(d, registradas.append, lambda t: enviados.append(t) or True, cliente, AHORA)

    assert len(cliente.llamadas) == 3
    # Las dos lecturas vuelven juntas en un único mensaje de usuario.
    lecturas = cliente.llamadas[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in lecturas] == ["a", "b"]
    # El paquete inválido vuelve como error con el motivo.
    error = cliente.llamadas[2]["messages"][-1]["content"][0]
    assert error["is_error"] and "saldo quedaría" in error["content"]
    # Solo se registra y envía el válido.
    assert registradas == [fila] and json.loads(fila["paquete"]) == valido
    assert fila["estado"] == "informativa" and fila["jornada_id"] == 9
    [mensaje] = enviados
    assert "J50" in mensaje and "J12" in mensaje and "Solo informativo" in mensaje


def test_el_agente_nunca_tiene_herramientas_de_escritura():
    nombres = {t["name"] for t in herramientas.DEFINICIONES}
    assert nombres == {"leer_plantilla_y_saldo", "leer_mercado_con_scores", "leer_ofertas_recibidas",
                       "leer_jugador", "proponer_accion"}
