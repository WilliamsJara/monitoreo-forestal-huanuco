"""Genera el informe técnico del proyecto (Word) a partir de `salidas/` y `salidas/validacion/`.

    .venv\\Scripts\\python scripts\\informe.py
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from docx import Document  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from huanuco_monitor import config, geo, indicadores  # noqa: E402
from huanuco_monitor.copernicus import ClienteCopernicus  # noqa: E402

VAL = config.SALIDAS_DIR / "validacion"
INF = config.SALIDAS_DIR / "informe"
AZUL, NARANJA, TINTA, TINTA2, GRILLA = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
ESTADO = {"Fiable": "0CA30C", "Fiable con reservas": "FAB219", "Parcial": "EC835A", "No fiable": "D03B3B"}

plt.rcParams.update({
    "font.family": "Arial", "font.size": 9, "axes.edgecolor": GRILLA, "axes.labelcolor": TINTA2,
    "xtick.color": TINTA2, "ytick.color": TINTA2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRILLA, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "figure.dpi": 200, "savefig.bbox": "tight",
})


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 2
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, c - m), min(1.0, c + m)


def ultima_corrida() -> Path:
    carpetas = sorted(p for p in config.SALIDAS_DIR.iterdir() if p.is_dir() and p.name[:8].isdigit())
    return carpetas[-1]


# ----------------------------------------------------------------------------- figuras

def barras_h(serie: pd.Series, xlabel: str, ruta: Path, fmt="{:,.0f}", color=AZUL, alto=None):
    serie = serie.sort_values()
    fig, ax = plt.subplots(figsize=(6.2, alto or 0.32 * len(serie) + 0.6))
    ax.barh(serie.index, serie.values, color=color, height=0.68)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(xlabel)
    for y, v in enumerate(serie.values):
        ax.text(v, y, " " + fmt.format(v).replace(",", " "), va="center", fontsize=8, color=TINTA)
    ax.set_xlim(0, serie.max() * 1.15 if serie.max() > 0 else 1)
    fig.savefig(ruta)
    plt.close(fig)


def mapa_focos(focos: pd.DataFrame, ruta: Path):
    fig, ax = plt.subplots(figsize=(6.2, 6.0))
    for p in geo.provincias().values():
        geoms = getattr(p.geometria, "geoms", [p.geometria])
        for g in geoms:
            if g.geom_type != "Polygon":
                continue
            x, y = g.exterior.xy
            ax.fill(x, y, color="#f0efec", ec="#8a8984", lw=0.8)
        c = p.geometria.representative_point()
        ax.text(c.x, c.y, p.nombre, fontsize=7, ha="center", color=TINTA2,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75))
    ax.scatter(focos["longitud"], focos["latitud"], s=6 + focos["frp"].clip(0, 100) / 4, c=NARANJA,
               edgecolors="white", linewidths=0.3, alpha=0.85, label="foco de calor (tamaño = FRP)")
    ax.set_aspect("equal")
    ax.grid(False)
    ax.set_xlabel("longitud")
    ax.set_ylabel("latitud")
    ax.legend(loc="lower left", frameon=False, fontsize=8)
    fig.savefig(ruta)
    plt.close(fig)


# ----------------------------------------------------------------------------- docx helpers

def sombrear(celda, hex_color):
    tc = celda._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc.append(shd)


def tabla(doc, df: pd.DataFrame, anchos=None, colorear=None, fuente=8.5):
    t = doc.add_table(rows=1, cols=len(df.columns))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, c in enumerate(df.columns):
        cel = t.rows[0].cells[i]
        cel.text = ""
        r = cel.paragraphs[0].add_run(str(c))
        r.bold = True
        r.font.size = Pt(fuente)
        sombrear(cel, "E4E3DF")
    for fila in df.itertuples(index=False):
        celdas = t.add_row().cells
        for i, v in enumerate(fila):
            celdas[i].text = ""
            r = celdas[i].paragraphs[0].add_run("" if pd.isna(v) else str(v))
            r.font.size = Pt(fuente)
            if colorear and df.columns[i] == colorear[0] and str(v) in colorear[1]:
                sombrear(celdas[i], colorear[1][str(v)])
    if anchos:
        for fila in t.rows:
            for i, w in enumerate(anchos):
                fila.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


def figura(doc, ruta, ancho_cm, pie):
    doc.add_picture(str(ruta), width=Cm(ancho_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph(pie)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.runs[0].italic = True
    p.runs[0].font.size = Pt(8.5)
    p.runs[0].font.color.rgb = RGBColor(0x52, 0x51, 0x4E)


def parrafo(doc, texto, negrita_inicial=None):
    p = doc.add_paragraph()
    if negrita_inicial:
        p.add_run(negrita_inicial).bold = True
    p.add_run(texto)
    return p


def vinetas(doc, items):
    for it in items:
        if isinstance(it, tuple):
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(it[0]).bold = True
            p.add_run(it[1])
        else:
            doc.add_paragraph(it, style="List Bullet")


def fmt(v, d=0):
    return f"{v:,.{d}f}".replace(",", " ")


# ----------------------------------------------------------------------------- main

def main():
    INF.mkdir(parents=True, exist_ok=True)
    corrida = ultima_corrida()
    resumen = json.loads((corrida / "resumen.json").read_text(encoding="utf-8"))
    focos = pd.read_csv(corrida / "focos_calor.csv", parse_dates=["fecha"])
    eventos = pd.read_csv(corrida / "eventos_incendio.csv")
    alertas = pd.read_csv(corrida / "alertas.csv")
    cambio = pd.read_csv(VAL / "cambio_cobertura_resumen.csv")
    met = json.loads((VAL / "metricas.json").read_text(encoding="utf-8"))
    interp = pd.read_csv(VAL / "interpretacion_visual.csv")
    m_perd = pd.read_csv(VAL / "muestra_perdida.csv").merge(interp, on="id")
    m_rec = pd.read_csv(VAL / "muestra_recuperacion.csv").merge(interp, on="id")
    m_inc = interp[interp["tipo"] == "incendio"]
    sens = pd.read_csv(VAL / "sensibilidad_umbrales.csv")

    # --- estadísticas de verificación
    n_p, k_p = len(m_perd), int((m_perd["categoria"] == "confirmada").sum())
    ic_p = wilson(k_p, n_p)
    prec_area = m_perd.loc[m_perd["categoria"] == "confirmada", "hectareas"].sum() / m_perd["hectareas"].sum()
    por_prov = m_perd.groupby("provincia")["categoria"].agg(
        muestras="size", confirmadas=lambda s: int((s == "confirmada").sum())).reset_index()
    pi = por_prov[por_prov["provincia"] == "Puerto Inca"].iloc[0]
    n_r, k_r = len(m_rec), int((m_rec["categoria"] == "confirmada").sum())
    n_i, k_i = len(m_inc), int((m_inc["categoria"] == "confirmada").sum())
    cat_nombre = {"confirmada": "Pérdida confirmada", "falso_nube": "Falso positivo: nube o sombra",
                  "cambio_agricola": "Cambio agrícola (no bosque)", "sin_cambio_visible": "Sin cambio visible",
                  "falso_sombra": "Falso positivo: sombra topográfica", "falso_rio": "Falso positivo: río"}
    dist_p = m_perd["categoria"].map(cat_nombre).value_counts()

    # Estabilidad del orden de provincias ante los umbrales (Spearman)
    cliente = ClienteCopernicus()
    antes, despues = indicadores.periodos_por_defecto()
    sys.path.insert(0, str(Path(__file__).parent))
    from validar import mascara_perdida  # noqa: E402
    cambios = {n: indicadores.cambio_cobertura(cliente, p, antes, despues) for n, p in geo.provincias().items()}
    variantes = {
        "def": dict(bosque=0.60, caida=0.25, max_tras=0.45, vecinos=3, min_obs=2),
        "c35": dict(bosque=0.60, caida=0.35, max_tras=0.45, vecinos=3, min_obs=2),
        "b70": dict(bosque=0.70, caida=0.25, max_tras=0.45, vecinos=3, min_obs=2),
        "v5": dict(bosque=0.60, caida=0.25, max_tras=0.45, vecinos=5, min_obs=2),
        "o3": dict(bosque=0.60, caida=0.25, max_tras=0.45, vecinos=3, min_obs=3),
    }
    tabla_var = pd.DataFrame({k: {n: cc.hectareas(mascara_perdida(cc, **kw)) for n, cc in cambios.items()}
                              for k, kw in variantes.items()})
    rangos = tabla_var.rank()
    rho = {k: rangos["def"].corr(rangos[k]) for k in variantes if k != "def"}
    rho_min = min(rho.values())
    top_estable = all(tabla_var[k].idxmax() == "Puerto Inca" for k in variantes)

    obs_total = cambio["perdida_ha"].sum()
    cob_media = met["cambio"]["cobertura_media_pct"]
    n_alta = sum(v == "alta" for v in resumen["niveles"].values())
    n_veg = int((alertas["tipo"] == "vegetación").sum())
    n_aire = int((alertas["tipo"] == "aire").sum())
    ajustado = (obs_total * ic_p[0], obs_total * ic_p[1])

    # --- figuras
    mapa_focos(focos, INF / "fig_mapa_focos.png")
    barras_h(focos.groupby("provincia").size(), "detecciones de focos de calor (7 días)", INF / "fig_focos.png")
    barras_h(cambio.set_index("provincia")["perdida_ha"], "posible pérdida observada (ha, 90 días)",
             INF / "fig_perdida.png")
    barras_h(dist_p, "muestras (de 20)", INF / "fig_verificacion.png", alto=2.0)
    barras_h(sens.set_index("variante")["perdida_total_ha"], "pérdida total estimada (ha)",
             INF / "fig_sensibilidad.png")

    # --- documento
    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(10.5)
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2.2)
        s.top_margin = s.bottom_margin = Cm(2.0)

    t = doc.add_heading("Sistema inteligente de monitoreo satelital y alerta temprana de contaminación "
                        "y amenazas forestales en el departamento de Huánuco", 0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph(f"Informe técnico de proyecto, resultados y verificación\n"
                          f"Corte de datos: {pd.Timestamp(resumen['generado']):%d/%m/%Y %H:%M} · "
                          f"Fecha del informe: {date.today():%d/%m/%Y}")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 1. Resumen ejecutivo
    doc.add_heading("1. Resumen ejecutivo", 1)
    parrafo(doc, "Se desarrolló y puso en funcionamiento un sistema que integra datos satelitales de NASA FIRMS, "
                 "Sentinel-2 y Sentinel-5P para vigilar incendios, pérdida de cobertura forestal, salud de la "
                 "vegetación y contaminación atmosférica en las 11 provincias de Huánuco, con un tablero web "
                 "interactivo y un proceso automatizable de generación de alertas. El sistema opera con datos "
                 "reales; todas las cifras de este informe provienen de una corrida completa del "
                 f"{pd.Timestamp(resumen['generado']):%d/%m/%Y}.")
    parrafo(doc, "Los resultados no se aceptaron sin más: se verificaron con pruebas de integridad, comparación "
                 "con estadísticas oficiales, análisis de sensibilidad y fotointerpretación de muestras "
                 "aleatorias de imágenes Sentinel-2. La conclusión es que el sistema es ", None)
    doc.paragraphs[-1].add_run("fiable para detectar y localizar incendios activos, útil como herramienta de "
                               "priorización de posibles zonas de tala en la Amazonía baja, y todavía no fiable "
                               "para cuantificar hectáreas deforestadas ni para afirmar recuperación de "
                               "ecosistemas.").bold = True
    doc.add_paragraph()

    veredicto = pd.DataFrame([
        ["Focos de calor e incendios", "Fiable",
         f"Integridad de datos verificada; {k_i} de {n_i} eventos de mayor intensidad muestran cicatriz de quema "
         "nueva en imagen SWIR; FIRMS es la fuente de referencia internacional."],
        ["Alerta de posible tala (localización)", "Parcial",
         f"{k_p} de {n_p} zonas al azar confirmadas ({ic_p[0]:.0%}–{ic_p[1]:.0%}, IC 95 %); "
         f"{int(pi.confirmadas)} de {int(pi.muestras)} en Puerto Inca. Falla sobre todo por nubes no enmascaradas."],
        ["Superficie deforestada (hectáreas)", "No fiable",
         f"Sobrestimada: {fmt(obs_total)} ha observadas en 90 días frente a ~13 000 ha/año oficiales para "
         "todo el departamento; muy sensible a umbrales."],
        ["Recuperación de cobertura", "No fiable",
         f"Solo {k_r} de {n_r} muestras corresponden a rebrote real; el resto son nubes, cultivos o ríos."],
        ["Salud de la vegetación (NDVI mensual)", "Fiable con reservas",
         f"Valores plausibles; {met['ndvi']['meses_validos_pct']:.0f} % de meses válidos, pero solo "
         f"~{met['ndvi']['cobertura_media_pct']:.0f} % de cada provincia observada sin nubes por mes."],
        ["Calidad del aire (Sentinel-5P)", "Fiable con reservas",
         f"Rangos físicamente plausibles; NO₂ con solo {met['aire']['NO2']['semanas_validas_pct']:.0f} % de semanas "
         "válidas. Mide columna atmosférica, no aire a nivel del suelo; sin estaciones para contrastar."],
    ], columns=["Componente", "Fiabilidad", "Evidencia"])
    tabla(doc, veredicto, anchos=[4.2, 3.0, 9.5], colorear=("Fiabilidad", ESTADO))

    # 2. Objetivos
    doc.add_heading("2. Descripción y objetivos del proyecto", 1)
    parrafo(doc, "El sistema busca contribuir a la prevención, gestión de riesgos y restauración de ecosistemas "
                 "forestales del departamento de Huánuco mediante inteligencia artificial, imágenes satelitales y "
                 "análisis geoespacial. Sus objetivos específicos son:")
    vinetas(doc, [
        "Detectar focos de calor asociados a incendios forestales y agruparlos en eventos.",
        "Identificar posibles áreas de deforestación y tala.",
        "Monitorear indicadores de contaminación atmosférica (NO₂ y CO).",
        "Analizar la cobertura vegetal y el seguimiento de zonas con indicios de recuperación.",
        "Visualizar la información georreferenciada por provincia y emitir alertas preventivas.",
    ])
    parrafo(doc, "El proyecto mejora el prototipo anterior YACUMAMA IA (cuadernos de Google Colab): se convirtió en "
                 "un paquete Python modular, independiente de Colab y de Google Earth Engine, con credenciales "
                 "fuera del código, cuatro sensores de incendios en lugar de uno, detección de cambio por píxel con "
                 "enmascarado de nubes, caché de consultas, tablero web y un script de actualización programable.")

    # 3. Área de estudio
    doc.add_heading("3. Área de estudio", 1)
    areas = pd.DataFrame([(p.nombre, fmt(p.area_km2)) for p in geo.provincias().values()],
                         columns=["Provincia", "Área (km²)"])
    parrafo(doc, "Las 11 provincias del departamento de Huánuco, desde la puna andina (Lauricocha, Yarowilca, "
                 "Dos de Mayo) hasta la selva baja amazónica (Puerto Inca). Los límites provienen de "
                 "geoBoundaries (nivel ADM2); el área calculada coincide con la oficial con diferencias menores "
                 "al 5 %.")
    tabla(doc, areas, anchos=[5, 3])

    # 4. Arquitectura
    doc.add_heading("4. Arquitectura y fuentes de datos", 1)
    tabla(doc, pd.DataFrame([
        ["Focos de calor", "NASA FIRMS: VIIRS S-NPP, NOAA-20, NOAA-21 (375 m) y MODIS (1 km)", "Casi tiempo real (~3 h)"],
        ["Vegetación y cambio", "Sentinel-2 L2A vía Copernicus Data Space (Statistical y Process API)", "Cada 5 días (nubes)"],
        ["Contaminación", "Sentinel-5P TROPOMI L2 (NO₂ troposférico, CO total), producto OFFL", "Diaria, ~5 km"],
        ["Límites", "geoBoundaries PER ADM2", "Estático"],
        ["Mapa base", "Esri World Imagery, OpenStreetMap", "—"],
    ], columns=["Componente", "Fuente", "Frecuencia / resolución"]), anchos=[3.3, 9.2, 4.2])
    parrafo(doc, "Componentes de software: cliente OAuth2 de Copernicus, módulo FIRMS con agrupación DBSCAN, "
                 "módulo de indicadores (NDVI, cambio de cobertura, NO₂, CO), motor de reglas de alerta, "
                 "orquestador paralelo de provincias, caché en disco con vencimiento, tablero Streamlit "
                 "(app.py) y scripts de actualización (actualizar.py), validación (validar.py) e informe "
                 "(informe.py).")
    figura(doc, INF / "tablero_panorama.png", 16.5,
           "Figura 1. Tablero web: panorama de alertas por provincia. El panorama del tablero no incluye las "
           "alertas de deforestación (se calculan bajo demanda); por eso muestra menos provincias en alerta alta "
           "que la corrida completa usada en este informe.")

    # 5. Metodología
    doc.add_heading("5. Metodología", 1)
    vinetas(doc, [
        ("Incendios. ", "Se descargan los focos de los cuatro sensores en ventanas de 5 días, se asignan a la "
         "provincia que los contiene y se agrupan con DBSCAN (distancia haversine, radio "
         f"{config.DBSCAN_EPS_KM} km, mínimo {config.DBSCAN_MIN_FOCOS} focos). Cada evento recibe severidad "
         "según número de focos, potencia radiativa (FRP) y días activo."),
        ("Pérdida de cobertura (posible tala). ", "Para cada píxel se calcula la mediana del NDVI de las "
         "observaciones despejadas (máscara SCL) en los últimos 90 días y en el mismo periodo del año anterior, "
         "para no confundir estacionalidad con deforestación. Se marca pérdida si el píxel era bosque "
         f"(NDVI ≥ {config.NDVI_BOSQUE}), cae al menos {config.CAIDA_NDVI_DEFORESTACION}, queda sin dosel "
         f"(≤ {config.NDVI_MAX_TRAS_PERDIDA}), tiene ≥ {config.MIN_OBSERVACIONES} observaciones por periodo y "
         f"≥ {config.MIN_VECINOS} vecinos marcados."),
        ("Recuperación. ", f"Píxeles degradados (NDVI ≤ {config.NDVI_DEGRADADO}) con aumento "
         f"≥ {config.GANANCIA_NDVI_RECUPERACION}."),
        ("Salud de la vegetación. ", "NDVI medio mensual por provincia (~220 m); alerta si el último mes cae "
         "≥ 0,10 bajo la mediana anual."),
        ("Calidad del aire. ", "Media semanal de NO₂ y CO por provincia; alerta si el puntaje z de la última "
         f"semana respecto de las anteriores es ≥ {config.AIRE_Z_MEDIO}."),
        ("Alertas. ", "Reglas por provincia con niveles baja, media y alta; el nivel provincial es el máximo de "
         "sus alertas."),
    ])

    # 6. Resultados
    doc.add_heading("6. Resultados", 1)
    f = met["firms"]
    doc.add_heading("6.1 Incendios y focos de calor (últimos 7 días)", 2)
    parrafo(doc, f"Se registraron {fmt(f['detecciones'])} detecciones de focos de calor, que corresponden a "
                 f"aproximadamente {fmt(f['detecciones_unicas_dia_celda_400m'])} focos distintos al descontar el "
                 f"mismo fuego visto por varios satélites. El {f['focos_en_eventos_pct']:.0f} % se agrupa en "
                 f"{f['eventos_dbscan']} eventos de incendio ({f['eventos_por_severidad'].get('alta', 0)} de "
                 f"severidad alta). Las provincias más afectadas son Puerto Inca, Ambo y Huánuco. El evento de "
                 f"mayor intensidad está en Ambo ({int(eventos.iloc[0]['focos'])} focos, FRP "
                 f"{fmt(eventos.iloc[0]['frp_total_mw'])} MW).")
    figura(doc, INF / "fig_mapa_focos.png", 12.5, "Figura 2. Focos de calor detectados (7 días).")
    figura(doc, INF / "fig_focos.png", 12.5, "Figura 3. Detecciones de focos de calor por provincia.")

    doc.add_heading("6.2 Posible pérdida y recuperación de cobertura (90 días)", 2)
    parrafo(doc, f"Periodo analizado: {antes[0]:%d/%m/%Y}–{antes[1]:%d/%m/%Y} frente a "
                 f"{despues[0]:%d/%m/%Y}–{despues[1]:%d/%m/%Y}. Las cifras son la salida del sistema "
                 "y deben leerse junto con la verificación de la sección 7, que muestra que están sobrestimadas.")
    t_cambio = cambio[["provincia", "perdida_ha", "recuperacion_ha", "cobertura_pct", "res_m"]].copy()
    t_cambio.columns = ["Provincia", "Pérdida observada (ha)", "Recuperación (ha)", "Área sin nubes (%)",
                        "Resolución (m)"]
    tabla(doc, t_cambio.sort_values("Pérdida observada (ha)", ascending=False), anchos=[3.5, 3.4, 3.2, 3.2, 2.6])
    figura(doc, INF / "fig_perdida.png", 12.5, "Figura 4. Posible pérdida de cobertura observada por provincia.")
    figura(doc, INF / "tablero_cobertura.png", 16.5,
           "Figura 5. Tablero: análisis de cambio de cobertura en Puerto Inca (zonas prioritarias en rojo).")

    doc.add_heading("6.3 Vegetación y calidad del aire", 2)
    a = met["aire"]
    parrafo(doc, f"El NDVI mensual provincial varió entre {met['ndvi']['rango'][0]:.2f} y "
                 f"{met['ndvi']['rango'][1]:.2f}, con valores bajos en provincias andinas y altos en la selva, "
                 f"como se espera. {n_veg} provincias presentan NDVI del último mes ≥ 0,10 por debajo de su "
                 "mediana anual, coherente con la estación seca y los incendios en curso. "
                 f"La columna de NO₂ tuvo mediana de {a['NO2']['mediana']:.1f} µmol/m² y la de CO "
                 f"{a['CO']['mediana']:.1f} mmol/m²; "
                 + ("sin anomalías significativas en la última semana válida." if n_aire == 0
                    else f"{n_aire} alerta(s) por anomalía."))

    doc.add_heading("6.4 Alertas emitidas", 2)
    cuenta = alertas.groupby(["tipo", "nivel"]).size().unstack(fill_value=0)
    cuenta = cuenta.reindex(columns=[c for c in ["alta", "media", "baja"] if c in cuenta.columns])
    cuenta = cuenta.reset_index().rename(columns={"tipo": "Tipo de alerta"})
    tabla(doc, cuenta, anchos=[4, 2.5, 2.5, 2.5])
    parrafo(doc, "Las alertas de deforestación de nivel alto deben interpretarse como zonas a verificar y no como "
                 "superficie deforestada confirmada (ver sección 7).")

    # 7. Verificación
    doc.add_heading("7. Verificación y fiabilidad de los resultados", 1)
    doc.add_heading("7.1 Integridad técnica", 2)
    vinetas(doc, [
        "Credenciales validadas contra los servicios (token OAuth2 de Copernicus y estado de la clave FIRMS).",
        "Las 11 provincias se cargaron correctamente; se corrigió un error de codificación del nombre «Marañón» "
        "en la fuente de límites.",
        "Respuestas de las API comprobadas manualmente (CSV de FIRMS y estadísticas de Sentinel-2/5P) antes de "
        "integrarlas.",
        "Cada sección del tablero se ejecutó sin errores (prueba automatizada de Streamlit y capturas de pantalla).",
        "Se corrigieron defectos detectados durante las pruebas: límite de 5 días por consulta de FIRMS, alineación "
        "del ráster, umbrales de severidad demasiado permisivos y falsos positivos por píxeles aislados.",
    ])

    doc.add_heading("7.2 Comparación con estadísticas oficiales", 2)
    tabla(doc, pd.DataFrame([
        ["Este sistema (salida directa)", "Departamento", "90 días (jul–oct 2026)", f"{fmt(obs_total)} ha en ~{cob_media:.0f} % del área observada"],
        ["Este sistema (corregido por precisión)", "Departamento", "90 días", f"≈ {fmt(round(ajustado[0], -2))}–{fmt(round(ajustado[1], -2))} ha"],
        ["Geobosques (MINAM)", "Departamento", "Año 2025", "≈ 13 000 ha/año"],
        ["Global Forest Watch", "Departamento", "Año 2025", "≈ 21 000 ha/año (bosque natural)"],
        ["Geobosques (MINAM)", "Puerto Inca", "Año 2023 / 2021", "2 679 ha / 10 784 ha"],
        ["Este sistema", "Puerto Inca", "90 días", f"{fmt(cambio.set_index('provincia').loc['Puerto Inca', 'perdida_ha'])} ha"],
    ], columns=["Fuente", "Ámbito", "Periodo", "Pérdida de bosque"]), anchos=[5.2, 2.8, 3.6, 5.1])
    parrafo(doc, "La salida directa equivale a casi un año de pérdida oficial en solo tres meses y observando menos "
                 "de la mitad del territorio, por lo que está claramente sobrestimada. Al descontar los falsos "
                 "positivos con la precisión medida (sección 7.3), la cifra queda en un orden de magnitud "
                 "compatible con las estadísticas oficiales, considerando que julio–octubre es la temporada de "
                 "mayor desbroce y quema. Aun así, el rango es amplio y no sustituye a Geobosques.")

    doc.add_heading("7.3 Verificación visual con imágenes Sentinel-2", 2)
    parrafo(doc, f"Se tomaron al azar (semilla 42) {n_p} zonas de pérdida, {n_r} de recuperación y los 5 eventos "
                 "de incendio de mayor FRP. Para cada una se compararon imágenes Sentinel-2 de ambos periodos con la "
                 "detección superpuesta. La interpretación la realizó el asistente de IA que desarrolló el sistema; "
                 "se recomienda que un especialista la revise y que se complemente con verificación de campo.")
    tabla(doc, pd.DataFrame([
        ["Pérdida de cobertura", n_p, k_p, f"{k_p / n_p:.0%}", f"{ic_p[0]:.0%}–{ic_p[1]:.0%}"],
        ["Pérdida (ponderado por área)", n_p, "—", f"{prec_area:.0%}", "—"],
        ["Recuperación", n_r, k_r, f"{k_r / n_r:.0%}", f"{wilson(k_r, n_r)[0]:.0%}–{wilson(k_r, n_r)[1]:.0%}"],
        ["Eventos de incendio (5 de mayor FRP)", n_i, k_i, f"{k_i / n_i:.0%}", "muestra dirigida"],
    ], columns=["Indicador", "Muestras", "Confirmadas", "Precisión", "IC 95 % (Wilson)"]),
        anchos=[5.5, 2.2, 2.4, 2.3, 3.5])
    figura(doc, INF / "fig_verificacion.png", 12.5, "Figura 6. Resultado de la verificación de 20 zonas de pérdida.")
    tm = m_perd[["id", "provincia", "hectareas", "dist_foco_km", "categoria", "observacion"]].copy()
    tm["categoria"] = tm["categoria"].map(cat_nombre)
    tm.columns = ["ID", "Provincia", "ha", "Foco a (km)", "Resultado", "Observación"]
    tabla(doc, tm, anchos=[1.1, 2.6, 1.2, 1.7, 4.0, 6.1], fuente=8)
    parrafo(doc, "Hallazgos: ", None)
    vinetas(doc, [
        f"Todas las zonas confirmadas están en la Amazonía baja (Puerto Inca {int(pi.confirmadas)} de "
        f"{int(pi.muestras)}, Marañón 2 de 4); en provincias andinas y de selva alta nubosa no se confirmó ninguna.",
        "La principal causa de error (9 de 20) son nubes y sombras de nube que la máscara SCL de Sentinel-2 no "
        "elimina.",
        "La segunda causa (3 de 20) son cambios en parcelas agrícolas, que el sistema no distingue del bosque.",
        "Las zonas confirmadas son, en promedio, más grandes que las falsas: la precisión ponderada por área es "
        f"{prec_area:.0%}.",
    ])
    for i, nombre in enumerate(["lamina_perdida_1.png", "lamina_perdida_2.png"], start=7):
        figura(doc, VAL / nombre, 11.5, f"Figura {i}. Muestras de pérdida: antes (2025), después (2026) y "
                                         "después con la detección en magenta.")
    figura(doc, VAL / "lamina_incendios.png", 11.5,
           "Figura 9. Eventos de incendio: SWIR previo, SWIR reciente (cicatriz de quema en rojo) y color real.")

    doc.add_heading("7.4 Sensibilidad a los umbrales", 2)
    parrafo(doc, f"La superficie total de pérdida cambia de {fmt(sens['perdida_total_ha'].min())} a "
                 f"{fmt(sens['perdida_total_ha'].max())} ha según los umbrales elegidos, por lo que la cifra en "
                 "hectáreas no es robusta. En cambio, el orden de las provincias se mantiene: correlación de "
                 f"Spearman ≥ {rho_min:.2f} entre variantes"
                 + (", y Puerto Inca es la provincia con más pérdida en todas." if top_estable else "."))
    figura(doc, INF / "fig_sensibilidad.png", 12.5, "Figura 10. Pérdida total según la variante de umbrales.")

    doc.add_heading("7.5 Coincidencia entre pérdida e incendios", 2)
    c = met["coincidencia_fuego"]
    parrafo(doc, f"El {c['zonas_a_1km_pct']:.0f} % de las {c['zonas_evaluadas']} zonas de pérdida tiene un foco "
                 f"VIIRS a menos de 1 km en el mismo periodo, frente al {c['azar_a_1km_pct']:.0f} % esperado para "
                 f"puntos al azar ({fmt(c['focos_viirs_90d'])} focos en 90 días). La asociación es moderada: parte "
                 "de la pérdida corresponde a desbroce y quema, pero los incendios son tan frecuentes en la "
                 "temporada que este cruce no sirve por sí solo como confirmación.")

    doc.add_heading("7.6 Vegetación y calidad del aire", 2)
    vinetas(doc, [
        f"NDVI: valores dentro del rango físico y con el patrón esperado (selva > Andes). El "
        f"{100 - met['ndvi']['meses_validos_pct']:.0f} % de los meses se descartó por nubosidad.",
        f"CO: mediana {a['CO']['mediana']:.1f} mmol/m² (p10–p90: {a['CO']['p10_p90'][0]:.1f}–"
        f"{a['CO']['p10_p90'][1]:.1f}), sin valores negativos. Es más alto en la selva baja porque la columna "
        "atmosférica es más larga a menor altitud: las provincias no deben compararse entre sí, solo cada una "
        "con su propia historia.",
        f"NO₂: mediana {a['NO2']['mediana']:.1f} µmol/m², valores típicos de zonas rurales. Solo el "
        f"{a['NO2']['semanas_validas_pct']:.0f} % de las semanas tiene datos suficientes.",
        "No existen en el departamento estaciones de calidad del aire con datos públicos para contrastar; los "
        "valores son plausibles, pero no están validados en superficie.",
    ])

    # 8. Limitaciones
    doc.add_heading("8. Limitaciones", 1)
    vinetas(doc, [
        f"La nubosidad persistente limita las observaciones ópticas: en promedio se observó el {cob_media:.0f} % "
        "de cada provincia en el análisis de cambio.",
        "Una caída de NDVI no distingue tala, quema, cosecha o sequía; el sistema emite «posible pérdida».",
        "Los umbrales no se han calibrado con datos de campo ni con el mapa oficial de bosque/no bosque.",
        "La verificación visual usa una muestra pequeña (20 zonas) y no la hizo un especialista en campo.",
        "Los focos FIRMS son anomalías térmicas: pueden incluir quemas agrícolas controladas y no miden el área "
        "quemada.",
        "Sentinel-5P mide la columna total de la atmósfera con unos 5 km de resolución; no equivale a la calidad del "
        "aire que se respira.",
        f"Las alertas por umbral fijo tienden a saturarse en plena temporada seca: sumando incendios y posible "
        f"deforestación, {n_alta} de las 11 provincias quedaron en nivel alto, lo que reduce su utilidad para "
        "priorizar. Conviene usar umbrales relativos a la historia de cada provincia.",
    ])

    # 9. Recomendaciones
    doc.add_heading("9. Recomendaciones para alcanzar resultados fiables", 1)
    tabla(doc, pd.DataFrame([
        ["1", "Mejorar la máscara de nubes: bandas CLM/CLP (s2cloudless) con dilatación de 2–3 píxeles",
         "Elimina la causa del 45 % de los falsos positivos"],
        ["2", "Restringir el análisis a la máscara oficial de bosque (Geobosques/MINAM)",
         "Elimina los cambios agrícolas y andinos"],
        ["3", "Añadir radar Sentinel-1, que no depende de las nubes", "Cobertura en selva alta nubosa"],
        ["4", "Calibrar umbrales con alertas oficiales (Geobosques, GLAD/RADD) y validar con ≥ 100 puntos "
              "estratificados por provincia", "Precisión y exhaustividad medidas con rigor"],
        ["5", "Exigir persistencia de la pérdida en dos fechas consecutivas", "Reduce falsos positivos temporales"],
        ["6", "Rediseñar la recuperación con series largas (≥ 2 años) y solo sobre pérdida previa conocida",
         "Indicador de restauración creíble"],
        ["7", "Entrenar un clasificador (ResNet o Random Forest) con las muestras verificadas",
         "Componente de IA supervisado y medible"],
        ["8", "Validar con brigadas de campo de SERFOR o del Gobierno Regional", "Verdad de terreno"],
    ], columns=["#", "Acción", "Beneficio esperado"]), anchos=[0.8, 10, 5.9])

    # 10. Conclusión
    doc.add_heading("10. Conclusión", 1)
    parrafo(doc, "El sistema está operativo, integra fuentes satelitales reconocidas y genera alertas por "
                 "provincia de forma automática. La verificación muestra que la detección de incendios es "
                 "confiable y que la alerta de posible tala identifica correctamente claros reales en la Amazonía "
                 "baja, sobre todo en Puerto Inca, que es además la provincia con mayor presión según las "
                 "fuentes oficiales y la prensa. La superficie deforestada y la recuperación aún no deben "
                 "reportarse como cifras oficiales: están sobrestimadas, sobre todo por nubes y cambios "
                 "agrícolas. Aplicar las recomendaciones 1, 2 y 4 es el paso necesario para que el sistema pase de "
                 "herramienta de priorización a herramienta de cuantificación.")

    # Anexos
    doc.add_heading("Anexo A. Reproducibilidad", 1)
    for linea in [
        r".venv\Scripts\python scripts\actualizar.py --dias 7 --cobertura",
        r".venv\Scripts\python scripts\validar.py",
        r".venv\Scripts\python scripts\informe.py",
        r".venv\Scripts\streamlit run app.py",
    ]:
        p = doc.add_paragraph(linea)
        p.runs[0].font.name = "Consolas"
        p.runs[0].font.size = Pt(9)
    parrafo(doc, f"Datos de esta corrida: {corrida.relative_to(config.ROOT)} y "
                 f"{VAL.relative_to(config.ROOT)} (métricas, muestras, interpretación y láminas).")
    doc.add_heading("Anexo B. Fuentes y referencias", 1)
    vinetas(doc, [
        "NASA FIRMS — Fire Information for Resource Management System. https://firms.modaps.eosdis.nasa.gov",
        "Copernicus Data Space Ecosystem — Sentinel-2 L2A y Sentinel-5P. https://dataspace.copernicus.eu",
        "MINAM — Geobosques, reportes de cobertura y pérdida de bosque. https://geobosques.minam.gob.pe",
        "Global Forest Watch — Huánuco, Perú. https://www.globalforestwatch.org/dashboards/country/PER/10/",
        "MINAM/SINIA — Reporte de cobertura de bosques y pérdida 2023.",
        "geoBoundaries — límites administrativos PER ADM2. https://www.geoboundaries.org",
    ])

    ruta = INF / f"Informe_monitoreo_forestal_Huanuco_{date.today():%Y%m%d}.docx"
    doc.save(ruta)
    print(json.dumps({
        "precision_perdida": [k_p, n_p, round(ic_p[0], 3), round(ic_p[1], 3)],
        "precision_area": round(prec_area, 3), "recuperacion": [k_r, n_r], "incendios": [k_i, n_i],
        "rho_min": round(rho_min, 3), "rho": {k: round(v, 3) for k, v in rho.items()},
        "top_estable": top_estable, "ajustado": [round(x) for x in ajustado],
    }, ensure_ascii=False))
    print(f"Informe: {ruta}")


if __name__ == "__main__":
    main()
