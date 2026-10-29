"""Caché en disco con tiempo de vida, para no repetir consultas a las APIs satelitales."""
import hashlib
import json
import pickle
import time
from typing import Any, Callable

from .config import CACHE_DIR


def _ruta(clave: Any):
    texto = json.dumps(clave, sort_keys=True, default=str)
    return CACHE_DIR / f"{hashlib.sha256(texto.encode()).hexdigest()[:24]}.pkl"


def memo(clave: Any, ttl: int, calcular: Callable[[], Any], forzar: bool = False) -> Any:
    """Devuelve el valor cacheado para `clave` o lo calcula y guarda si expiró."""
    ruta = _ruta(clave)
    if not forzar and ruta.exists() and time.time() - ruta.stat().st_mtime < ttl:
        try:
            with ruta.open("rb") as f:
                return pickle.load(f)
        except Exception:  # caché de otra versión de librerías o archivo dañado: se vuelve a calcular
            pass
    valor = calcular()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with ruta.open("wb") as f:
        pickle.dump(valor, f)
    return valor


def leer(clave: Any) -> Any:
    """Valor guardado para `clave` sin importar su antigüedad, o None si no existe (no consulta la red)."""
    ruta = _ruta(clave)
    if not ruta.exists():
        return None
    try:
        with ruta.open("rb") as f:
            return pickle.load(f)
    except Exception:
        return None
