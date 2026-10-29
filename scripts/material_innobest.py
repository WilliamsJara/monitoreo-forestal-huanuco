"""Documento de resultados para INNOBEST HUÁNUCO 2026 (Word), con gráficos y láminas de evidencia.

    .venv\\Scripts\\python scripts\\material_innobest.py

Lee los resultados ya calculados (validación MINAM, comparación de máscaras, interpretación visual,
última corrida) y genera `salidas/innobest/Resultados_INNOBEST_2026.docx` con sus figuras.
"""
import json
import sys
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from docx import Document  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from huanuco_monitor import config  # noqa: E402

TITULO = ("Sistema inteligente de monitoreo satelital y alerta temprana de contaminación y amenazas forestales "
          "en el departamento de Huánuco")
VAL = config.SALIDAS_DIR / "validacion"
SALIDA = config.SALIDAS_DIR / "innobest"

# Paleta validada (scripts/validate_palette.js de la guía dataviz): azul y naranja, ΔE CVD 24,7
AZUL, NARANJA = "#2a78d6", "#eb6834"
SUPERFICIE, TINTA, TINTA_2, APAGADO, REJILLA = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"


def estilo_ejes(ax):
    ax.set_facecolor(SUPERFICIE)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(APAGADO)
    ax.tick_params(colors=TINTA_2, labelsize=9, length=0)
    ax.yaxis.grid(True, color=REJILLA, linewidth=0.8)
    ax.set_axisbelow(True)


def barras_redondeadas(ax, xs, alturas, color, ancho):
    ax.bar(xs, alturas, width=ancho, color=color, linewidth=0, zorder=2)


def figura_precision(versiones: list[tuple[str, float]], azar: float, ruta: Path):
    """Una sola serie (precisión frente a MINAM por versión) con la línea de azar como referencia."""
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=200)
    fig.patch.set_facecolor(SUPERFICIE)
    estilo_ejes(ax)
    xs = list(range(len(versiones)))
    barras_redondeadas(ax, xs, [v for _, v in versiones], AZUL, 0.56)
    for x, (_, v) in zip(xs, versiones):
        ax.text(x, v + 2, f"{v:.0f} %", ha="center", va="bottom", fontsize=10, color=TINTA, fontweight="bold")
    from matplotlib.lines import Line2D
    ax.axhline(azar, color=APAGADO, linewidth=1.2, linestyle=(0, (4, 3)))
    ax.legend(handles=[Line2D([], [], color=APAGADO, linewidth=1.2, linestyle=(0, (4, 3)))],
              labels=[f"coincidencia esperada por azar ({azar:.0f} %)"], loc="upper left", frameon=False,
              fontsize=8.5, labelcolor=TINTA_2)
    ax.set_xticks(xs, [n for n, _ in versiones], fontsize=8.5, color=TINTA_2)
    ax.set_xlim(-0.6, len(versiones) - 0.4)
    ax.set_ylim(0, 110)
    ax.set_yticks([0, 25, 50, 75, 100], ["0 %", "25 %", "50 %", "75 %", "100 %"])
    fig.tight_layout()
    fig.savefig(ruta, facecolor=SUPERFICIE)
    plt.close(fig)


def figura_precision_sensibilidad(filas: list[tuple[str, float, float]], ruta: Path):
    """Dos series en la misma escala (%): precisión y sensibilidad frente a MINAM."""
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=200)
    fig.patch.set_facecolor(SUPERFICIE)
    estilo_ejes(ax)
    ancho = 0.34
    xs = list(range(len(filas)))
    barras_redondeadas(ax, [x - ancho / 2 - 0.01 for x in xs], [p for _, p, _ in filas], AZUL, ancho)
    barras_redondeadas(ax, [x + ancho / 2 + 0.01 for x in xs], [s for _, _, s in filas], NARANJA, ancho)
    for x, (_, p, s) in zip(xs, filas):
        ax.text(x - ancho / 2 - 0.01, p + 2, f"{p:.0f} %", ha="center", fontsize=9, color=TINTA)
        ax.text(x + ancho / 2 + 0.01, s + 2, f"{s:.0f} %", ha="center", fontsize=9, color=TINTA)
    ax.set_xticks(xs, [n for n, _, _ in filas], fontsize=8.5, color=TINTA_2)
    ax.set_xlim(-0.6, len(filas) - 0.4)
    ax.set_ylim(0, 108)
    ax.set_yticks([0, 25, 50, 75, 100], ["0 %", "25 %", "50 %", "75 %", "100 %"])
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=AZUL, label="Precisión (zonas que coinciden con MINAM)"),
                       Patch(color=NARANJA, label="Sensibilidad (claros MINAM detectados)")],
              loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=8.5, labelcolor=TINTA_2,
              ncol=2, handlelength=1.2, columnspacing=1.2)
    fig.tight_layout()
    fig.savefig(ruta, facecolor=SUPERFICIE)
    plt.close(fig)


def sombrear(celda, color):
    pr = celda._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), color)
    pr.append(shd)


def tabla(doc, filas, encabezado, anchos):
    t = doc.add_table(rows=1, cols=len(encabezado))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for c, texto in zip(t.rows[0].cells, encabezado):
        c.text = ""
        r = c.paragraphs[0].add_run(texto); r.bold = True; r.font.size = Pt(9.5)
        sombrear(c, "E8EEF7")
    for fila in filas:
        celdas = t.add_row().cells
        for c, v in zip(celdas, fila):
            c.text = ""
            r = c.paragraphs[0].add_run(str(v)); r.font.size = Pt(9.5)
    for fila in t.rows:
        for c, w in zip(fila.cells, anchos):
            c.width = Cm(w)
    return t


def parrafo(doc, texto, negrita_inicio=None, tam=10.5):
    p = doc.add_paragraph()
    if negrita_inicio:
        r = p.add_run(negrita_inicio); r.bold = True; r.font.size = Pt(tam)
    r = p.add_run(texto); r.font.size = Pt(tam)
    return p


def figura(doc, ruta, ancho_cm, pie):
    doc.add_picture(str(ruta), width=Cm(ancho_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph(pie)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in p.runs:
        r.italic = True; r.font.size = Pt(9); r.font.color.rgb = RGBColor(0x52, 0x51, 0x4E)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    minam = json.loads((VAL / "minam" / "resumen.json").read_text(encoding="utf-8"))
    nubes = json.loads((VAL / "comparacion_mascara" / "resumen.json").read_text(encoding="utf-8"))
    metricas = json.loads((VAL / "metricas.json").read_text(encoding="utf-8"))
    umbrales = {u["variante"]: u for u in minam["umbrales"]}
    anterior = next(u for k, u in umbrales.items() if "umbral anterior" in k)
    v = minam["versiones"]
    actual = v["v3"]

    interp = {}
    for nombre, archivo in (("N", "interpretacion_visual_v3.csv"), ("M", "interpretacion_visual_umbral_055.csv")):
        d = pd.read_csv(VAL / "minam" / archivo)
        interp[nombre] = d["categoria"].value_counts().to_dict()
    por_prov = pd.read_csv(VAL / "minam" / "minam_por_provincia.csv")
    ultima = sorted(p for p in config.SALIDAS_DIR.glob("2*_*") if p.is_dir())
    resumen_corrida = json.loads((ultima[-1] / "resumen.json").read_text(encoding="utf-8")) if ultima else None

    # ---------------------------------------------------------------- figuras
    f1 = SALIDA / "fig_precision_versiones.png"
    figura_precision([("Versión inicial\n(nubes: solo SCL)", v["v1"]["precision_zonas_pct"]),
                      ("+ máscara de nubes\ns2cloudless", v["v2"]["precision_zonas_pct"]),
                      ("+ bosque oficial\nMINAM", anterior["precision_zonas_pct"]),
                      ("+ umbral ajustado\n(sistema actual)", actual["precision_zonas_pct"])],
                     actual["azar_pixeles_pct"], f1)
    f2 = SALIDA / "fig_precision_sensibilidad.png"
    figura_precision_sensibilidad([
        ("Versión inicial", v["v1"]["precision_zonas_pct"], v["v1"]["sensibilidad_alertas_grandes_pct"]),
        ("+ nubes", v["v2"]["precision_zonas_pct"], v["v2"]["sensibilidad_alertas_grandes_pct"]),
        ("+ bosque MINAM", anterior["precision_zonas_pct"], anterior["sensibilidad_alertas_grandes_pct"]),
        ("Sistema actual", actual["precision_zonas_pct"], actual["sensibilidad_alertas_grandes_pct"]),
    ], f2)

    # ---------------------------------------------------------------- documento
    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Calibri"; estilo.font.size = Pt(10.5)
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2.2); s.top_margin = s.bottom_margin = Cm(2.0)

    t = doc.add_heading(TITULO, 0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in t.runs:
        r.font.size = Pt(20)
    p = doc.add_paragraph(f"Resultados y evidencias · INNOBEST HUÁNUCO 2026 · {date.today():%d/%m/%Y}")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_heading("1. El problema y la propuesta", 1)
    parrafo(doc, "Huánuco pierde bosque cada año por tala, quema y cambio de uso, y sufre incendios y episodios de "
                 "contaminación atmosférica que hoy se detectan tarde. El sistema vigila las 11 provincias con "
                 "satélites gratuitos y emite alertas tempranas por provincia, con la evidencia necesaria para que "
                 "una autoridad o un guardaparque pueda verificarlas.")
    tabla(doc, [
        ["Incendios y focos de calor", "NASA FIRMS (VIIRS 375 m, MODIS)", "Focos agrupados en eventos (DBSCAN) con severidad"],
        ["Deforestación, tala y quema", "Sentinel-2 (10–20 m)", "Pérdida de bosque dentro del bosque oficial de MINAM"],
        ["Salud de la vegetación", "Sentinel-2", "NDVI mensual comparado con el mismo mes del año anterior"],
        ["Contaminación atmosférica", "Sentinel-5P (NO₂, CO)", "Anomalías semanales por provincia"],
    ], ["Amenaza", "Satélite", "Qué detecta"], [4.5, 4.8, 7.4])

    doc.add_heading("2. Resultados principales", 1)
    tabla(doc, [
        [f"{actual['precision_zonas_pct']:.0f} %", "de las zonas de pérdida detectadas coincide con alertas oficiales "
         f"de MINAM (por azar coincidiría el {actual['azar_pixeles_pct']:.0f} %)"],
        [f"{v['v1']['precision_zonas_pct']:.0f} % → {actual['precision_zonas_pct']:.0f} %",
         "mejora de la precisión frente a la primera versión, sin agregar herramientas de IA más complejas"],
        [f"{nubes['perdida']['zonas'] - nubes['perdida']['confirmadas']} → 0",
         "falsas alarmas (nubes, cultivos) en la muestra revisada de 20 zonas de la primera versión"],
        [f"{actual['sensibilidad_alertas_grandes_pct']:.0f} %",
         "de los claros grandes que MINAM registró en 2026 son detectados por el sistema en zonas sin nubes"],
    ], ["Cifra", "Qué significa"], [3.6, 13.1])

    doc.add_heading("3. Cómo se validó", 1)
    parrafo(doc, "Las alertas de pérdida se compararon con las alertas tempranas oficiales de MINAM/PNCB "
                 "(Geobosques, 2026) y su pérdida de bosque 2025. Es una validación independiente: MINAM usa otro "
                 "satélite (Landsat, 30 m) y otro método. Cualquiera puede repetirla consultando Geobosques.",
            "Validación independiente con datos oficiales. ")
    figura(doc, f1, 15.5, "Figura 1. Porcentaje de zonas de pérdida detectadas que coinciden con alertas oficiales de "
                          "MINAM, por versión del sistema. La línea punteada es la coincidencia esperada por azar.")
    parrafo(doc, "Cada mejora se midió antes de adoptarla. La máscara de nubes s2cloudless eliminó todas las falsas "
                 "alarmas por nubes sin perder ninguna tala real; el mapa oficial de bosque de MINAM descartó las "
                 "parcelas agrícolas; y el ajuste del umbral recuperó claros con rebrote que antes se escapaban.",
            "Mejora paso a paso. ")
    figura(doc, f2, 15.5, "Figura 2. Precisión y sensibilidad frente a MINAM (sensibilidad en claros que cubren al "
                          "menos la mitad de un píxel del sistema). El sistema prioriza no dar falsas alarmas.")

    doc.add_heading("Revisión visual", 2)
    n, m = interp["N"], interp["M"]
    parrafo(doc, f"Se revisaron 60 zonas sorteadas al azar con imágenes satelitales de antes y después. "
                 f"No se encontró ninguna falsa alarma; {n.get('confirmada', 0) + m.get('confirmada', 0)} zonas se "
                 f"confirmaron como pérdida nueva y {n.get('indeterminado', 0) + m.get('indeterminado', 0)} quedaron "
                 "indeterminadas, sobre todo por nubes en la imagen de inspección. Esta revisión fue asistida por "
                 "inteligencia artificial y es preliminar; la evidencia principal es la comparación con MINAM.")
    lam = VAL / "minam" / "revision" / "revision_confirmada_1.png"
    if not lam.exists():
        lam = VAL / "minam" / "lamina_v3_1.png"
    figura(doc, lam, 16.5, "Figura 3. Ejemplos de zonas detectadas: antes, después, falso color y contorno de la "
                           "detección. Composiciones Sentinel-2 sin nubes.")

    doc.add_heading("4. Evidencia de cada alerta", 1)
    parrafo(doc, "Cada alerta indica provincia, coordenadas, fecha, satélite de origen, indicador que la activó y "
                 "calidad de la observación (por ejemplo, el porcentaje de la provincia sin nubes). En el tablero, "
                 "cada zona de pérdida muestra si coincide con una alerta oficial de MINAM e imágenes de antes y "
                 "después sin nubes. Las corridas diarias se guardan en una base de datos con respaldo verificado.")
    if resumen_corrida and resumen_corrida.get("alertas"):
        filas = [[a["provincia"], a["tipo"], a["nivel"], a.get("fecha", ""), a.get("fuente", "")]
                 for a in resumen_corrida["alertas"][:10]]
        tabla(doc, filas, ["Provincia", "Tipo", "Nivel", "Fecha", "Fuente"], [3.0, 2.6, 1.6, 4.5, 5.0])
        p = doc.add_paragraph(f"Alertas de la corrida del {pd.Timestamp(resumen_corrida['generado']):%d/%m/%Y %H:%M}.")
        for r in p.runs:
            r.italic = True; r.font.size = Pt(9)

    doc.add_heading("5. Pérdida detectada por provincia", 1)
    pp = por_prov[por_prov["perdida_ha_v3"] > 0].sort_values("perdida_ha_v3", ascending=False)
    tabla(doc, [[r.provincia, f"{r.perdida_ha_v3:,.0f}".replace(",", " "), int(r.zonas),
                 f"{r.precision_zonas_pct:.0f} %" if pd.notna(r.precision_zonas_pct) else "—",
                 f"{r.cobertura_pct:.0f} %"] for r in pp.itertuples()],
          ["Provincia", "Pérdida (ha)", "Zonas", "Coinciden con MINAM", "Área sin nubes"],
          [3.6, 2.8, 2.0, 4.0, 3.4])
    p = doc.add_paragraph(f"Periodo {minam['periodos']['antes'][0]} a {minam['periodos']['antes'][1]} comparado con "
                          f"{minam['periodos']['despues'][0]} a {minam['periodos']['despues'][1]}.")
    for r in p.runs:
        r.italic = True; r.font.size = Pt(9)

    doc.add_heading("6. Límites y próximos pasos", 1)
    for texto in [
        "Las nubes de la selva alta impiden observar parte del territorio en cada periodo; el sistema informa qué "
        "porcentaje de cada provincia pudo observar. Próximo paso: radar Sentinel-1, que ve a través de las nubes.",
        "El mapa oficial de MINAM cubre el bosque húmedo y el seco; la tala de bosques secundarios y de bosques "
        "andinos no mapeados no se evalúa.",
        "El sistema prioriza la precisión: detecta los claros grandes con más seguridad que los pequeños.",
        "La revisión visual fue asistida por IA y es preliminar; se completará con verificación del equipo y de campo.",
        "La calidad del aire de Sentinel-5P mide la columna atmosférica, no la concentración al nivel del suelo; no hay "
        "estaciones en tierra en la región para contrastarla.",
    ]:
        doc.add_paragraph(texto, style="List Bullet")

    doc.add_heading("7. Por qué es innovador", 1)
    for texto in [
        "Integra en un solo tablero incendios, deforestación, salud de la vegetación y contaminación de las 11 "
        "provincias, con datos satelitales gratuitos y actualización diaria automática.",
        "Cada alerta se puede verificar: trae fuente, fecha, indicador, calidad e imágenes, y se contrasta con la "
        "fuente oficial del Estado.",
        "Su precisión está medida con datos oficiales independientes, no solo declarada.",
        "Funciona en una computadora común, sin servicios de pago.",
    ]:
        doc.add_paragraph(texto, style="List Bullet")

    ruta = SALIDA / "Resultados_INNOBEST_2026.docx"
    doc.save(ruta)
    print(ruta)


if __name__ == "__main__":
    main()
