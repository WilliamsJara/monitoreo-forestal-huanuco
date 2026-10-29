"""Focos de calor de NASA FIRMS y agrupación en eventos de incendio (DBSCAN)."""
import io
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
from sklearn.cluster import DBSCAN

from . import cache, config, geo

RADIO_TIERRA_KM = 6371.0
MAX_DIAS_CONSULTA = 5

COLUMNAS = [
    "latitud", "longitud", "fecha", "hora", "fuente", "satelite",
    "confianza", "frp", "brillo_k", "dia_noche",
]


def _confianza(df: pd.DataFrame) -> pd.Series:
    """Normaliza la confianza: VIIRS usa l/n/h, MODIS usa 0-100."""
    c = df["confidence"].astype(str).str.lower()
    numerica = pd.to_numeric(c, errors="coerce")
    texto = c.map({"l": "baja", "n": "nominal", "h": "alta"})
    por_numero = pd.cut(numerica, [-1, 30, 80, 101], labels=["baja", "nominal", "alta"]).astype(object)
    return texto.fillna(por_numero).fillna("nominal")


def _descargar(fuente: str, dias: int, inicio: date, bbox: tuple) -> pd.DataFrame:
    area = ",".join(f"{v:.4f}" for v in bbox)
    url = f"{config.FIRMS_AREA_URL}/{config.FIRMS_MAP_KEY}/{fuente}/{area}/{dias}/{inicio.isoformat()}"
    try:
        r = requests.get(url, timeout=60)
    except requests.RequestException as e:
        # El mensaje de requests incluye la URL, que contiene la MAP_KEY: no se propaga
        raise RuntimeError(f"FIRMS {fuente}: sin conexión ({type(e).__name__})") from None
    texto = r.text.strip()
    if r.status_code != 200 or (texto and not texto.startswith("latitude")):
        raise RuntimeError(f"FIRMS {fuente} ({r.status_code}): {texto[:200]}")
    if not texto:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(texto))
    if df.empty:
        return df
    brillo = df["bright_ti4"] if "bright_ti4" in df else df["brightness"]
    return pd.DataFrame({
        "latitud": df["latitude"],
        "longitud": df["longitude"],
        "fecha": pd.to_datetime(df["acq_date"]),
        "hora": df["acq_time"].astype(int).map(lambda t: f"{t // 100:02d}:{t % 100:02d}"),
        "fuente": fuente,
        "satelite": df["satellite"].astype(str),
        "confianza": _confianza(df),
        "frp": pd.to_numeric(df["frp"], errors="coerce").fillna(0.0),
        "brillo_k": pd.to_numeric(brillo, errors="coerce"),
        "dia_noche": df["daynight"].map({"D": "día", "N": "noche"}),
    })


def _ventanas(dias: int, hoy: date) -> list[tuple[date, int]]:
    """La API acepta como máximo 5 días por consulta: divide el periodo en ventanas."""
    inicio = hoy - timedelta(days=dias - 1)
    ventanas = []
    while inicio <= hoy:
        n = min(MAX_DIAS_CONSULTA, (hoy - inicio).days + 1)
        ventanas.append((inicio, n))
        inicio += timedelta(days=n)
    return ventanas


def focos_de_calor(dias: int = 7, fuentes: list[str] | None = None, forzar: bool = False) -> pd.DataFrame:
    """Focos de calor dentro de las provincias de Huánuco en los últimos `dias` (1-30)."""
    dias = int(min(max(dias, 1), 30))
    fuentes = fuentes or list(config.FIRMS_FUENTES)
    bbox = geo.bbox_region()
    hoy = date.today()
    partes = []
    for f in fuentes:
        for inicio, n in _ventanas(dias, hoy):
            # Las ventanas cerradas ya no cambian: se cachean por más tiempo
            ttl = config.TTL_FIRMS if inicio + timedelta(days=n) > hoy - timedelta(days=2) else 7 * 86400
            partes.append(cache.memo(("firms", f, inicio, n, bbox), ttl,
                                     lambda f=f, i=inicio, n=n: _descargar(f, n, i, bbox), forzar))
    partes = [p for p in partes if not p.empty]
    if not partes:
        return pd.DataFrame(columns=COLUMNAS + ["provincia"])
    df = pd.concat(partes, ignore_index=True).drop_duplicates(
        subset=["latitud", "longitud", "fecha", "hora", "fuente"])
    df["provincia"] = geo.asignar_provincia(df["longitud"].to_numpy(), df["latitud"].to_numpy())
    return df.dropna(subset=["provincia"]).reset_index(drop=True)


def agrupar_eventos(focos: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Agrupa focos cercanos en eventos de incendio con DBSCAN (métrica haversine).

    Devuelve (focos con columna `evento`, tabla de eventos). `evento = -1` = foco aislado.
    """
    focos = focos.copy()
    if focos.empty:
        focos["evento"] = []
        return focos, pd.DataFrame()
    coords = np.radians(focos[["latitud", "longitud"]].to_numpy())
    modelo = DBSCAN(
        eps=config.DBSCAN_EPS_KM / RADIO_TIERRA_KM,
        min_samples=config.DBSCAN_MIN_FOCOS,
        metric="haversine",
        algorithm="ball_tree",
    )
    focos["evento"] = modelo.fit_predict(coords)
    agrupados = focos[focos["evento"] >= 0]
    if agrupados.empty:
        return focos, pd.DataFrame()
    eventos = (
        agrupados.groupby("evento")
        .agg(
            provincia=("provincia", lambda s: s.mode().iat[0]),
            focos=("frp", "size"),
            frp_total_mw=("frp", "sum"),
            frp_max_mw=("frp", "max"),
            latitud=("latitud", "mean"),
            longitud=("longitud", "mean"),
            inicio=("fecha", "min"),
            ultimo=("fecha", "max"),
            confianza_alta=("confianza", lambda s: int((s == "alta").sum())),
        )
        .reset_index()
    )
    eventos["dias_activo"] = (eventos["ultimo"] - eventos["inicio"]).dt.days + 1
    eventos["severidad"] = np.select(
        [
            (eventos["focos"] >= config.EVENTO_FOCOS_ALTO) | (eventos["frp_total_mw"] >= config.EVENTO_FRP_ALTO_MW),
            (eventos["focos"] >= 6) | (eventos["dias_activo"] >= 3),
        ],
        ["alta", "media"],
        default="baja",
    )
    return focos, eventos.sort_values("frp_total_mw", ascending=False).reset_index(drop=True)
