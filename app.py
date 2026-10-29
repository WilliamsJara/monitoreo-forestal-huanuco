"""Tablero interactivo — Sistema inteligente de monitoreo satelital y alerta temprana de contaminación y amenazas forestales en el departamento de Huánuco.

Ejecutar:  .venv\\Scripts\\streamlit run app.py
"""
import base64
import io
import sys
from datetime import date, timedelta
from pathlib import Path

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from branca.element import Element
from folium.plugins import Fullscreen
from PIL import Image
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).parent / "src"))

from huanuco_monitor import alertas as reglas, almacen, config, geo, indicadores, monitor, referencias  # noqa: E402
from huanuco_monitor.copernicus import ClienteCopernicus  # noqa: E402

st.set_page_config(page_title="Monitoreo satelital y alerta temprana — Huánuco", page_icon="🌳", layout="wide")

# Paleta: estados reservados para niveles de alerta (siempre acompañados de etiqueta);
# un único azul para series de magnitud.
COLOR_NIVEL = {"sin alerta": "#c3c2b7", "baja": "#fab219", "media": "#ec835a", "alta": "#d03b3b"}
ICONO_NIVEL = {"sin alerta": "○", "baja": "▲", "media": "▲▲", "alta": "▲▲▲"}
AZUL = "#2a78d6"
FOCO = "#eb6834"
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


# --------------------------------------------------------------------------- datos

faltan = config.credenciales_faltantes()
if faltan:
    st.error(f"Faltan credenciales en el archivo .env: {', '.join(faltan)}")
    st.stop()


@st.cache_resource
def cliente() -> ClienteCopernicus:
    # Espera corta en el tablero: si Copernicus está saturado se muestra enseguida el último análisis guardado
    return ClienteCopernicus(timeout=90, reintentos=2)


# Cada fuente se consulta y se actualiza por separado. `version` cambia al pulsar «Actualizar» para esa
# fuente; `_forzar` (no forma parte de la clave) solo es True en esa ejecución, para que después los
# cambios de filtros reutilicen la caché en disco recién renovada.
@st.cache_resource(ttl=3600, show_spinner=False)
def datos_firms(dias_focos: int, fuentes: tuple[str, ...], version: int, _forzar: bool = False):
    return monitor.datos_firms(dias_focos, list(fuentes), _forzar)


@st.cache_resource(ttl=6 * 3600, show_spinner=False)
def datos_ndvi(version: int, _forzar: bool = False):
    return monitor.datos_ndvi(cliente(), _forzar)


@st.cache_resource(ttl=6 * 3600, show_spinner=False)
def datos_aire(version: int, _forzar: bool = False):
    return monitor.datos_aire(cliente(), _forzar)


@st.cache_resource(ttl=600, show_spinner="Cargando la última corrida guardada…")
def reporte_guardado(carpeta: str) -> monitor.Reporte:
    return monitor.reporte_guardado(carpeta)


@st.cache_data(ttl=600, show_spinner=False)
def historial() -> pd.DataFrame:
    return almacen.historial_alertas()


@st.cache_resource(ttl=30 * 86400, show_spinner=False)
def recorte(lon: float, lat: float, periodo: tuple, tipo: str) -> Image.Image:
    return indicadores.recorte_compuesto(cliente(), lon, lat, periodo, tipo)


@st.cache_resource(ttl=24 * 3600, show_spinner=False)
def cambio(provincia: str, antes: tuple, despues: tuple) -> indicadores.CambioCobertura:
    return indicadores.cambio_cobertura(cliente(), geo.provincias()[provincia], antes, despues)


def ultimo_cambio_guardado(provincia: str, dias: int) -> indicadores.CambioCobertura | None:
    """Análisis de semanas anteriores ya guardado en la caché (hasta 8 semanas atrás), sin conexión."""
    for semanas in range(1, 9):
        hasta = indicadores.inicio_semana() - timedelta(weeks=semanas)
        antes, despues = indicadores.periodos_por_defecto(dias, hasta)
        try:
            return indicadores.cambio_cobertura(cliente(), geo.provincias()[provincia], antes, despues,
                                                solo_cache=True)
        except LookupError:
            continue
    return None


@st.cache_resource(ttl=24 * 3600, show_spinner=False)
def color_real(provincia: str) -> tuple[str, tuple]:
    # Solo desde la caché (la prepara la corrida programada): el tablero nunca espera por la imagen de fondo
    png, bbox = indicadores.imagen_color_real(cliente(), geo.provincias()[provincia], solo_cache=True)
    img = Image.open(io.BytesIO(png))
    img.thumbnail((1000, 1000))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), bbox


def coincide_minam(cc: indicadores.CambioCobertura, zonas: pd.DataFrame) -> list[str]:
    """Para cada zona: ¿hay alerta temprana MINAM 2026 o pérdida 2025 en su celda (±1 píxel)?"""
    if zonas.empty:
        return []
    try:
        args = (cc.bbox, *cc.dentro.shape[::-1])
        ref = (referencias.fraccion("alertas_2026", *args) > 0) | (referencias.fraccion("perdida_2025", *args) > 0)
    except Exception:
        return ["sin conexión"] * len(zonas)
    x0, y0, x1, y1 = cc.bbox
    h, w = ref.shape
    salida = []
    for z in zonas.itertuples():
        i, j = int((y1 - z.latitud) / (y1 - y0) * h), int((z.longitud - x0) / (x1 - x0) * w)
        salida.append("sí" if ref[max(i - 9, 0):i + 10, max(j - 9, 0):j + 10].any() else "no")
    return salida


# --------------------------------------------------------------------------- mapas

def mapa_base(bbox=None, zoom=8) -> folium.Map:
    x0, y0, x1, y1 = bbox or geo.bbox_region()
    m = folium.Map(location=[(y0 + y1) / 2, (x0 + x1) / 2], zoom_start=zoom, tiles=None, control_scale=True,
                   prefer_canvas=True)
    folium.TileLayer(ESRI, attr="Esri World Imagery", name="Imagen satelital (Esri)").add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False).add_to(m)
    Fullscreen().add_to(m)
    m.fit_bounds([[y0, x0], [y1, x1]])
    return m


def capa_provincias(m, niveles: dict[str, str] | None = None, resaltar: str | None = None):
    feats = []
    for p in geo.provincias().values():
        nivel = (niveles or {}).get(p.nombre, "sin alerta")
        feats.append({"type": "Feature", "geometry": p.geojson,
                      "properties": {"provincia": p.nombre, "nivel": f"{ICONO_NIVEL[nivel]} {nivel}",
                                     "_color": COLOR_NIVEL[nivel] if niveles else "#ffffff",
                                     "_resaltar": p.nombre == resaltar}})
    folium.GeoJson(
        {"type": "FeatureCollection", "features": feats},
        name="Provincias",
        style_function=lambda f: {
            "fillColor": f["properties"]["_color"],
            "fillOpacity": 0.35 if niveles else 0.0,
            "color": "#ffffff",
            "weight": 3 if f["properties"]["_resaltar"] else 1.2,
        },
        highlight_function=lambda f: {"weight": 3, "fillOpacity": 0.5},
        tooltip=folium.GeoJsonTooltip(["provincia", "nivel"], aliases=["Provincia", "Alerta"]),
    ).add_to(m)


def capa_focos(m, focos: pd.DataFrame, eventos: pd.DataFrame):
    if focos.empty:
        return
    grupo = folium.FeatureGroup(name=f"Focos de calor ({len(focos)})")
    for r in focos.itertuples():
        folium.CircleMarker(
            [r.latitud, r.longitud], radius=4 + min(r.frp, 100) / 20, color="#ffffff", weight=1,
            fill=True, fill_color=FOCO, fill_opacity=0.9,
            tooltip=(f"<b>{r.provincia}</b><br>{r.fecha:%d/%m/%Y} {r.hora} UTC · {r.dia_noche}<br>"
                     f"{config.FIRMS_FUENTES.get(r.fuente, r.fuente)}<br>"
                     f"FRP {r.frp:.1f} MW · confianza {r.confianza}"),
        ).add_to(grupo)
    grupo.add_to(m)
    if not eventos.empty:
        capa = folium.FeatureGroup(name=f"Eventos de incendio ({len(eventos)})")
        for e in eventos.itertuples():
            folium.Circle(
                [e.latitud, e.longitud], radius=500 + 400 * e.focos ** 0.5,
                color=COLOR_NIVEL[e.severidad], weight=2.5, fill=False,
                tooltip=(f"<b>Evento {e.evento} · severidad {e.severidad}</b><br>{e.provincia}<br>"
                         f"{e.focos} focos · FRP total {e.frp_total_mw:.0f} MW<br>"
                         f"{e.inicio:%d/%m} → {e.ultimo:%d/%m} ({e.dias_activo} días)"),
            ).add_to(capa)
        capa.add_to(m)


def leyenda(m, filas: list[tuple[str, str]], titulo: str):
    items = "".join(
        f'<div><span style="display:inline-block;width:12px;height:12px;border-radius:3px;'
        f'background:{c};margin-right:6px;vertical-align:middle"></span>{t}</div>' for c, t in filas)
    m.get_root().html.add_child(Element(
        f'<div style="position:fixed;bottom:24px;left:12px;z-index:9999;background:rgba(252,252,251,.94);'
        f'color:#0b0b0b;padding:8px 10px;border-radius:6px;font:12px/1.6 sans-serif;'
        f'box-shadow:0 1px 4px rgba(0,0,0,.3)"><b>{titulo}</b>{items}</div>'))


def mostrar_mapa(m, alto=560, clave=None):
    folium.LayerControl(collapsed=True).add_to(m)  # plegado: en celular no tapa el mapa
    st_folium(m, height=alto, use_container_width=True, returned_objects=[], key=clave)


# --------------------------------------------------------------------------- gráficos

def figura_linea(df: pd.DataFrame, x: str, y: str, titulo_y: str, formato: str, texto_hover: str):
    fig = go.Figure(go.Scatter(
        x=df[x], y=df[y], mode="lines+markers", connectgaps=False,
        line=dict(color=AZUL, width=2), marker=dict(size=8, color=AZUL, line=dict(color="#fcfcfb", width=2)),
        hovertemplate=f"%{{x|%d %b %Y}}<br>{texto_hover}: %{{y:{formato}}}<extra></extra>",
    ))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified",
                      yaxis_title=titulo_y, xaxis_title=None, showlegend=False)
    fig.update_xaxes(showgrid=False)
    return fig


def figura_barras(serie: pd.Series, titulo_x: str):
    serie = serie.sort_values()
    fig = go.Figure(go.Bar(
        x=serie.values, y=serie.index, orientation="h", marker=dict(color=AZUL, cornerradius=4),
        text=serie.values, textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    fig.update_layout(height=40 + 30 * len(serie), margin=dict(l=10, r=40, t=10, b=10),
                      xaxis_title=titulo_x, bargap=0.25, showlegend=False)
    fig.update_yaxes(showgrid=False)
    return fig


# --------------------------------------------------------------------------- interfaz

BADGE_NIVEL = {"alta": "red", "media": "orange", "baja": "yellow", "sin alerta": "gray"}
ICONO_TIPO = {"incendio": ":material/local_fire_department:", "deforestación": ":material/forest:",
              "vegetación": ":material/eco:", "aire": ":material/air:"}

# Modo «guardado»: el tablero abre en segundos con la última corrida programada (sin consultar satélites
# ni gastar cuota). Modo «vivo»: consulta cada fuente (con su caché y respaldo).
ultima = almacen.ultima_corrida()
hay_guardada = bool(ultima and ultima["carpeta"] and (Path(ultima["carpeta"]) / "resumen.json").exists())
st.session_state.setdefault("modo", "guardado" if hay_guardada else "vivo")
for k in ("firms", "ndvi", "aire"):
    st.session_state.setdefault(f"version_{k}", 0)


def a_vivo():
    st.session_state.modo = "vivo"


st.sidebar.title(":material/satellite_alt: Monitoreo y alerta")
st.sidebar.caption("Departamento de Huánuco · 11 provincias")
seccion = st.sidebar.radio(
    "Sección",
    ["Panorama y alertas", "Incendios y focos de calor", "Deforestación y recuperación",
     "Cobertura vegetal (NDVI)", "Calidad del aire"],
)
st.sidebar.divider()
forzar = set()
if st.session_state.modo == "guardado":
    st.sidebar.caption(f"Datos de la corrida programada del **{pd.Timestamp(ultima['generado']):%d/%m/%Y %H:%M}**")
    st.sidebar.button("Consultar satélites ahora", icon=":material/refresh:", width="stretch", on_click=a_vivo)
elif st.sidebar.button("Actualizar datos satelitales", icon=":material/refresh:", width="stretch"):
    forzar = {"firms", "ndvi", "aire"}
with st.sidebar.expander("Opciones avanzadas", icon=":material/tune:"):
    dias_focos = st.slider("Días de focos de calor", 1, 30, 7, on_change=a_vivo)
    fuentes = st.multiselect("Sensores FIRMS", list(config.FIRMS_FUENTES), default=list(config.FIRMS_FUENTES),
                             format_func=config.FIRMS_FUENTES.get, on_change=a_vivo)
    if st.session_state.modo == "vivo":
        st.caption("Actualizar una sola fuente")
        for k in ("firms", "ndvi", "aire"):
            if st.button(monitor.FUENTES[k], key=f"actualizar_{k}", width="stretch"):
                forzar.add(k)
        if hay_guardada:
            st.button("Volver a la última corrida guardada", icon=":material/history:", width="stretch",
                      on_click=lambda: st.session_state.update(modo="guardado"))
for k in forzar:
    st.session_state[f"version_{k}"] += 1

if st.session_state.modo == "guardado":
    rep = reporte_guardado(ultima["carpeta"])
    dias_focos = ultima.get("dias_focos") or 7
else:
    with st.spinner("Consultando NASA FIRMS, Sentinel-2 y Sentinel-5P… (la primera carga puede tardar unos minutos)"):
        rep = monitor.componer(
            datos_firms(dias_focos, tuple(fuentes or config.FIRMS_FUENTES), st.session_state.version_firms,
                        "firms" in forzar),
            datos_ndvi(st.session_state.version_ndvi, "ndvi" in forzar),
            datos_aire(st.session_state.version_aire, "aire" in forzar),
        )

with st.sidebar.expander("Actualización de cada fuente", icon=":material/schedule:"):
    for n, e in rep.fuentes.items():
        st.caption(f"{'⚠ ' if e.respaldo else ''}{monitor.FUENTES[n]}: {e.descripcion}")
if rep.errores:
    with st.sidebar.expander(f"⚠ {len(rep.errores)} consulta{'s' if len(rep.errores) > 1 else ''} con error"):
        for e in rep.errores:
            st.caption(e)

nombres = list(geo.provincias())

if seccion == "Panorama y alertas":
    st.header("Sistema inteligente de monitoreo satelital y alerta temprana de contaminación y amenazas "
              "forestales en el departamento de Huánuco")
    niveles = rep.niveles
    tabla = rep.tabla_alertas
    ndvi_ult = (rep.ndvi.dropna(subset=["media"]).sort_values("desde").groupby("provincia")["media"].last()
                if not rep.ndvi.empty else pd.Series(dtype=float))
    # Contenedor horizontal: 4 indicadores en una fila en pantalla ancha, 2 por fila en celular
    with st.container(horizontal=True, gap="small"):
        for etiqueta, valor in [(f"Focos de calor ({dias_focos} d)", f"{len(rep.focos):,}"),
                                ("Eventos de incendio", len(rep.eventos)),
                                ("Provincias en alta", sum(v == "alta" for v in niveles.values())),
                                ("NDVI (último mes)", f"{ndvi_ult.mean():.2f}" if len(ndvi_ult) else "—")]:
            st.metric(etiqueta, valor, border=True, width=165)

    # 1. Resumen territorial: una tarjeta por provincia, de mayor a menor alerta (en celular se apilan)
    st.subheader("Resumen por provincia")
    conteo = tabla.groupby(["provincia", "tipo"]).size() if not tabla.empty else pd.Series(dtype=int)
    with st.container(horizontal=True, gap="small"):
        for prov in sorted(nombres, key=lambda n: (-reglas.ORDEN[niveles[n]], n)):
            nivel = niveles[prov]
            with st.container(border=True, width=170):
                st.markdown(f"**{prov}**  \n:{BADGE_NIVEL[nivel]}-badge[{ICONO_NIVEL[nivel]} {nivel}]")
                tipos = [f"{ICONO_TIPO[t]} {conteo.get((prov, t), 0)}" for t in ICONO_TIPO
                         if conteo.get((prov, t), 0)]
                st.caption(" · ".join(tipos) if tipos else "sin alertas")

    # 2. Alertas prioritarias: primero las de nivel alto, con su evidencia resumida
    st.subheader("Alertas prioritarias")
    if tabla.empty:
        st.success("Sin alertas activas en el periodo.")
    else:
        prioritarias = tabla[tabla["nivel"] == "alta"]
        prioritarias = prioritarias if len(prioritarias) else tabla
        with st.container(horizontal=True, gap="small"):
            for r in prioritarias.head(6).itertuples():
                with st.container(border=True, width=360):
                    st.markdown(f":{BADGE_NIVEL[r.nivel]}-badge[{r.nivel}] **{r.provincia}** · "
                                f"{ICONO_TIPO.get(r.tipo, '')} {r.tipo}")
                    st.markdown(r.mensaje)
                    st.caption(" · ".join(x for x in (r.fecha, r.fuente, r.calidad) if x))
        if len(prioritarias) > 6 or len(tabla) > len(prioritarias):
            st.caption(f"{len(tabla)} alertas en total: ver la tabla completa más abajo.")

    # 3. Mapa
    st.subheader("Mapa de alertas")
    m = mapa_base()
    capa_provincias(m, niveles)
    capa_focos(m, rep.focos, rep.eventos)
    leyenda(m, [(COLOR_NIVEL[n], f"{ICONO_NIVEL[n]} {n}") for n in ["alta", "media", "baja", "sin alerta"]]
            + [(FOCO, "foco de calor (tamaño = FRP)")], "Nivel de alerta")
    mostrar_mapa(m, 480, "mapa_panorama")

    if not tabla.empty:
        with st.expander("Todas las alertas con su evidencia: fuente, fecha, indicador, calidad y ubicación"):
            st.dataframe(tabla.drop(columns="valor"), hide_index=True, width="stretch",
                         column_config={"mensaje": st.column_config.TextColumn("detalle", width="large"),
                                        "latitud": st.column_config.NumberColumn(format="%.5f"),
                                        "longitud": st.column_config.NumberColumn(format="%.5f")})
            st.download_button("Descargar alertas con evidencia (CSV)", tabla.to_csv(index=False).encode("utf-8"),
                               "alertas_huanuco.csv", "text/csv", icon=":material/download:")
    hist = historial()
    with st.expander("Historial de alertas (corridas programadas guardadas en la base de datos)"):
        if hist.empty:
            st.caption("Aún no hay corridas guardadas: se registran al ejecutar scripts\\actualizar.py.")
        else:
            serie = hist.groupby(["generado", "nivel"])["alertas"].sum().unstack(fill_value=0)
            fig = go.Figure()
            for n in ["alta", "media", "baja"]:
                if n in serie:
                    fig.add_bar(x=serie.index, y=serie[n], name=n, marker_color=COLOR_NIVEL[n])
            fig.update_layout(barmode="stack", height=300, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="alertas", legend_title_text="nivel")
            st.plotly_chart(fig, width="stretch")
    st.caption("Pérdida de cobertura: el detalle por zona se calcula en «Deforestación y recuperación».")

elif seccion == "Incendios y focos de calor":
    st.title("Incendios forestales y focos de calor")
    st.caption("NASA FIRMS (VIIRS 375 m y MODIS 1 km). Los focos a menos de "
               f"{config.DBSCAN_EPS_KM} km se agrupan en eventos con DBSCAN (≥ {config.DBSCAN_MIN_FOCOS} focos).")
    focos, eventos = rep.focos, rep.eventos
    if focos.empty:
        st.info("No se detectaron focos de calor en el periodo seleccionado.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Focos de calor", f"{len(focos):,}")
        c2.metric("Confianza alta", f"{(focos['confianza'] == 'alta').sum():,}")
        c3.metric("Eventos agrupados", len(eventos))
        c4.metric("Potencia radiativa total", f"{focos['frp'].sum():,.0f} MW")
        m = mapa_base()
        capa_provincias(m)
        capa_focos(m, focos, eventos)
        leyenda(m, [(FOCO, "foco de calor"), (COLOR_NIVEL["alta"], "evento severidad alta"),
                    (COLOR_NIVEL["media"], "evento severidad media"),
                    (COLOR_NIVEL["baja"], "evento severidad baja")], "Incendios")
        mostrar_mapa(m, 560, "mapa_incendios")
        a, b = st.columns(2)
        with a:
            st.subheader("Focos por provincia")
            st.plotly_chart(figura_barras(focos.groupby("provincia").size(), "focos de calor"),
                            width="stretch")
        with b:
            st.subheader("Focos por día")
            diario = focos.groupby("fecha").size().rename("focos").reset_index()
            st.plotly_chart(figura_linea(diario, "fecha", "focos", "focos de calor", ",d", "Focos"),
                            width="stretch")
        st.subheader("Eventos de incendio")
        if eventos.empty:
            st.caption("Ningún grupo de focos alcanzó el mínimo para considerarse evento.")
        else:
            tabla_ev = eventos.drop(columns=["evento"])
            numericas = tabla_ev.select_dtypes("number").columns  # las fechas no se redondean
            tabla_ev[numericas] = tabla_ev[numericas].round(3)
            st.dataframe(tabla_ev, hide_index=True, width="stretch")
        with st.expander("Tabla de focos de calor"):
            st.dataframe(focos.drop(columns=["evento"]), hide_index=True, width="stretch")
            st.download_button("Descargar CSV", focos.to_csv(index=False).encode("utf-8"),
                               "focos_calor_huanuco.csv", "text/csv")

elif seccion == "Deforestación y recuperación":
    st.title("Deforestación, tala y recuperación de la cobertura vegetal")
    st.caption("Sentinel-2 L2A: mediana de NDVI por píxel (sin nubes ni sombras) en dos periodos. "
               f"Pérdida = bosque (NDVI ≥ {config.NDVI_BOSQUE}) con caída ≥ {config.CAIDA_NDVI_DEFORESTACION}. "
               f"Recuperación = área degradada (NDVI ≤ {config.NDVI_DEGRADADO}) con aumento ≥ "
               f"{config.GANANCIA_NDVI_RECUPERACION}. Por defecto compara con el mismo periodo del año anterior "
               "para no confundir la estacionalidad con deforestación. La pérdida se evalúa solo dentro del bosque "
               "oficial de MINAM (Geobosques) y la recuperación solo donde hubo bosque, para no confundir cultivos, "
               "pastos ni orillas de río con bosque.")
    a, b, c = st.columns([2, 2, 1])
    prov = a.selectbox("Provincia", nombres, index=nombres.index("Puerto Inca"))
    dias = b.select_slider("Duración de cada periodo", [30, 60, 90, 120, 180], value=90,
                           format_func=lambda d: f"{d} días")
    antes, despues = indicadores.periodos_por_defecto(dias)
    b.caption(f"Antes: {antes[0]:%d/%m/%Y}–{antes[1]:%d/%m/%Y} · Después: {despues[0]:%d/%m/%Y}–{despues[1]:%d/%m/%Y}")
    c.write("")
    calcular = c.button("Analizar", type="primary", width="stretch")
    clave = (prov, antes, despues)
    if calcular:
        st.session_state.cambio = clave
    if st.session_state.get("cambio") != clave:
        st.info("Elige la provincia y pulsa **Analizar** (≈ 1 minuto por provincia la primera vez).")
    else:
        with st.spinner(f"Procesando imágenes Sentinel-2 de {prov}…"):
            try:
                cc = cambio(*clave)
            except Exception as e:  # Copernicus saturado, sin cuota o sin internet
                cc = ultimo_cambio_guardado(prov, dias)
                if cc is None:
                    st.error(f"No se pudo consultar Copernicus y no hay un análisis anterior guardado de {prov}: {e}")
                    st.stop()
                st.warning(f"Copernicus no respondió ({type(e).__name__}). Se muestra el último análisis guardado: "
                           f"{cc.antes[0]:%d/%m/%Y}–{cc.antes[1]:%d/%m/%Y} vs. "
                           f"{cc.despues[0]:%d/%m/%Y}–{cc.despues[1]:%d/%m/%Y}.", icon=":material/history:")
            try:
                url_color, bbox_color = color_real(prov)
            except Exception:  # la imagen de fondo es opcional: el mapa usa la imagen satelital de Esri
                url_color = bbox_color = None
        r = cc.resumen()
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Posible pérdida forestal", f"{r['perdida_ha']:,.0f} ha")
        k2.metric("Indicios de recuperación", f"{r['recuperacion_ha']:,.0f} ha")
        k3.metric("Área observable sin nubes", f"{r['cobertura_pct']:.0f} %")
        k4.metric("Resolución de análisis", f"{r['res_m']} m")
        if "no disponible" in r["mascara_bosque"]:
            st.warning(f"Sin máscara de bosque: {r['mascara_bosque']}. La pérdida puede incluir cambios agrícolas.")
        else:
            st.caption(f"Máscara de bosque: {r['mascara_bosque']}.")
        if r["cobertura_pct"] < 40:
            st.warning("Menos del 40 % de la provincia tuvo observaciones despejadas en ambos periodos: "
                       "amplía la duración del periodo para mejorar la cobertura.")
        x0, y0, x1, y1 = cc.bbox
        m = mapa_base(cc.bbox)
        if url_color:
            folium.raster_layers.ImageOverlay(url_color, bounds=[[bbox_color[1], bbox_color[0]],
                                                                 [bbox_color[3], bbox_color[2]]],
                                              name="Sentinel-2 color real (reciente)", opacity=1).add_to(m)
        folium.raster_layers.ImageOverlay(cc.imagen_rgba(), bounds=[[y0, x0], [y1, x1]],
                                          name="Cambio de cobertura", mercator_project=True).add_to(m)
        for servicio, capa_wms, nombre in (("bosque_humedo_2024", "1", "MINAM: bosque al 2024"),
                                           ("alertas_tempranas_2026", "0", "MINAM: alertas tempranas 2026")):
            folium.raster_layers.WmsTileLayer(
                url=f"{config.GEOBOSQUES_URL}/{servicio}/MapServer/WMSServer", layers=capa_wms, fmt="image/png",
                transparent=True, name=nombre, show=False, attr="MINAM / PNCB — Geobosques").add_to(m)
        capa_provincias(m, resaltar=prov)
        perdida = cc.focos_cambio(cc.perdida)
        perdida["alerta MINAM"] = coincide_minam(cc, perdida)
        recup = cc.focos_cambio(cc.recuperacion)
        capa = folium.FeatureGroup(name="Zonas prioritarias de pérdida (top 25)")
        for z in perdida.head(25).itertuples():
            folium.CircleMarker([z.latitud, z.longitud], radius=9, color=COLOR_NIVEL["alta"], weight=2.5,
                                fill=False, tooltip=f"Posible pérdida: {z.hectareas} ha<br>"
                                                    f"{z.latitud:.5f}, {z.longitud:.5f}").add_to(capa)
        capa.add_to(m)
        leyenda(m, [("#d03b3b", "posible pérdida (tala / quema)"), ("#0ca30c", "indicio de recuperación")],
                "Cambio de cobertura")
        mostrar_mapa(m, 620, f"mapa_cambio_{prov}")
        t1, t2 = st.columns(2)
        with t1:
            st.subheader("Zonas de pérdida")
            st.dataframe(perdida.round(5), hide_index=True, width="stretch", height=300)
        with t2:
            st.subheader("Zonas en recuperación")
            st.dataframe(recup.round(5), hide_index=True, width="stretch", height=300)
        if not perdida.empty:
            st.subheader("Evidencia de una zona: antes y después")
            top = perdida.head(25).reset_index(drop=True)
            i = st.selectbox("Zona", top.index, format_func=lambda k: (
                f"{top.hectareas[k]} ha · {top.latitud[k]:.5f}, {top.longitud[k]:.5f} · "
                f"alerta MINAM: {top['alerta MINAM'][k]}"))
            z = top.loc[i]
            with st.spinner("Generando imágenes sin nubes…"):
                imgs = [recorte(float(z.longitud), float(z.latitud), cc.antes, "color"),
                        recorte(float(z.longitud), float(z.latitud), cc.despues, "color"),
                        recorte(float(z.longitud), float(z.latitud), cc.despues, "falso")]
            for col, im, titulo in zip(st.columns(3), imgs, [
                    f"Antes ({cc.antes[0]:%m/%Y}–{cc.antes[1]:%m/%Y})",
                    f"Después ({cc.despues[0]:%m/%Y}–{cc.despues[1]:%m/%Y})", "Después, falso color"]):
                col.image(im, caption=titulo, width="stretch")
            st.caption("Composición sin nubes (mediana de las pasadas despejadas), ~1,3 km de lado, centrada en "
                       "la zona. En falso color el bosque es verde oscuro y el suelo desnudo o quemado, rosado o "
                       "marrón. Blanco = sin ninguna observación despejada.")

elif seccion == "Cobertura vegetal (NDVI)":
    st.title("Salud de la cobertura vegetal (NDVI)")
    st.caption(f"Sentinel-2 L2A, NDVI medio mensual de píxeles despejados (~220 m), últimos {config.NDVI_MESES} "
               "meses. Los meses con menos del 5 % de la provincia sin nubes se omiten. La alerta compara el "
               "último mes con el mismo periodo del año anterior, para no confundir la estación seca con daño.")
    if rep.ndvi.empty:
        st.warning("No hay datos de NDVI disponibles.")
    else:
        prov = st.selectbox("Provincia", nombres, index=nombres.index("Puerto Inca"))
        serie = rep.ndvi[rep.ndvi["provincia"] == prov].sort_values("desde")
        st.plotly_chart(figura_linea(serie, "desde", "media", "NDVI medio", ".2f", "NDVI"),
                        width="stretch")
        st.subheader("Resumen por provincia")
        g = rep.ndvi.dropna(subset=["media"]).groupby("provincia")["media"]
        comp = reglas.comparacion_ndvi(rep.ndvi).set_index("provincia")
        resumen = pd.DataFrame({
            "Último mes válido": pd.to_datetime(comp["fecha"]).dt.strftime("%d/%m/%Y"),
            "NDVI último mes": comp["ndvi"],
            "Mismo periodo año anterior": comp["ndvi_anio_anterior"],
            "Caída": comp["caida"],
            "Mínimo": g.min(),
            "Máximo": g.max(),
        })
        st.dataframe(resumen.round(3), width="stretch")
        st.caption(f"Alerta media si la caída es ≥ {config.CAIDA_NDVI_MEDIO}; alta si es ≥ {config.CAIDA_NDVI_ALTO}. "
                   "Sin valor del año anterior = no hubo meses despejados comparables.")

elif seccion == "Calidad del aire":
    st.title("Contaminación atmosférica (Sentinel-5P TROPOMI)")
    st.caption("Columnas semanales de NO₂ troposférico y CO total. La anomalía z compara la última semana "
               f"válida con las anteriores: z ≥ {config.AIRE_Z_MEDIO} → alerta media, "
               f"z ≥ {config.AIRE_Z_ALTO} → alta. Picos de CO suelen coincidir con quemas.")
    if rep.aire.empty:
        st.warning("No hay datos de Sentinel-5P disponibles.")
    else:
        a, b = st.columns(2)
        cont = a.radio("Contaminante", list(indicadores.CONTAMINANTES), horizontal=True,
                       format_func=lambda c: indicadores.CONTAMINANTES[c][0])
        prov = b.selectbox("Provincia", nombres, index=nombres.index("Puerto Inca"))
        nombre, unidad, _ = indicadores.CONTAMINANTES[cont]
        serie = rep.aire[(rep.aire["provincia"] == prov) & (rep.aire["contaminante"] == cont)].sort_values("desde")
        st.plotly_chart(figura_linea(serie, "desde", "media", f"{cont} ({unidad})", ".1f", cont),
                        width="stretch")
        st.subheader("Anomalías por provincia")
        an = rep.anomalias_aire[rep.anomalias_aire["contaminante"] == cont]
        st.dataframe(an.rename(columns={"ultimo": f"última semana ({unidad})", "z": "anomalía z"})
                     .drop(columns=["unidad"]).round(2), hide_index=True, width="stretch")

st.sidebar.divider()
st.sidebar.caption("Fuentes: NASA FIRMS · Copernicus Sentinel-2 L2A y Sentinel-5P (Copernicus Data Space) · "
                   "límites geoBoundaries · mapa base Esri.")
