"""Reglas de la Fase 3 y de dónde salen sus números.

Revalorización — backtest del 16/10/2026 sobre fact_valor_diario (~121.000
jugador×día; pesos ajustados por mínimos cuadrados con los datos hasta
mediados de agosto de 2026 y probados en las 8 semanas siguientes, que no se
usaron para ajustar):

    variación de mañana (%) ≈ 0,54 · var_hoy + 0,26 · media_3d
        acierto del signo 96,5 %; error medio 0,58 pp frente a 1,38 de "no cambia".
        El 10 % con más subida prevista subió +4,9 % de media (previsto +4,5 %).
    variación a 3 días (%) ≈ 1,64 · var_hoy + 0,60 · media_3d
        acierto del signo 91,2 %; el 10 % mejor subió +13,8 % (previsto +12,8 %).

La media de 7 días no aporta nada una vez que están las otras dos (peso ≈ 0).
El valor en Biwenger tiene mucha inercia: lo que sube hoy suele seguir subiendo.

Puntos esperados — backtest sobre fact_puntos_jornada (2.356 partidos):

    (0,5 · media de la temporada + 0,5 · forma de los últimos 5) × p(juega)
        error medio 2,06 puntos frente a 2,28 de la media sola; correlación 0,47.
    p(juega) = partidos jugados de los últimos 5. Usar la titularidad empeoraba
    el resultado (error 2,15), así que no se usa.

SIN VALIDAR todavía (no hay partidos jugados con estos datos guardados):
el once probable y la dificultad del rival. Pesan poco a propósito; hay que
revisarlos cuando haya jornadas jugadas con su once probable y su dificultad
guardados en silver.
"""

PESO_1D = {"var_hoy": 0.54, "media_3d": 0.26}
PESO_3D = {"var_hoy": 1.64, "media_3d": 0.60}

PESO_MEDIA_TEMPORADA = 0.5
PESO_FORMA = 0.5
PARTIDOS_FORMA = 5

# Once probable (sin validar): si sale, se juega casi seguro; si no, casi nunca.
P_JUEGA_SI_EN_ONCE = 0.85
P_JUEGA_SI_FUERA_DEL_ONCE = 0.25

# Estado del jugador.
NO_DISPONIBLE = {"injured", "sanctioned"}
FACTOR_DUDA = 0.5  # 'doubt' multiplica la probabilidad de jugar

# Dificultad del rival (sin validar): ±15 % como mucho. 50 = partido normal.
SENSIBILIDAD_RIVAL = 0.3
FACTOR_RIVAL_MIN, FACTOR_RIVAL_MAX = 0.85, 1.15


def subida_1d(var_hoy: float, media_3d: float) -> float:
    return PESO_1D["var_hoy"] * var_hoy + PESO_1D["media_3d"] * media_3d


def subida_3d(var_hoy: float, media_3d: float) -> float:
    return PESO_3D["var_hoy"] * var_hoy + PESO_3D["media_3d"] * media_3d


def factor_rival(dificultad: int | None) -> float:
    if dificultad is None:
        return 1.0
    f = 1 + SENSIBILIDAD_RIVAL * (50 - dificultad) / 100
    return min(FACTOR_RIVAL_MAX, max(FACTOR_RIVAL_MIN, f))


def p_juega(p_historica: float | None, en_once: bool | None, estado: str | None) -> float:
    if estado in NO_DISPONIBLE:
        return 0.0
    p = p_historica if p_historica is not None else 0.5
    if en_once is True:
        p = max(p, P_JUEGA_SI_EN_ONCE)
    elif en_once is False:
        p = min(p, P_JUEGA_SI_FUERA_DEL_ONCE)
    if estado == "doubt":
        p *= FACTOR_DUDA
    return p
