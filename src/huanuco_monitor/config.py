"""Configuración central: credenciales, rutas, endpoints y umbrales de alerta."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache"
SALIDAS_DIR = ROOT / "salidas"
BASE_DATOS = SALIDAS_DIR / "monitoreo.sqlite"   # historial de corridas y alertas
RESPALDOS_DIR = ROOT / "respaldos"
PROVINCIAS_GEOJSON = DATA_DIR / "provincias_huanuco.geojson"

# --- Credenciales (se leen de .env, nunca se escriben en el código) ---
SH_CLIENT_ID = os.getenv("SH_CLIENT_ID", "")
SH_CLIENT_SECRET = os.getenv("SH_CLIENT_SECRET", "")
FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "")

# --- Copernicus Data Space Ecosystem (Sentinel Hub) ---
CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
CDSE_STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
CDSE_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

# --- Geobosques (MINAM / PNCB): bosque, pérdida histórica y alertas tempranas oficiales ---
GEOBOSQUES_URL = "https://gis.bosques.gob.pe/server/rest/services/Interoperabilidad"

# --- NASA FIRMS ---
FIRMS_AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_FUENTES = {
    "VIIRS_SNPP_NRT": "VIIRS S-NPP (375 m)",
    "VIIRS_NOAA20_NRT": "VIIRS NOAA-20 (375 m)",
    "VIIRS_NOAA21_NRT": "VIIRS NOAA-21 (375 m)",
    "MODIS_NRT": "MODIS Terra/Aqua (1 km)",
}

# --- Umbrales de análisis ---
NDVI_BOSQUE = 0.60            # NDVI mínimo para considerar un píxel como bosque antes del cambio
CAIDA_NDVI_DEFORESTACION = 0.25  # caída de NDVI que marca posible deforestación/tala
NDVI_DEGRADADO = 0.45         # NDVI máximo de un área degradada candidata a recuperación
GANANCIA_NDVI_RECUPERACION = 0.15
NDVI_MAX_TRAS_PERDIDA = 0.55  # tras la pérdida el píxel queda sin dosel (suelo, quema, rebrote incipiente)
                              # 0,45 hasta el 24/10/2026; 0,55 detecta claros con rebrote (validar_minam.py)
MIN_OBSERVACIONES = 2         # observaciones despejadas mínimas por periodo y píxel
MIN_VECINOS = 3               # vecinos marcados (3×3) para descartar píxeles aislados
PROB_NUBE_MAX = 0.20          # probabilidad de nube s2cloudless máxima para aceptar una observación
NDVI_MESES = 14               # serie NDVI: 12 meses + margen para comparar con el mismo mes del año anterior

# Clustering de focos de calor (DBSCAN): focos a menos de EPS_KM forman un mismo evento
DBSCAN_EPS_KM = 1.5
DBSCAN_MIN_FOCOS = 3

# Niveles de alerta por provincia
INCENDIO_FOCOS_MEDIO = 5
INCENDIO_FOCOS_ALTO = 25
INCENDIO_FRP_ALTO_MW = 500.0   # FRP acumulado en la provincia
EVENTO_FOCOS_ALTO = 15
EVENTO_FRP_ALTO_MW = 300.0     # FRP acumulado de un evento
DEFORESTACION_HA_MEDIO = 10.0
DEFORESTACION_HA_ALTO = 50.0
CAIDA_NDVI_MEDIO = 0.10        # caída del NDVI provincial frente al mismo periodo del año anterior
CAIDA_NDVI_ALTO = 0.18
AIRE_Z_MEDIO = 2.0
AIRE_Z_ALTO = 3.0

# Tiempos de vida de la caché (segundos)
TTL_FIRMS = 3 * 3600
TTL_ESTADISTICAS = 24 * 3600   # aire (Sentinel-5P, consulta liviana): diario
# NDVI y cambio de cobertura son las consultas que más cuota de Copernicus gastan: sus periodos terminan el
# lunes de la semana en curso y se recalculan una vez por semana (la cuota mensual gratuita es limitada).
TTL_NDVI = 7 * 86400
TTL_IMAGENES = 7 * 86400


def credenciales_faltantes() -> list[str]:
    faltan = []
    if not SH_CLIENT_ID or not SH_CLIENT_SECRET:
        faltan.append("SH_CLIENT_ID / SH_CLIENT_SECRET")
    if not FIRMS_MAP_KEY:
        faltan.append("FIRMS_MAP_KEY")
    return faltan
