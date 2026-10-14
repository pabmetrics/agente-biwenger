"""Cliente de la API interna de Biwenger (no oficial).

Dos familias de endpoints (ver docs/api-biwenger.md):
- Públicos, en cf.biwenger.com: jugadores, precios, jornadas. Sin token.
- Privados, en biwenger.as.com: cuenta, plantilla, mercado, ofertas. Con token
  Bearer y las cabeceras X-League / X-User de la liga.

Este cliente solo lee. Las acciones de escritura (pujar, vender, alinear) no
viven aquí: las ejecuta la Azure Function tras la confirmación por Telegram.
"""

from __future__ import annotations

import os
import time

import httpx

URL_PUBLICA = "https://cf.biwenger.com/api/v2"
URL_PRIVADA = "https://biwenger.as.com/api/v2"
COMPETICION = "la-liga"
# 5 = "Media AS y SofaScore", la puntuación de la liga (ver /competitions/la-liga/data -> scores).
SCORE_ID = 5

USER_AGENT = "Mozilla/5.0 (agente-biwenger; uso personal)"
PAUSA_ENTRE_LLAMADAS_S = 1.0
REINTENTOS = 3


class BiwengerError(RuntimeError):
    pass


class LimiteSuperado(BiwengerError):
    """429: Biwenger pide esperar "unas horas". Hay que parar, no reintentar."""


class BiwengerAPI:
    def __init__(
        self,
        token: str | None = None,
        league_id: str | None = None,
        user_id: str | None = None,
        pausa_s: float = PAUSA_ENTRE_LLAMADAS_S,
    ):
        self.token = token or os.getenv("BIWENGER_TOKEN")
        self.league_id = league_id or os.getenv("BIWENGER_LEAGUE_ID")
        self.user_id = user_id or os.getenv("BIWENGER_USER_ID")
        self.pausa_s = pausa_s
        self._ultima_llamada = 0.0
        self.ultima_url: str = ""
        self.ultimos_params: dict = {}
        self._http = httpx.Client(
            timeout=30,
            headers={"User-Agent": USER_AGENT, "X-Lang": "es", "Accept": "application/json"},
        )

    # --- infraestructura ---------------------------------------------------

    def _get(self, url: str, params: dict | None = None, privada: bool = False) -> dict:
        headers = self._cabeceras_privadas() if privada else {}
        self.ultima_url, self.ultimos_params = url, params or {}
        for intento in range(1, REINTENTOS + 1):
            espera = self.pausa_s - (time.monotonic() - self._ultima_llamada)
            if espera > 0:
                time.sleep(espera)
            self._ultima_llamada = time.monotonic()
            try:
                r = self._http.get(url, params=params, headers=headers)
            except httpx.TransportError as e:
                if intento == REINTENTOS:
                    raise BiwengerError(f"Error de red en {url}: {e}") from e
                time.sleep(2**intento)
                continue
            if r.status_code >= 500 and intento < REINTENTOS:
                time.sleep(2**intento)
                continue
            if r.status_code == 429:
                raise LimiteSuperado(f"429 en {url}: límite de peticiones superado")
            if r.status_code == 401:
                raise BiwengerError(f"401 en {url}: token ausente o caducado")
            if r.status_code != 200:
                raise BiwengerError(f"{r.status_code} en {url}: {r.text[:200]}")
            cuerpo = r.json()
            if cuerpo.get("status") != 200 or "data" not in cuerpo:
                raise BiwengerError(f"Respuesta inesperada en {url}: {str(cuerpo)[:200]}")
            return cuerpo
        raise BiwengerError(f"Sin respuesta válida de {url}")

    def _cabeceras_privadas(self) -> dict:
        if not self.token:
            raise BiwengerError("Falta BIWENGER_TOKEN (ver .env.example)")
        h = {"Authorization": f"Bearer {self.token}"}
        if self.league_id:
            h["X-League"] = str(self.league_id)
        if self.user_id:
            h["X-User"] = str(self.user_id)
        return h

    @property
    def tiene_token(self) -> bool:
        return bool(self.token)

    # --- públicos ----------------------------------------------------------

    def competicion(self) -> dict:
        """Foto del día: los ~550 jugadores (precio, variación, estado, forma) y equipos."""
        return self._get(
            f"{URL_PUBLICA}/competitions/{COMPETICION}/data",
            {"lang": "es", "score": SCORE_ID},
        )

    def jornadas(self) -> dict:
        """Jornada actual/última con partidos, clasificación, MVP y once ideal."""
        return self._get(f"{URL_PUBLICA}/rounds/{COMPETICION}", {"lang": "es", "score": SCORE_ID})

    def jornada(self, round_id: int) -> dict:
        """Una jornada concreta; si está en 'preview' trae los onces probables."""
        return self._get(
            f"{URL_PUBLICA}/rounds/{COMPETICION}/{round_id}", {"lang": "es", "score": SCORE_ID}
        )

    def jugador(self, slug_o_id: str | int) -> dict:
        """Detalle de un jugador: ~1 año de precios diarios y puntos por partido."""
        return self._get(
            f"{URL_PUBLICA}/players/{COMPETICION}/{slug_o_id}",
            {
                "lang": "es",
                "score": SCORE_ID,
                "fields": "*,team,fitness,reports(points,home,events.type(0),"
                "match(*,round,home,away),star),prices,competition,seasons",
            },
        )

    # --- privados (requieren token; verificados el 14/10/2026) -------------

    def cuenta(self) -> dict:
        """Usuario y ligas; de aquí salen BIWENGER_LEAGUE_ID y BIWENGER_USER_ID."""
        return self._get(f"{URL_PRIVADA}/account", privada=True)

    def plantilla(self) -> dict:
        """Mis jugadores, alineación y saldo."""
        return self._get(
            f"{URL_PRIVADA}/user",
            {"fields": "*,lineup(type,playersID),players(id,owner),market"},
            privada=True,
        )

    def mercado(self) -> dict:
        """Jugadores en venta hoy y ofertas recibidas."""
        return self._get(f"{URL_PRIVADA}/market", privada=True)

    def liga(self) -> dict:
        """Clasificación y mánagers de la liga."""
        return self._get(
            f"{URL_PRIVADA}/league", {"include": "all", "fields": "*,standings"}, privada=True
        )
