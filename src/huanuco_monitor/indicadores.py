"""Indicadores ambientales desde Sentinel-2 (vegetación) y Sentinel-5P (calidad del aire)."""
import io
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from PIL import Image

from . import cache, config, geo, referencias
from .copernicus import ClienteCopernicus

# Observación válida: clase SCL de vegetación (4) o suelo (5), sin nube según s2cloudless (CLM, que ya
# incluye un margen alrededor de las nubes) y con probabilidad de nube CLP (0-255) bajo el umbral.
# Se descartan sombras (2, 3), nubes (8, 9), cirros (10), saturados (1), sin clasificar (7), agua (6:
# barras y playas de río) y nieve (11).
_VALIDO = f"""function valido(s) {{
  return s.dataMask === 1 && (s.SCL === 4 || s.SCL === 5) && s.CLM === 0
    && s.CLP < {round(config.PROB_NUBE_MAX * 255)};
}}"""
_BANDAS_VALIDEZ = '"SCL", "CLM", "CLP", "dataMask"'

# NDVI por intervalo: mediana por píxel de todas las pasadas despejadas del intervalo (ORBIT). Con el
# mosaico simple solo se usa la escena más reciente de cada píxel y, en selva, casi siempre está nublada
# (Puerto Inca, 3 meses de prueba: 4-25 % de área observada frente a 40-46 % con la mediana).
EVAL_NDVI_ESTADISTICA = f"""//VERSION=3
function setup() {{
  return {{
    input: [{{ bands: ["B04", "B08", {_BANDAS_VALIDEZ}] }}],
    output: [{{ id: "ndvi", bands: 1, sampleType: "FLOAT32" }}, {{ id: "dataMask", bands: 1 }}],
    mosaicking: "ORBIT"
  }};
}}
{_VALIDO}
function evaluatePixel(muestras) {{
  var v = [];
  for (var i = 0; i < muestras.length; i++) {{
    var s = muestras[i];
    if (valido(s)) v.push((s.B08 - s.B04) / (s.B08 + s.B04 + 1e-6));
  }}
  if (v.length === 0) return {{ ndvi: [NaN], dataMask: [0] }};
  v.sort(function (a, b) {{ return a - b; }});
  var m = Math.floor(v.length / 2);
  return {{ ndvi: [v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2], dataMask: [1] }};
}}
"""

# Compara la mediana de NDVI de dos periodos por píxel (fusión de datos: "antes" y "despues").
# Codificación UINT8: 0 = fuera de la provincia, 255 = sin observación despejada, 1..201 = NDVI -1..1.
# Banda 3: 1 + mínimo de observaciones despejadas entre ambos periodos (0 = fuera de la provincia).
EVAL_CAMBIO = f"""//VERSION=3
function setup() {{
  return {{
    input: [
      {{ datasource: "antes", bands: ["B04", "B08", {_BANDAS_VALIDEZ}] }},
      {{ datasource: "despues", bands: ["B04", "B08", {_BANDAS_VALIDEZ}] }}
    ],
    output: {{ bands: 3, sampleType: "UINT8" }},
    mosaicking: "ORBIT"
  }};
}}
function mediana(v) {{
  if (v.length === 0) return NaN;
  v.sort(function (a, b) {{ return a - b; }});
  var m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}}
{_VALIDO}
function ndviValidos(muestras) {{
  var v = [];
  for (var i = 0; i < muestras.length; i++) {{
    var s = muestras[i];
    if (valido(s)) {{
      v.push((s.B08 - s.B04) / (s.B08 + s.B04 + 1e-6));
    }}
  }}
  return v;
}}
function codificar(x) {{
  if (isNaN(x)) return 255;
  return Math.round((Math.max(-1, Math.min(1, x)) + 1) * 100) + 1;
}}
function evaluatePixel(muestras) {{
  var a = ndviValidos(muestras.antes), d = ndviValidos(muestras.despues);
  return [codificar(mediana(a)), codificar(mediana(d)), Math.min(a.length, d.length, 254) + 1];
}}
"""

EVAL_COLOR_REAL = """//VERSION=3
function setup() {
  return { input: [{ bands: ["B02", "B03", "B04", "dataMask"] }], output: { bands: 4 } };
}
function evaluatePixel(s) {
  var g = 2.8;
  return [g * s.B04, g * s.B03, g * s.B02, s.dataMask];
}
"""

CONTAMINANTES = {
    # banda S5P: (nombre, unidad de visualización, factor desde mol/m²)
    "NO2": ("Dióxido de nitrógeno (NO₂)", "µmol/m²", 1e6),
    "CO": ("Monóxido de carbono (CO)", "mmol/m²", 1e3),
}


def _iso(d: date) -> str:
    return f"{d.isoformat()}T00:00:00Z"


def inicio_semana(d: date | None = None) -> date:
    """Lunes de la semana de `d`: fecha de corte de las consultas pesadas, estable durante 7 días para que
    la caché sirva toda la semana y no se gaste cuota de Copernicus a diario."""
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def _filas_estadistica(respuesta: dict, salida: str) -> list[dict]:
    filas = []
    for item in respuesta.get("data", []):
        if "error" in item:
            continue
        st = item["outputs"][salida]["bands"]["B0"]["stats"]
        n = st.get("sampleCount", 0)
        sin_dato = st.get("noDataCount", 0)
        validos = n - sin_dato
        filas.append({
            "desde": pd.Timestamp(item["interval"]["from"]).tz_localize(None),
            "hasta": pd.Timestamp(item["interval"]["to"]).tz_localize(None),
            "media": st.get("mean") if validos > 0 else np.nan,
            "desv": st.get("stDev") if validos > 0 else np.nan,
            "pct_valido": 100.0 * validos / n if n else 0.0,
        })
    df = pd.DataFrame(filas)
    if not df.empty:
        df["media"] = pd.to_numeric(df["media"], errors="coerce")
        df["desv"] = pd.to_numeric(df["desv"], errors="coerce")
    return df


# --------------------------------------------------------------------------- vegetación

def serie_ndvi(
    cliente: ClienteCopernicus,
    provincia: geo.Provincia,
    meses: int = config.NDVI_MESES,
    hasta: date | None = None,
    forzar: bool = False,
) -> pd.DataFrame:
    """NDVI medio mensual de la provincia (píxeles despejados de Sentinel-2 L2A, ~220 m)."""
    hasta = hasta or inicio_semana()
    desde = hasta - timedelta(days=30 * meses)
    payload = {
        "input": {
            "bounds": {"geometry": provincia.geojson, "properties": {"crs": config.CRS84}},
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {"maxCloudCoverage": 90}}],
        },
        "aggregation": {
            "timeRange": {"from": _iso(desde), "to": _iso(hasta)},
            "aggregationInterval": {"of": "P30D", "lastIntervalBehavior": "SHORTEN"},
            "resx": 0.002,
            "resy": 0.002,
            "evalscript": EVAL_NDVI_ESTADISTICA,
        },
    }
    clave = ("ndvi", EVAL_NDVI_ESTADISTICA, provincia.nombre, desde.isoformat(), hasta.isoformat())
    df = cache.memo(clave, config.TTL_NDVI,
                    lambda: _filas_estadistica(cliente.estadisticas(payload), "ndvi"), forzar)
    if not df.empty:
        # Meses con menos de 5 % de píxeles despejados no son representativos
        df.loc[df["pct_valido"] < 5, "media"] = np.nan
        df["provincia"] = provincia.nombre
    return df


def _sin_aislados(mascara: np.ndarray) -> np.ndarray:
    """Conserva solo píxeles con al menos MIN_VECINOS vecinos marcados (ventana 3×3)."""
    p = np.pad(mascara.astype(np.uint8), 1)
    h, w = mascara.shape
    vecinos = sum(p[1 + di:1 + di + h, 1 + dj:1 + dj + w]
                  for di in (-1, 0, 1) for dj in (-1, 0, 1) if di or dj)
    return mascara & (vecinos >= config.MIN_VECINOS)


@dataclass
class CambioCobertura:
    provincia: str
    bbox: tuple[float, float, float, float]
    antes: tuple[date, date]
    despues: tuple[date, date]
    ndvi_antes: np.ndarray = field(repr=False)
    ndvi_despues: np.ndarray = field(repr=False)
    dentro: np.ndarray = field(repr=False)
    observaciones: np.ndarray = field(repr=False, default=None)
    res_grados: float = 0.0
    ha_pixel: float = 0.0
    # Máscaras oficiales MINAM (None = no aplicadas): bosque al 2024 y «alguna vez bosque» (+ pérdida 2001-2024)
    bosque_ref: np.ndarray | None = field(repr=False, default=None)
    alguna_vez_bosque: np.ndarray | None = field(repr=False, default=None)
    referencia: str = "sin máscara de bosque"

    @property
    def comparable(self) -> np.ndarray:
        return (self.dentro & ~np.isnan(self.ndvi_antes) & ~np.isnan(self.ndvi_despues)
                & (self.observaciones >= config.MIN_OBSERVACIONES))

    @property
    def delta(self) -> np.ndarray:
        return self.ndvi_despues - self.ndvi_antes

    @property
    def perdida(self) -> np.ndarray:
        """Bosque previo con caída fuerte de NDVI: posible deforestación, tala o quema.

        Con máscara MINAM solo se evalúa el bosque oficial: descarta cultivos y pastos que tienen NDVI
        de bosque en algún momento del año y luego se cosechan o queman.
        """
        base = self.comparable if self.bosque_ref is None else self.comparable & self.bosque_ref
        with np.errstate(invalid="ignore"):
            return _sin_aislados(base & (self.ndvi_antes >= config.NDVI_BOSQUE)
                                 & (self.delta <= -config.CAIDA_NDVI_DEFORESTACION)
                                 & (self.ndvi_despues <= config.NDVI_MAX_TRAS_PERDIDA))

    @property
    def recuperacion(self) -> np.ndarray:
        """Área degradada cuyo NDVI aumenta: indicio de regeneración o restauración.

        Con máscara MINAM solo cuenta donde hubo bosque (bosque actual o perdido desde 2001): excluye
        cultivos, pastos y orillas de río que nunca fueron bosque.
        """
        base = self.comparable if self.alguna_vez_bosque is None else self.comparable & self.alguna_vez_bosque
        with np.errstate(invalid="ignore"):
            return _sin_aislados(base & (self.ndvi_antes <= config.NDVI_DEGRADADO)
                                 & (self.delta >= config.GANANCIA_NDVI_RECUPERACION))

    @property
    def cobertura_pct(self) -> float:
        """Porcentaje de la provincia con observación despejada en ambos periodos."""
        return 100.0 * self.comparable.sum() / max(self.dentro.sum(), 1)

    def hectareas(self, mascara: np.ndarray) -> float:
        return float(mascara.sum() * self.ha_pixel)

    def resumen(self) -> dict:
        zonas = self.focos_cambio(self.perdida)
        mayor = zonas.iloc[0] if len(zonas) else None
        return {
            "provincia": self.provincia,
            "periodo": (f"{self.antes[0]:%d/%m/%Y}–{self.antes[1]:%d/%m/%Y} vs. "
                        f"{self.despues[0]:%d/%m/%Y}–{self.despues[1]:%d/%m/%Y}"),
            "zona_latitud": round(float(mayor["latitud"]), 5) if mayor is not None else None,
            "zona_longitud": round(float(mayor["longitud"]), 5) if mayor is not None else None,
            "perdida_ha": round(self.hectareas(self.perdida), 1),
            "recuperacion_ha": round(self.hectareas(self.recuperacion), 1),
            "cobertura_pct": round(float(self.cobertura_pct), 1),
            "res_m": round(self.res_grados * 111_320),
            "mascara_bosque": self.referencia,
        }

    def focos_cambio(self, mascara: np.ndarray, bloque: int = 16, min_ha: float = 2.0) -> pd.DataFrame:
        """Agrupa píxeles marcados en celdas de `bloque`×`bloque` y devuelve sus centroides."""
        h, w = mascara.shape
        x0, y0, x1, y1 = self.bbox
        filas = []
        for i in range(0, h, bloque):
            for j in range(0, w, bloque):
                n = int(mascara[i:i + bloque, j:j + bloque].sum())
                ha = n * self.ha_pixel
                if ha < min_ha:
                    continue
                ii, jj = np.nonzero(mascara[i:i + bloque, j:j + bloque])
                filas.append({
                    "latitud": y1 - (i + ii.mean() + 0.5) * (y1 - y0) / h,
                    "longitud": x0 + (j + jj.mean() + 0.5) * (x1 - x0) / w,
                    "hectareas": round(ha, 1),
                })
        return pd.DataFrame(filas).sort_values("hectareas", ascending=False) if filas else pd.DataFrame(
            columns=["latitud", "longitud", "hectareas"])

    def imagen_rgba(self) -> np.ndarray:
        """Capa transparente: pérdida en rojo, recuperación en verde."""
        img = np.zeros((*self.dentro.shape, 4), dtype=np.uint8)
        img[self.perdida] = (208, 59, 59, 230)
        img[self.recuperacion] = (12, 163, 12, 210)
        return img


def periodos_por_defecto(dias: int = 90, hasta: date | None = None):
    """Periodo reciente vs. el mismo periodo del año anterior (evita confundir estacionalidad).

    Por defecto termina el lunes de la semana en curso (ver `inicio_semana`)."""
    hasta = hasta or inicio_semana()
    despues = (hasta - timedelta(days=dias), hasta)
    antes = (despues[0] - timedelta(days=365), despues[1] - timedelta(days=365))
    return antes, despues


def cambio_cobertura(
    cliente: ClienteCopernicus,
    provincia: geo.Provincia,
    antes: tuple[date, date] | None = None,
    despues: tuple[date, date] | None = None,
    max_px: int = 1400,
    forzar: bool = False,
    evalscript: str = EVAL_CAMBIO,
    mascara_bosque: bool = True,
    solo_cache: bool = False,
) -> CambioCobertura:
    """Detecta pérdida y recuperación de vegetación comparando medianas de NDVI por píxel.

    Si `mascara_bosque`, restringe el análisis al bosque oficial de MINAM; si el servicio no responde,
    el resultado se entrega sin máscara y `referencia` lo indica.
    """
    if antes is None or despues is None:
        antes, despues = periodos_por_defecto()
    x0, y0, x1, y1 = provincia.bbox
    res = max((x1 - x0) / max_px, (y1 - y0) / max_px, 0.0003)
    ancho, alto = int(np.ceil((x1 - x0) / res)), int(np.ceil((y1 - y0) / res))

    def filtro(periodo):
        return {"timeRange": {"from": _iso(periodo[0]), "to": _iso(periodo[1])}, "maxCloudCoverage": 80}

    payload = {
        "input": {
            "bounds": {"geometry": provincia.geojson, "properties": {"crs": config.CRS84}},
            "data": [
                {"type": "sentinel-2-l2a", "id": "antes", "dataFilter": filtro(antes)},
                {"type": "sentinel-2-l2a", "id": "despues", "dataFilter": filtro(despues)},
            ],
        },
        "output": {
            "width": ancho,
            "height": alto,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": evalscript,
    }
    clave = ("cambio", evalscript, provincia.nombre, antes, despues, ancho, alto)
    if solo_cache:  # análisis ya calculado (sin conexión a Copernicus), aunque sea de semanas anteriores
        png = cache.leer(clave)
        if png is None:
            raise LookupError(f"No hay un análisis guardado de {provincia.nombre} para ese periodo")
    else:
        png = cache.memo(clave, config.TTL_IMAGENES, lambda: cliente.procesar(payload), forzar)
    arr = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))

    def decodificar(banda):
        v = (banda.astype(float) - 1) / 100 - 1
        v[(banda == 0) | (banda == 255)] = np.nan
        return v

    dentro = arr[..., 2] > 0
    observaciones = arr[..., 2].astype(int) - 1
    # Con width/height, Sentinel Hub reparte el bbox exacto de la geometría entre los píxeles
    w_m = geo.tamano_pixel_m((x1 - x0) / ancho, (y0 + y1) / 2)[0]
    h_m = geo.tamano_pixel_m((y1 - y0) / alto, 0)[1]
    bosque = alguna_vez = None
    referencia = "sin máscara de bosque"
    if mascara_bosque:
        try:
            bosque, alguna_vez = referencias.mascara_bosque((x0, y0, x1, y1), ancho, alto)
            referencia = "MINAM: bosque húmedo 2024 + bosque seco 2021"
        except Exception as e:  # sin la máscara el análisis sigue siendo útil, pero se advierte
            referencia = f"máscara MINAM no disponible ({type(e).__name__})"
    return CambioCobertura(
        provincia=provincia.nombre,
        bbox=(x0, y0, x1, y1),
        antes=antes,
        despues=despues,
        ndvi_antes=decodificar(arr[..., 0]),
        ndvi_despues=decodificar(arr[..., 1]),
        dentro=dentro,
        observaciones=observaciones,
        res_grados=res,
        ha_pixel=w_m * h_m / 10_000,
        bosque_ref=bosque,
        alguna_vez_bosque=alguna_vez,
        referencia=referencia,
    )


def imagen_color_real(
    cliente: ClienteCopernicus, provincia: geo.Provincia, dias: int = 60, max_px: int = 1400,
    forzar: bool = False, solo_cache: bool = False,
) -> tuple[bytes, tuple[float, float, float, float]]:
    """Mosaico Sentinel-2 de color real con la escena menos nublada de los últimos `dias`."""
    hasta = inicio_semana()
    desde = hasta - timedelta(days=dias)
    x0, y0, x1, y1 = provincia.bbox
    res = max((x1 - x0) / max_px, (y1 - y0) / max_px, 0.0003)
    ancho, alto = int(np.ceil((x1 - x0) / res)), int(np.ceil((y1 - y0) / res))
    payload = {
        "input": {
            "bounds": {"geometry": provincia.geojson, "properties": {"crs": config.CRS84}},
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {"timeRange": {"from": _iso(desde), "to": _iso(hasta)},
                               "mosaickingOrder": "leastCC"},
            }],
        },
        "output": {"width": ancho, "height": alto,
                   "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
        "evalscript": EVAL_COLOR_REAL,
    }
    clave = ("color", provincia.nombre, desde.isoformat(), ancho, alto)
    if solo_cache:
        png = cache.leer(clave)
        if png is None:
            raise LookupError(f"La imagen de color real de {provincia.nombre} aún no está preparada")
    else:
        png = cache.memo(clave, config.TTL_IMAGENES, lambda: cliente.procesar(payload), forzar)
    return png, (x0, y0, x1, y1)


# Recorte compuesto sin nubes: mediana por píxel de las pasadas despejadas del periodo (misma máscara que
# el análisis), para ver lo mismo que "vio" el sistema. Color real o falso color SWIR (B12-B8A-B04: bosque
# verde oscuro, suelo desnudo o quema en tonos rosados/marrones).
_BANDAS_RECORTE = {"color": ("B04", "B03", "B02", 3.2), "falso": ("B12", "B8A", "B04", 2.5)}


def _eval_recorte(tipo: str) -> str:
    r, g, b, ganancia = _BANDAS_RECORTE[tipo]
    return f"""//VERSION=3
function setup() {{
  return {{
    input: [{{ bands: ["{r}", "{g}", "{b}", {_BANDAS_VALIDEZ}] }}],
    output: {{ bands: 3, sampleType: "UINT8" }},
    mosaicking: "ORBIT"
  }};
}}
{_VALIDO}
function med(v) {{
  v.sort(function (a, b) {{ return a - b; }});
  var m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}}
function evaluatePixel(muestras) {{
  var r = [], g = [], b = [];
  for (var i = 0; i < muestras.length; i++) {{
    var s = muestras[i];
    if (valido(s)) {{ r.push(s.{r}); g.push(s.{g}); b.push(s.{b}); }}
  }}
  if (r.length === 0) return [255, 255, 255];  // sin observación despejada: blanco
  return [med(r) * {ganancia} * 255, med(g) * {ganancia} * 255, med(b) * {ganancia} * 255];
}}
"""


def recorte_compuesto(
    cliente: ClienteCopernicus, lon: float, lat: float, periodo: tuple[date, date], tipo: str = "color",
    semiancho: float = 0.006, px: int = 220,
) -> Image.Image:
    """Recorte Sentinel-2 sin nubes (mediana del periodo) centrado en (lon, lat); blanco = nunca despejado."""
    bbox = [lon - semiancho, lat - semiancho, lon + semiancho, lat + semiancho]
    evalscript = _eval_recorte(tipo)
    payload = {
        "input": {
            "bounds": {"bbox": bbox, "properties": {"crs": config.CRS84}},
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {
                "timeRange": {"from": _iso(periodo[0]), "to": _iso(periodo[1])}, "maxCloudCoverage": 80}}],
        },
        "output": {"width": px, "height": px, "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
        "evalscript": evalscript,
    }
    png = cache.memo(("recorte", evalscript, [round(v, 6) for v in bbox], periodo, px), 30 * 86400,
                     lambda: cliente.procesar(payload))
    return Image.open(io.BytesIO(png)).convert("RGB")


# --------------------------------------------------------------------------- calidad del aire

def serie_aire(
    cliente: ClienteCopernicus,
    provincia: geo.Provincia,
    contaminante: str,
    dias: int = 120,
    hasta: date | None = None,
    forzar: bool = False,
) -> pd.DataFrame:
    """Columna troposférica/total semanal de NO₂ o CO (Sentinel-5P TROPOMI) en la provincia."""
    if contaminante not in CONTAMINANTES:
        raise ValueError(f"Contaminante no soportado: {contaminante}")
    hasta = hasta or date.today()
    desde = hasta - timedelta(days=dias)
    evalscript = f"""//VERSION=3
function setup() {{
  return {{
    input: [{{ bands: ["{contaminante}", "dataMask"] }}],
    output: [{{ id: "valor", bands: 1, sampleType: "FLOAT32" }}, {{ id: "dataMask", bands: 1 }}]
  }};
}}
function evaluatePixel(s) {{ return {{ valor: [s.{contaminante}], dataMask: [s.dataMask] }}; }}
"""
    payload = {
        "input": {
            "bounds": {"geometry": provincia.geojson, "properties": {"crs": config.CRS84}},
            "data": [{"type": "sentinel-5p-l2", "dataFilter": {"timeliness": "OFFL"}}],
        },
        "aggregation": {
            "timeRange": {"from": _iso(desde), "to": _iso(hasta)},
            "aggregationInterval": {"of": "P7D", "lastIntervalBehavior": "SHORTEN"},
            "resx": 0.05,
            "resy": 0.05,
            "evalscript": evalscript,
        },
    }
    clave = ("aire", contaminante, provincia.nombre, desde.isoformat(), hasta.isoformat())
    df = cache.memo(clave, config.TTL_ESTADISTICAS,
                    lambda: _filas_estadistica(cliente.estadisticas(payload), "valor"), forzar)
    if not df.empty:
        # Semanas con muy pocos píxeles válidos (nubes, calidad baja) dan promedios ruidosos
        df.loc[df["pct_valido"] < 20, "media"] = np.nan
        factor = CONTAMINANTES[contaminante][2]
        df["media"] = df["media"] * factor
        df["desv"] = df["desv"] * factor
        df["provincia"] = provincia.nombre
        df["contaminante"] = contaminante
    return df


def anomalia_z(serie: pd.Series, ventana_min: int = 6) -> float:
    """Puntaje z del último valor válido respecto de la línea base previa de la misma serie."""
    s = serie.dropna()
    if len(s) < ventana_min + 1:
        return float("nan")
    base, ultimo = s.iloc[:-1], s.iloc[-1]
    desv = base.std(ddof=1)
    return float((ultimo - base.mean()) / desv) if desv > 0 else float("nan")
