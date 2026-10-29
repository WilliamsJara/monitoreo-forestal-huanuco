"""Almacenamiento permanente en SQLite: corridas, estado de cada fuente, alertas con su evidencia y zonas
de pérdida. Permite consultar la evolución de las alertas en el tiempo y sobrevive a la caché.

Los resultados grandes (imágenes, series completas) siguen en archivos de `salidas/`; aquí solo van los
metadatos y las alertas.
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path, PurePosixPath, PureWindowsPath

import pandas as pd

from . import alertas as reglas
from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS corridas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generado TEXT NOT NULL,          -- ISO 8601
    origen TEXT NOT NULL,            -- actualizar.py, tablero…
    dias_focos INTEGER,
    con_cobertura INTEGER,
    carpeta TEXT,                    -- carpeta de salidas/ con los CSV de la corrida
    parametros TEXT                  -- umbrales vigentes (JSON)
);
CREATE TABLE IF NOT EXISTS estado_fuentes (
    corrida_id INTEGER REFERENCES corridas(id),
    fuente TEXT, actualizado TEXT, respaldo INTEGER, errores TEXT
);
CREATE TABLE IF NOT EXISTS alertas (
    corrida_id INTEGER REFERENCES corridas(id),
    provincia TEXT, tipo TEXT, nivel TEXT, mensaje TEXT, valor REAL,
    fuente TEXT, fecha TEXT, indicador TEXT, calidad TEXT, latitud REAL, longitud REAL
);
CREATE TABLE IF NOT EXISTS cobertura (
    corrida_id INTEGER REFERENCES corridas(id),
    provincia TEXT, periodo TEXT, perdida_ha REAL, recuperacion_ha REAL, cobertura_pct REAL, mascara_bosque TEXT
);
CREATE TABLE IF NOT EXISTS zonas_perdida (
    corrida_id INTEGER REFERENCES corridas(id),
    provincia TEXT, latitud REAL, longitud REAL, hectareas REAL
);
CREATE INDEX IF NOT EXISTS i_alertas_corrida ON alertas(corrida_id);
"""

PARAMETROS = ["NDVI_BOSQUE", "CAIDA_NDVI_DEFORESTACION", "NDVI_MAX_TRAS_PERDIDA", "MIN_OBSERVACIONES",
              "MIN_VECINOS", "PROB_NUBE_MAX", "CAIDA_NDVI_MEDIO", "CAIDA_NDVI_ALTO", "AIRE_Z_MEDIO", "AIRE_Z_ALTO"]


def conectar() -> sqlite3.Connection:
    config.BASE_DATOS.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.BASE_DATOS)
    con.executescript(ESQUEMA)
    return con


def guardar(rep, origen: str, dias_focos: int | None = None, carpeta: str = "") -> int:
    """Guarda un `monitor.Reporte`; devuelve el id de la corrida."""
    with closing(conectar()) as con, con:
        cur = con.execute(
            "INSERT INTO corridas (generado, origen, dias_focos, con_cobertura, carpeta, parametros) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rep.generado.isoformat(timespec="seconds"), origen, dias_focos, int(bool(rep.cambios)), carpeta,
             json.dumps({k: getattr(config, k) for k in PARAMETROS})))
        cid = cur.lastrowid
        con.executemany("INSERT INTO estado_fuentes VALUES (?, ?, ?, ?, ?)", [
            (cid, n, e.actualizado.isoformat(timespec="seconds") if e.actualizado else None, int(e.respaldo),
             "\n".join(e.errores)) for n, e in rep.fuentes.items()])
        con.executemany(f"INSERT INTO alertas VALUES ({', '.join('?' * (len(reglas.COLUMNAS) + 1))})",
                        [(cid, *[a.dict()[c] for c in reglas.COLUMNAS]) for a in rep.alertas])
        for c in rep.cambios.values():
            r = c.resumen()
            con.execute("INSERT INTO cobertura VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (cid, r["provincia"], r["periodo"], r["perdida_ha"], r["recuperacion_ha"],
                         r["cobertura_pct"], r["mascara_bosque"]))
            z = c.focos_cambio(c.perdida, min_ha=1.0)
            con.executemany("INSERT INTO zonas_perdida VALUES (?, ?, ?, ?, ?)",
                            [(cid, c.provincia, float(f.latitud), float(f.longitud), float(f.hectareas))
                             for f in z.itertuples()])
    return cid


def historial_alertas() -> pd.DataFrame:
    """Número de alertas por corrida, tipo y nivel (para ver la evolución en el tiempo)."""
    if not config.BASE_DATOS.exists():
        return pd.DataFrame(columns=["generado", "tipo", "nivel", "alertas"])
    with closing(conectar()) as con:
        return pd.read_sql_query(
            "SELECT c.generado, a.tipo, a.nivel, COUNT(*) AS alertas FROM corridas c "
            "JOIN alertas a ON a.corrida_id = c.id GROUP BY c.id, a.tipo, a.nivel ORDER BY c.generado",
            con, parse_dates=["generado"])


def ultima_corrida() -> dict | None:
    if not config.BASE_DATOS.exists():
        return None
    with closing(conectar()) as con:
        fila = con.execute("SELECT id, generado, origen, carpeta, dias_focos FROM corridas "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    if not fila:
        return None
    corrida = dict(zip(["id", "generado", "origen", "carpeta", "dias_focos"], fila))
    corrida["carpeta"] = str(carpeta_local(corrida["carpeta"]))
    return corrida


def carpeta_local(ruta: str | None) -> Path:
    """La carpeta de una corrida en este equipo. Las rutas guardadas pueden venir de otro sistema (p. ej. de
    Windows a un servidor Linux): si no existe tal cual, se busca por su nombre dentro de `salidas/`."""
    if not ruta:
        return config.SALIDAS_DIR / "_sin_carpeta"
    directa = Path(ruta)
    if directa.exists():
        return directa
    nombre = PureWindowsPath(ruta).name if "\\" in ruta else PurePosixPath(ruta).name
    return config.SALIDAS_DIR / nombre
