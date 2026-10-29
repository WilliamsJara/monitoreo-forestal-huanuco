"""Orquestador: descarga los indicadores de las 11 provincias y genera las alertas.

Cada fuente (NASA FIRMS, Sentinel-2 NDVI, Sentinel-5P aire, Sentinel-2 cobertura) se consulta por
separado. Si una falla por completo, se usan sus últimos datos buenos (respaldo en disco) y se indica su
fecha, sin afectar a las demás.
"""
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from . import alertas as reglas
from . import config, firms, geo, indicadores
from .copernicus import ClienteCopernicus

FUENTES = {"firms": "NASA FIRMS (incendios)", "ndvi": "Sentinel-2 (vegetación)",
           "aire": "Sentinel-5P (aire)", "cobertura": "Sentinel-2 (cobertura)"}


@dataclass
class EstadoFuente:
    actualizado: datetime | None = None
    respaldo: bool = False          # True = datos de una consulta anterior (la actual falló)
    errores: list[str] = field(default_factory=list)

    @property
    def descripcion(self) -> str:
        if self.actualizado is None:
            return "sin datos"
        texto = f"{self.actualizado:%d/%m/%Y %H:%M}"
        return texto + " (respaldo: la consulta actual falló)" if self.respaldo else texto


@dataclass
class Reporte:
    generado: datetime
    focos: pd.DataFrame
    eventos: pd.DataFrame
    ndvi: pd.DataFrame
    aire: pd.DataFrame
    anomalias_aire: pd.DataFrame
    cambios: dict[str, indicadores.CambioCobertura] = field(default_factory=dict)
    alertas: list[reglas.Alerta] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    fuentes: dict[str, EstadoFuente] = field(default_factory=dict)

    @property
    def tabla_alertas(self) -> pd.DataFrame:
        return reglas.tabla(self.alertas)

    @property
    def niveles(self) -> dict[str, str]:
        return reglas.nivel_por_provincia(self.alertas, list(geo.provincias()))


def _en_paralelo(funcion, provincias, errores, etiqueta, hilos=6):
    def seguro(p):
        try:
            return funcion(p)
        except Exception as e:  # una provincia que falla no detiene el resto
            errores.append(f"{etiqueta} · {p.nombre}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=hilos) as ex:
        return [r for r in ex.map(seguro, provincias) if r is not None]


def _con_respaldo(nombre: str, calcular, vacio, etiqueta: str = "") -> tuple[object, EstadoFuente]:
    """Ejecuta `calcular() -> (datos, errores, completo)`; guarda el resultado completo como respaldo y, si
    la consulta falla del todo, devuelve el último respaldo (o `vacio()` si nunca hubo uno)."""
    ruta = config.CACHE_DIR / f"respaldo_{nombre}.pkl"
    try:
        datos, errores, completo = calcular()
    except Exception as e:
        datos, errores, completo = None, [f"{etiqueta or FUENTES[nombre]}: {e}"], False
    if datos is not None and completo:
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ahora = datetime.now()
        with ruta.open("wb") as f:
            pickle.dump((ahora, datos), f)
        return datos, EstadoFuente(ahora, False, errores)
    if datos is not None and not errores:
        return datos, EstadoFuente(datetime.now(), False, errores)
    if ruta.exists() and (datos is None or _vacio(datos)):
        try:
            with ruta.open("rb") as f:
                fecha, guardado = pickle.load(f)
            return guardado, EstadoFuente(fecha, True, errores)
        except Exception:  # respaldo ilegible (otra versión de librerías): se sigue sin él
            pass
    return (datos if datos is not None else vacio()), EstadoFuente(
        datetime.now() if datos is not None else None, False, errores)


def _vacio(datos) -> bool:
    primero = datos[0] if isinstance(datos, tuple) else datos
    return isinstance(primero, (pd.DataFrame, dict, list)) and len(primero) == 0


# --------------------------------------------------------------------------- fuentes

def datos_firms(dias_focos: int = 7, fuentes_firms: list[str] | None = None, forzar: bool = False):
    """(focos, eventos), estado. Sin focos es un resultado válido (no se reemplaza por el respaldo)."""
    def calcular():
        focos = firms.focos_de_calor(dias_focos, fuentes_firms, forzar)
        return firms.agrupar_eventos(focos), [], True

    def vacio():
        return firms.agrupar_eventos(pd.DataFrame(columns=firms.COLUMNAS + ["provincia"]))

    clave = f"firms_{dias_focos}_{'-'.join(sorted(fuentes_firms or config.FIRMS_FUENTES))}"
    return _con_respaldo(clave, calcular, vacio, FUENTES["firms"])


def datos_ndvi(cliente: ClienteCopernicus | None = None, forzar: bool = False):
    cliente = cliente or ClienteCopernicus()
    provs = list(geo.provincias().values())

    def calcular():
        errores = []
        # La mediana por píxel de 14 meses es pesada: con 6 consultas simultáneas Copernicus responde 500
        res = _en_paralelo(lambda p: indicadores.serie_ndvi(cliente, p, forzar=forzar), provs, errores, "NDVI",
                           hilos=3)
        return (pd.concat(res, ignore_index=True) if res else pd.DataFrame()), errores, not errores

    return _con_respaldo("ndvi", calcular, pd.DataFrame)


def datos_aire(cliente: ClienteCopernicus | None = None, forzar: bool = False):
    """(series, anomalías), estado."""
    cliente = cliente or ClienteCopernicus()
    provs = list(geo.provincias().values())
    columnas = ["provincia", "contaminante", "unidad", "z", "ultimo", "fecha", "pct_valido"]

    def calcular():
        errores, series, filas = [], [], []
        for c, (_, unidad, _) in indicadores.CONTAMINANTES.items():
            res = _en_paralelo(lambda p, c=c: indicadores.serie_aire(cliente, p, c, forzar=forzar),
                               provs, errores, c)
            for df in res:
                if df.empty:
                    continue
                series.append(df)
                d = df.sort_values("desde")
                validos = d.dropna(subset=["media"])
                ultimo = validos.iloc[-1] if len(validos) else None
                filas.append({
                    "provincia": df["provincia"].iat[0], "contaminante": c, "unidad": unidad,
                    "z": indicadores.anomalia_z(d["media"]),
                    "ultimo": ultimo["media"] if ultimo is not None else float("nan"),
                    "fecha": ultimo["desde"] if ultimo is not None else pd.NaT,
                    "pct_valido": ultimo["pct_valido"] if ultimo is not None else float("nan"),
                })
        aire = pd.concat(series, ignore_index=True) if series else pd.DataFrame()
        return (aire, pd.DataFrame(filas, columns=columnas)), errores, not errores

    return _con_respaldo("aire", calcular, lambda: (pd.DataFrame(), pd.DataFrame(columns=columnas)))


def datos_cobertura(cliente: ClienteCopernicus | None = None, forzar: bool = False):
    """Sin respaldo propio: pesa cientos de MB y sus imágenes ya quedan en la caché de 24 h."""
    cliente = cliente or ClienteCopernicus()
    errores = []
    res = _en_paralelo(lambda p: indicadores.cambio_cobertura(cliente, p, forzar=forzar),
                       list(geo.provincias().values()), errores, "Cobertura")
    return {c.provincia: c for c in res}, EstadoFuente(datetime.now() if res else None, False, errores)


# --------------------------------------------------------------------------- reporte

def precalentar_tablero(cambios: dict, cliente: ClienteCopernicus | None = None) -> list[str]:
    """Deja en caché lo que la sección de deforestación pide al abrir cada provincia: imagen de fondo en
    color real, alertas MINAM y las tres imágenes de evidencia de la zona de pérdida más grande. Así el
    tablero no tiene que conectarse a internet en la semana. Devuelve los errores (no detiene la corrida)."""
    from . import referencias

    cliente = cliente or ClienteCopernicus()
    provincias = geo.provincias()
    errores = []
    for nombre, cc in cambios.items():
        try:
            indicadores.imagen_color_real(cliente, provincias[nombre])
            args = (cc.bbox, *cc.dentro.shape[::-1])
            referencias.fraccion("alertas_2026", *args)
            referencias.fraccion("perdida_2025", *args)
            zonas = cc.focos_cambio(cc.perdida)
            if len(zonas):
                z = zonas.iloc[0]
                for periodo, tipo in ((cc.antes, "color"), (cc.despues, "color"), (cc.despues, "falso")):
                    indicadores.recorte_compuesto(cliente, float(z.longitud), float(z.latitud), periodo, tipo)
        except Exception as e:
            errores.append(f"Preparación del tablero · {nombre}: {e}")
    return errores


def componer(firms_res, ndvi_res, aire_res, cobertura_res=None) -> Reporte:
    """Arma el reporte y las alertas a partir de los resultados de cada fuente (actualizados por separado)."""
    (focos, eventos), e_firms = firms_res
    ndvi, e_ndvi = ndvi_res
    (aire, anomalias), e_aire = aire_res
    cambios, e_cob = cobertura_res if cobertura_res else ({}, None)
    estados = {"firms": e_firms, "ndvi": e_ndvi, "aire": e_aire}
    if e_cob is not None:
        estados["cobertura"] = e_cob
    lista = (
        reglas.alertas_incendio(focos, eventos)
        + reglas.alertas_deforestacion([c.resumen() for c in cambios.values()])
        + reglas.alertas_vegetacion(ndvi)
        + reglas.alertas_aire(anomalias)
    )
    errores = [e for est in estados.values() for e in est.errores]
    errores += [f"{FUENTES[n]}: se usan datos del {est.actualizado:%d/%m/%Y %H:%M}"
                for n, est in estados.items() if est.respaldo]
    return Reporte(datetime.now(), focos, eventos, ndvi, aire, anomalias, cambios, lista, errores, estados)


def _leer_csv(ruta, fechas=()) -> pd.DataFrame:
    try:
        return pd.read_csv(ruta, parse_dates=list(fechas))
    except (FileNotFoundError, pd.errors.EmptyDataError, ValueError):
        return pd.DataFrame()


def reporte_guardado(carpeta) -> Reporte:
    """Reporte armado desde una corrida guardada en `salidas/` (sin consultar satélites ni gastar cuota).

    Permite abrir el tablero en segundos y hacer demostraciones sin conexión a Copernicus. No incluye las
    imágenes del cambio de cobertura (se calculan en su sección), pero sí sus alertas con evidencia.
    """
    import json
    from pathlib import Path

    carpeta = Path(carpeta)
    resumen = json.loads((carpeta / "resumen.json").read_text(encoding="utf-8"))
    generado = datetime.fromisoformat(resumen["generado"])

    focos = _leer_csv(carpeta / "focos_calor.csv", ["fecha"])
    if focos.empty:
        focos = pd.DataFrame(columns=firms.COLUMNAS + ["provincia"])
    focos, eventos = firms.agrupar_eventos(focos)
    ndvi = _leer_csv(carpeta / "ndvi_mensual.csv", ["desde", "hasta"])
    aire = _leer_csv(carpeta / "aire_semanal.csv", ["desde", "hasta"])
    filas = []
    if not aire.empty:
        for (prov, c), d in aire.groupby(["provincia", "contaminante"]):
            d = d.sort_values("desde")
            validos = d.dropna(subset=["media"])
            ultimo = validos.iloc[-1] if len(validos) else None
            filas.append({"provincia": prov, "contaminante": c, "unidad": indicadores.CONTAMINANTES[c][1],
                          "z": indicadores.anomalia_z(d["media"]),
                          "ultimo": ultimo["media"] if ultimo is not None else float("nan"),
                          "fecha": ultimo["desde"] if ultimo is not None else pd.NaT,
                          "pct_valido": ultimo["pct_valido"] if ultimo is not None else float("nan")})
    anomalias = pd.DataFrame(filas, columns=["provincia", "contaminante", "unidad", "z", "ultimo", "fecha",
                                             "pct_valido"])

    tabla = _leer_csv(carpeta / "alertas.csv")
    lista = []
    for r in tabla.to_dict("records"):
        r = {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in r.items()}
        for k in ("fuente", "fecha", "indicador", "calidad"):
            r[k] = r.get(k) or ""
        lista.append(reglas.Alerta(**{k: r.get(k) for k in reglas.COLUMNAS}))

    estados = {}
    for n, texto in resumen.get("fuentes", {}).items():
        try:
            fecha = datetime.strptime(texto[:16], "%d/%m/%Y %H:%M")
        except ValueError:
            fecha = None
        estados[n] = EstadoFuente(fecha, "respaldo" in texto, [])
    return Reporte(generado, focos, eventos, ndvi, aire, anomalias, {}, lista,
                   list(resumen.get("errores", [])), estados)


def generar_reporte(
    dias_focos: int = 7,
    fuentes_firms: list[str] | None = None,
    con_cambio_cobertura: bool = False,
    forzar: bool = False,
    cliente: ClienteCopernicus | None = None,
) -> Reporte:
    cliente = cliente or ClienteCopernicus()
    return componer(
        datos_firms(dias_focos, fuentes_firms, forzar),
        datos_ndvi(cliente, forzar),
        datos_aire(cliente, forzar),
        datos_cobertura(cliente, forzar) if con_cambio_cobertura else None,
    )
