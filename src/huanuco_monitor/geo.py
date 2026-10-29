"""Límites provinciales de Huánuco y utilidades geoespaciales."""
import json
import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import shapely
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from .config import PROVINCIAS_GEOJSON


@dataclass(frozen=True)
class Provincia:
    nombre: str
    geometria: shapely.Geometry

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return tuple(self.geometria.bounds)

    @property
    def geojson(self) -> dict:
        return mapping(self.geometria)

    @property
    def area_km2(self) -> float:
        return area_km2(self.geometria)


@lru_cache(maxsize=1)
def provincias() -> dict[str, Provincia]:
    datos = json.loads(PROVINCIAS_GEOJSON.read_text(encoding="utf-8"))
    resultado = {}
    for f in datos["features"]:
        nombre = f["properties"]["provincia"]
        geom = shapely.make_valid(shape(f["geometry"]))
        resultado[nombre] = Provincia(nombre, geom)
    return dict(sorted(resultado.items()))


@lru_cache(maxsize=1)
def region() -> shapely.Geometry:
    return unary_union([p.geometria for p in provincias().values()])


def bbox_region(margen: float = 0.02) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = region().bounds
    return (x0 - margen, y0 - margen, x1 + margen, y1 + margen)


def asignar_provincia(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Devuelve el nombre de la provincia que contiene cada punto (o None si está fuera)."""
    salida = np.full(len(lon), None, dtype=object)
    for p in provincias().values():
        dentro = shapely.contains_xy(p.geometria, lon, lat)
        salida[dentro & (salida == None)] = p.nombre  # noqa: E711
    return salida


def area_km2(geom: shapely.Geometry) -> float:
    """Área aproximada en km² (proyección equirectangular local; error <1% a esta escala)."""
    lat0 = math.radians(geom.centroid.y)
    escala = shapely.transform(
        geom, lambda c: np.column_stack([c[:, 0] * 111.320 * math.cos(lat0), c[:, 1] * 110.574])
    )
    return escala.area


def tamano_pixel_m(res_grados: float, lat: float) -> tuple[float, float]:
    return res_grados * 111_320 * math.cos(math.radians(lat)), res_grados * 110_574
