"""Capas oficiales de MINAM / PNCB (Geobosques): bosque, pérdida histórica y alertas tempranas.

Se leen de los servicios interoperables de https://gis.bosques.gob.pe (ArcGIS MapServer, acceso libre)
y se proyectan sobre la misma cuadrícula de píxeles que el análisis de cambio de cobertura.
"""
import io
import math

import numpy as np
import requests
from PIL import Image

from . import cache, config

# nombre: (servicio, id de capa, tiempo de vida de la caché)
CAPAS = {
    "bosque_humedo": ("bosque_humedo_2024", 1, 30 * 86400),             # bosque húmedo amazónico al 2024
    "perdida_historica": ("bosque_humedo_2024", 2, 30 * 86400),         # pérdida de bosque 2001-2024
    "bosque_seco": ("bosque_seco_2021", 1, 30 * 86400),                 # bosque estacionalmente seco al 2021
    "perdida_2025": ("perdida_bosque_humedo_2001_2025", 25, 30 * 86400),  # pérdida antrópica 2025
    "alertas_2026": ("alertas_tempranas_2026", 0, 86400),               # alertas tempranas acumuladas 2026
}
MAX_LADO = 4000       # el servidor acepta imágenes de hasta 4096 px por lado
RES_ORIGEN_M = 30     # las capas de Geobosques derivan de Landsat (30 m)


def _exportar(servicio: str, capa: int, bbox: tuple, ancho: int, alto: int) -> np.ndarray:
    """Pide la capa renderizada (PNG transparente) y devuelve True donde hay dato."""
    x0, y0, x1, y1 = bbox
    r = requests.get(
        f"{config.GEOBOSQUES_URL}/{servicio}/MapServer/export",
        params={"bbox": f"{x0},{y0},{x1},{y1}", "bboxSR": 4326, "imageSR": 4326, "size": f"{ancho},{alto}",
                "layers": f"show:{capa}", "format": "png32", "transparent": "true", "f": "image"},
        timeout=180,
    )
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError(f"Geobosques {servicio}/{capa} ({r.status_code}): {r.text[:200]}")
    img = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))
    if img.shape[:2] != (alto, ancho):
        raise RuntimeError(f"Geobosques {servicio}: tamaño inesperado {img.shape[:2]} (pedido {alto}×{ancho})")
    return img[..., 3] > 0


def _calcular_fraccion(servicio, capa, bbox, ancho, alto, factor) -> np.ndarray:
    x0, y0, x1, y1 = bbox
    W, H = ancho * factor, alto * factor
    paso = (MAX_LADO // factor) * factor  # bloques alineados con los píxeles de destino
    sub = np.zeros((H, W), dtype=bool)
    for f0 in range(0, H, paso):
        for c0 in range(0, W, paso):
            f1, c1 = min(f0 + paso, H), min(c0 + paso, W)
            caja = (x0 + c0 * (x1 - x0) / W, y1 - f1 * (y1 - y0) / H,
                    x0 + c1 * (x1 - x0) / W, y1 - f0 * (y1 - y0) / H)
            sub[f0:f1, c0:c1] = _exportar(servicio, capa, caja, c1 - c0, f1 - f0)
    frac = sub.reshape(alto, factor, ancho, factor).mean(axis=(1, 3))
    return np.round(frac * 255).astype(np.uint8)  # compacto en la caché


def fraccion(nombre: str, bbox: tuple, ancho: int, alto: int, forzar: bool = False) -> np.ndarray:
    """Fracción (0-1) de cada píxel de la cuadrícula cubierta por la capa oficial `nombre`.

    La capa se pide con submuestreo cercano a 30 m y se promedia: así las alertas pequeñas no se pierden
    al pasar a píxeles más grandes.
    """
    servicio, capa, ttl = CAPAS[nombre]
    x0, y0, x1, y1 = bbox
    px_m = (x1 - x0) / ancho * 111_320 * math.cos(math.radians((y0 + y1) / 2))
    factor = int(min(max(round(px_m / RES_ORIGEN_M), 1), 4))
    clave = ("minam", servicio, capa, tuple(round(v, 6) for v in bbox), ancho, alto, factor)
    v = cache.memo(clave, ttl, lambda: _calcular_fraccion(servicio, capa, bbox, ancho, alto, factor), forzar)
    return v.astype(float) / 255


def mascara_bosque(bbox: tuple, ancho: int, alto: int) -> tuple[np.ndarray, np.ndarray]:
    """(bosque oficial, alguna vez bosque) en la cuadrícula.

    - bosque: bosque húmedo al 2024 o bosque seco al 2021 (≥ 50 % del píxel).
    - alguna vez bosque: lo anterior más la pérdida 2001-2024; es donde tiene sentido hablar de
      recuperación del bosque (excluye pastos, cultivos y ríos que nunca fueron bosque).
    """
    humedo = fraccion("bosque_humedo", bbox, ancho, alto)
    seco = fraccion("bosque_seco", bbox, ancho, alto)
    historica = fraccion("perdida_historica", bbox, ancho, alto)
    bosque = np.maximum(humedo, seco) >= 0.5
    return bosque, bosque | (historica >= 0.5)
