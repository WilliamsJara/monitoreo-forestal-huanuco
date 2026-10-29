"""Cliente mínimo de Copernicus Data Space (Sentinel Hub): OAuth2, Statistical API y Process API."""
import threading
import time

import requests

from . import config


class ErrorCopernicus(RuntimeError):
    pass


class ClienteCopernicus:
    def __init__(self, client_id: str = "", client_secret: str = "", timeout: int = 180, reintentos: int = 4):
        """`timeout` (s por consulta) y `reintentos` ante saturación (429/5xx): el tablero usa valores cortos
        para no hacer esperar al usuario; las corridas programadas, los valores por defecto."""
        self.timeout = timeout
        self.reintentos = reintentos
        self.client_id = client_id or config.SH_CLIENT_ID
        self.client_secret = client_secret or config.SH_CLIENT_SECRET
        self._token = ""
        self._expira = 0.0
        self._lock = threading.Lock()
        self.sesion = requests.Session()

    def _cabecera(self) -> dict:
        with self._lock:
            if time.time() > self._expira - 60:
                r = self.sesion.post(
                    config.CDSE_TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    timeout=30,
                )
                if r.status_code != 200:
                    raise ErrorCopernicus(f"Autenticación fallida ({r.status_code}): {r.text[:200]}")
                datos = r.json()
                self._token = datos["access_token"]
                self._expira = time.time() + datos.get("expires_in", 600)
            return {"Authorization": f"Bearer {self._token}"}

    def _post(self, url: str, payload: dict, accept: str) -> requests.Response:
        for intento in range(self.reintentos):
            r = self.sesion.post(
                url, json=payload, headers={**self._cabecera(), "Accept": accept}, timeout=self.timeout
            )
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(int(r.headers.get("Retry-After", 2 ** (intento + 1))))
                continue
            if r.status_code != 200:
                raise ErrorCopernicus(f"{url.rsplit('/', 1)[-1]} {r.status_code}: {r.text[:300]}")
            return r
        raise ErrorCopernicus(f"{url} no respondió tras varios reintentos ({r.status_code})")

    def estadisticas(self, payload: dict) -> dict:
        return self._post(config.CDSE_STATS_URL, payload, "application/json").json()

    def procesar(self, payload: dict, accept: str = "image/png") -> bytes:
        return self._post(config.CDSE_PROCESS_URL, payload, accept).content
