"""Motor de reglas de alerta temprana por provincia."""
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from . import config

NIVELES = ["sin alerta", "baja", "media", "alta"]
ORDEN = {n: i for i, n in enumerate(NIVELES)}


@dataclass
class Alerta:
    provincia: str
    tipo: str        # incendio | deforestación | vegetación | aire
    nivel: str       # baja | media | alta
    mensaje: str
    valor: float
    # Evidencia verificable: de dónde sale, de cuándo es, qué la activó y con qué calidad se observó
    fuente: str = ""
    fecha: str = ""
    indicador: str = ""
    calidad: str = ""
    latitud: float | None = None
    longitud: float | None = None

    def dict(self) -> dict:
        return asdict(self)


COLUMNAS = ["provincia", "tipo", "nivel", "mensaje", "valor", "fuente", "fecha", "indicador", "calidad",
            "latitud", "longitud"]


def alertas_incendio(focos: pd.DataFrame, eventos: pd.DataFrame) -> list[Alerta]:
    salida = []
    if focos.empty:
        return salida
    for prov, g in focos.groupby("provincia"):
        n, frp = len(g), float(g["frp"].sum())
        ev = eventos[eventos["provincia"] == prov] if not eventos.empty else eventos
        sev_alta = int((ev["severidad"] == "alta").sum()) if not ev.empty else 0
        if n >= config.INCENDIO_FOCOS_ALTO or frp >= config.INCENDIO_FRP_ALTO_MW or sev_alta:
            nivel = "alta"
        elif n >= config.INCENDIO_FOCOS_MEDIO or len(ev):
            nivel = "media"
        else:
            nivel = "baja"
        texto = f"{n} focos de calor (FRP {frp:.0f} MW)"
        if len(ev):
            texto += f", {len(ev)} evento(s) agrupado(s)"
            if sev_alta:
                texto += f", {sev_alta} de severidad alta"
        # Ubicación: el evento de mayor potencia o, si no hay eventos, el foco de mayor FRP
        punto = ev.sort_values("frp_total_mw").iloc[-1] if len(ev) else g.sort_values("frp").iloc[-1]
        sensores = ", ".join(sorted(g["fuente"].str.split("_").str[0].unique()))
        salida.append(Alerta(
            prov, "incendio", nivel, texto, float(n),
            fuente=f"NASA FIRMS ({sensores})",
            fecha=f"{g['fecha'].min():%d/%m/%Y}–{g['fecha'].max():%d/%m/%Y}",
            indicador=f"n.º de focos (≥ {config.INCENDIO_FOCOS_MEDIO} media, ≥ {config.INCENDIO_FOCOS_ALTO} alta), "
                      f"FRP y eventos DBSCAN",
            calidad=f"{100 * (g['confianza'] == 'alta').mean():.0f} % de focos con confianza alta",
            latitud=round(float(punto["latitud"]), 5), longitud=round(float(punto["longitud"]), 5)))
    return salida


def alertas_deforestacion(resumenes: list[dict]) -> list[Alerta]:
    salida = []
    for r in resumenes:
        ha = r["perdida_ha"]
        if ha >= config.DEFORESTACION_HA_ALTO:
            nivel = "alta"
        elif ha >= config.DEFORESTACION_HA_MEDIO:
            nivel = "media"
        elif ha > 0:
            nivel = "baja"
        else:
            continue
        aviso = "" if r["cobertura_pct"] >= 40 else f" (solo {r['cobertura_pct']:.0f} % sin nubes)"
        salida.append(Alerta(
            r["provincia"], "deforestación", nivel,
            f"{ha:.0f} ha de posible pérdida de cobertura forestal (tala, quema o desbroce){aviso}", ha,
            fuente="Sentinel-2 L2A (Copernicus) + máscara de bosque MINAM",
            fecha=r.get("periodo", ""),
            indicador=f"caída de NDVI ≥ {config.CAIDA_NDVI_DEFORESTACION} en bosque (≥ "
                      f"{config.DEFORESTACION_HA_MEDIO:g} ha media, ≥ {config.DEFORESTACION_HA_ALTO:g} ha alta)",
            calidad=f"{r['cobertura_pct']:.0f} % de la provincia observable; {r.get('mascara_bosque', '')}",
            latitud=r.get("zona_latitud"), longitud=r.get("zona_longitud")))
    return salida


def comparacion_ndvi(series_ndvi: pd.DataFrame) -> pd.DataFrame:
    """Último NDVI válido de cada provincia frente al mismo periodo del año anterior.

    Compararlo con la mediana anual marcaría alerta cada estación seca; la referencia es la mediana de
    los intervalos que empiezan a ±45 días de la misma fecha un año antes. Si el último dato despejado
    tiene más de 60 días, la provincia queda sin comparación (no sirve para alerta temprana).
    """
    columnas = ["provincia", "fecha", "ndvi", "ndvi_anio_anterior", "caida", "pct_valido"]
    filas = []
    if series_ndvi.empty:
        return pd.DataFrame(columns=columnas)
    for prov, g in series_ndvi.groupby("provincia"):
        g = g.sort_values("desde")
        validos = g.dropna(subset=["media"])
        if validos.empty:
            continue
        ultimo = validos.iloc[-1]
        ref = np.nan
        if ultimo["desde"] >= g["desde"].max() - pd.Timedelta(days=60):
            fecha_ref = ultimo["desde"] - pd.Timedelta(days=365)
            cerca = validos.loc[(validos["desde"] - fecha_ref).abs() <= pd.Timedelta(days=45), "media"]
            ref = float(cerca.median()) if len(cerca) else np.nan
        filas.append({"provincia": prov, "fecha": ultimo["desde"], "ndvi": float(ultimo["media"]),
                      "ndvi_anio_anterior": ref, "caida": ref - float(ultimo["media"]),
                      "pct_valido": float(ultimo.get("pct_valido", np.nan))})
    return pd.DataFrame(filas, columns=columnas)


def alertas_vegetacion(series_ndvi: pd.DataFrame) -> list[Alerta]:
    """Caída del NDVI del último mes válido respecto del mismo periodo del año anterior."""
    salida = []
    for r in comparacion_ndvi(series_ndvi).itertuples():
        if not r.caida >= config.CAIDA_NDVI_MEDIO:  # también descarta NaN (sin referencia)
            continue
        nivel = "alta" if r.caida >= config.CAIDA_NDVI_ALTO else "media"
        salida.append(Alerta(
            r.provincia, "vegetación", nivel,
            f"NDVI {r.ndvi:.2f} ({r.fecha:%d/%m/%Y}), {r.caida:.2f} por debajo del mismo periodo del año anterior",
            float(r.caida),
            fuente="Sentinel-2 L2A (Copernicus, Statistical API)",
            fecha=f"intervalo de 30 días desde {r.fecha:%d/%m/%Y}",
            indicador=f"caída de NDVI provincial vs. año anterior (≥ {config.CAIDA_NDVI_MEDIO} media, "
                      f"≥ {config.CAIDA_NDVI_ALTO} alta)",
            calidad=f"{r.pct_valido:.0f} % de la provincia observada sin nubes"))
    return salida


def alertas_aire(anomalias: pd.DataFrame) -> list[Alerta]:
    """`anomalias`: columnas provincia, contaminante, z, ultimo, unidad."""
    salida = []
    for _, r in anomalias.iterrows():
        z = r["z"]
        if np.isnan(z) or z < config.AIRE_Z_MEDIO:
            continue
        nivel = "alta" if z >= config.AIRE_Z_ALTO else "media"
        fecha = r.get("fecha")
        salida.append(Alerta(
            r["provincia"], "aire", nivel,
            f"{r['contaminante']} {r['ultimo']:.1f} {r['unidad']} (z = {z:.1f} sobre su línea base)", float(z),
            fuente="Sentinel-5P TROPOMI (Copernicus)",
            fecha=f"semana desde {fecha:%d/%m/%Y}" if pd.notna(fecha) else "",
            indicador=f"anomalía z de la columna de {r['contaminante']} (≥ {config.AIRE_Z_MEDIO} media, "
                      f"≥ {config.AIRE_Z_ALTO} alta)",
            calidad=f"{r['pct_valido']:.0f} % de la provincia con dato válido" if pd.notna(r.get("pct_valido"))
            else ""))
    return salida


def nivel_por_provincia(alertas: list[Alerta], provincias: list[str]) -> dict[str, str]:
    nivel = {p: "sin alerta" for p in provincias}
    for a in alertas:
        if ORDEN[a.nivel] > ORDEN[nivel.get(a.provincia, "sin alerta")]:
            nivel[a.provincia] = a.nivel
    return nivel


def tabla(alertas: list[Alerta]) -> pd.DataFrame:
    df = pd.DataFrame([a.dict() for a in alertas], columns=COLUMNAS)
    if df.empty:
        return df
    df["_o"] = df["nivel"].map(ORDEN)
    return df.sort_values(["_o", "provincia"], ascending=[False, True]).drop(columns="_o").reset_index(drop=True)
