"""Validación de los resultados: integridad, sensibilidad, coincidencia con incendios y muestras visuales.

    .venv\\Scripts\\python scripts\\validar.py

Genera en `salidas/validacion/` las métricas (JSON/CSV) y láminas de imágenes Sentinel-2
antes/después de zonas elegidas al azar, para verificación por fotointerpretación.
"""
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from sklearn.neighbors import BallTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from huanuco_monitor import cache, config, firms, geo, indicadores  # noqa: E402
from huanuco_monitor.copernicus import ClienteCopernicus  # noqa: E402

SALIDA = config.SALIDAS_DIR / "validacion"
SEMILLA = 42
CHIP_GRADOS = 0.006   # semiancho de la ventana de inspección (~1,3 km de lado)
CHIP_PX = 220

EVAL_CHIP = """//VERSION=3
function setup() { return { input: [{ bands: ["B02", "B03", "B04", "dataMask"] }], output: { bands: 3 } }; }
function evaluatePixel(s) { var g = 3.2; return [g * s.B04, g * s.B03, g * s.B02]; }
"""
EVAL_SWIR = """//VERSION=3
function setup() { return { input: [{ bands: ["B04", "B8A", "B12", "dataMask"] }], output: { bands: 3 } }; }
function evaluatePixel(s) { return [2.5 * s.B12, 2.5 * s.B8A, 2.5 * s.B04]; }
"""


def chip(cliente, lon, lat, periodo, evalscript=EVAL_CHIP, semiancho=CHIP_GRADOS, px=CHIP_PX) -> Image.Image:
    bbox = [lon - semiancho, lat - semiancho, lon + semiancho, lat + semiancho]
    payload = {
        "input": {
            "bounds": {"bbox": bbox, "properties": {"crs": config.CRS84}},
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {
                "timeRange": {"from": f"{periodo[0]}T00:00:00Z", "to": f"{periodo[1]}T23:59:59Z"},
                "mosaickingOrder": "leastCC"}}],
        },
        "output": {"width": px, "height": px,
                   "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
        "evalscript": evalscript,
    }
    png = cache.memo(("chip", evalscript, bbox, periodo, px), 30 * 86400, lambda: cliente.procesar(payload))
    return Image.open(io.BytesIO(png)).convert("RGB")


def superponer_mascara(img: Image.Image, cc: indicadores.CambioCobertura, mascara, lon, lat, color):
    """Dibuja sobre `img` los píxeles detectados por el sistema dentro de la ventana."""
    x0, y0, x1, y1 = cc.bbox
    h, w = mascara.shape
    c0 = int((lon - CHIP_GRADOS - x0) / (x1 - x0) * w)
    c1 = int(np.ceil((lon + CHIP_GRADOS - x0) / (x1 - x0) * w))
    f0 = int((y1 - (lat + CHIP_GRADOS)) / (y1 - y0) * h)
    f1 = int(np.ceil((y1 - (lat - CHIP_GRADOS)) / (y1 - y0) * h))
    sub = np.zeros((f1 - f0, c1 - c0), dtype=bool)
    fs, cs = slice(max(f0, 0), min(f1, h)), slice(max(c0, 0), min(c1, w))
    sub[fs.start - f0:fs.stop - f0, cs.start - c0:cs.stop - c0] = mascara[fs, cs]
    capa = Image.fromarray((sub * 255).astype(np.uint8)).resize(img.size, Image.NEAREST)
    resultado = img.copy()
    resultado.paste(Image.new("RGB", img.size, color), mask=capa.point(lambda v: 150 if v else 0))
    return resultado


def lamina(filas, titulo, ruta):
    """filas: lista de (etiqueta, [imágenes]) → lámina PNG con 3 columnas."""
    try:
        fuente = ImageFont.truetype("arial.ttf", 15)
    except OSError:
        fuente = ImageFont.load_default(size=15)
    ancho = 3 * CHIP_PX + 4 * 8
    alto_fila = CHIP_PX + 30
    hoja = Image.new("RGB", (ancho, 40 + len(filas) * alto_fila), "white")
    d = ImageDraw.Draw(hoja)
    d.text((8, 10), titulo, fill="black", font=fuente)
    for i, (etiqueta, imgs) in enumerate(filas):
        y = 40 + i * alto_fila
        d.text((8, y), etiqueta, fill="black", font=fuente)
        for j, im in enumerate(imgs):
            hoja.paste(im, (8 + j * (CHIP_PX + 8), y + 22))
    hoja.save(ruta)


def mascara_perdida(cc, bosque, caida, max_tras, vecinos, min_obs):
    with np.errstate(invalid="ignore"):
        base = (cc.dentro & ~np.isnan(cc.ndvi_antes) & ~np.isnan(cc.ndvi_despues)
                & (cc.observaciones >= min_obs) & (cc.ndvi_antes >= bosque)
                & (cc.delta <= -caida) & (cc.ndvi_despues <= max_tras))
    if vecinos == 0:
        return base
    p = np.pad(base.astype(np.uint8), 1)
    h, w = base.shape
    n = sum(p[1 + a:1 + a + h, 1 + b:1 + b + w] for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b)
    return base & (n >= vecinos)


def focos_periodo(desde: date, hasta: date) -> pd.DataFrame:
    """Focos VIIRS (375 m) de un periodo arbitrario, en ventanas de 5 días."""
    bbox = geo.bbox_region()
    partes, inicio = [], desde
    while inicio <= hasta:
        n = min(5, (hasta - inicio).days + 1)
        for f in ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]:
            try:
                partes.append(cache.memo(("firms", f, inicio, n, bbox), 7 * 86400,
                                         lambda f=f, i=inicio, n=n: firms._descargar(f, n, i, bbox)))
            except RuntimeError:
                pass  # periodos fuera del rango NRT de un sensor
        inicio += timedelta(days=n)
    df = pd.concat([p for p in partes if not p.empty], ignore_index=True)
    df["provincia"] = geo.asignar_provincia(df["longitud"].to_numpy(), df["latitud"].to_numpy())
    return df.dropna(subset=["provincia"])


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    cliente = ClienteCopernicus()
    provs = geo.provincias()
    metricas = {}

    # ------------------------------------------------------------------ 1. FIRMS
    print("1/5 Focos de calor…", flush=True)
    focos = firms.focos_de_calor(7)
    focos_ev, eventos = firms.agrupar_eventos(focos)
    # Detecciones de distintos satélites sobre el mismo fuego: se cuentan una vez por día y celda de ~400 m
    celdas = focos.assign(cx=(focos["longitud"] / 0.004).round(), cy=(focos["latitud"] / 0.004).round())
    unicos = celdas.drop_duplicates(["fecha", "cx", "cy"])
    metricas["firms"] = {
        "detecciones": len(focos),
        "detecciones_unicas_dia_celda_400m": len(unicos),
        "por_sensor": focos["fuente"].value_counts().to_dict(),
        "por_confianza": focos["confianza"].value_counts().to_dict(),
        "por_dia_noche": focos["dia_noche"].value_counts().to_dict(),
        "eventos_dbscan": len(eventos),
        "focos_en_eventos_pct": round(100 * (focos_ev["evento"] >= 0).mean(), 1),
        "eventos_por_severidad": eventos["severidad"].value_counts().to_dict() if len(eventos) else {},
    }

    # ------------------------------------------------------------------ 2. Cambio de cobertura
    print("2/5 Cambio de cobertura (desde caché)…", flush=True)
    antes, despues = indicadores.periodos_por_defecto()
    cambios = {n: indicadores.cambio_cobertura(cliente, p, antes, despues) for n, p in provs.items()}
    resumen = pd.DataFrame([c.resumen() for c in cambios.values()])
    resumen["area_km2"] = resumen["provincia"].map(lambda n: round(provs[n].area_km2))
    resumen["perdida_extrapolada_ha"] = (resumen["perdida_ha"] / (resumen["cobertura_pct"] / 100)).round()
    resumen.to_csv(SALIDA / "cambio_cobertura_resumen.csv", index=False)

    variantes = []
    for etiqueta, kw in {
        "sistema (por defecto)": dict(bosque=0.60, caida=0.25, max_tras=0.45, vecinos=3, min_obs=2),
        "sin filtros espaciales/obs.": dict(bosque=0.60, caida=0.25, max_tras=1.0, vecinos=0, min_obs=1),
        "caída ≥ 0,20": dict(bosque=0.60, caida=0.20, max_tras=0.45, vecinos=3, min_obs=2),
        "caída ≥ 0,30": dict(bosque=0.60, caida=0.30, max_tras=0.45, vecinos=3, min_obs=2),
        "caída ≥ 0,35": dict(bosque=0.60, caida=0.35, max_tras=0.45, vecinos=3, min_obs=2),
        "bosque NDVI ≥ 0,70": dict(bosque=0.70, caida=0.25, max_tras=0.45, vecinos=3, min_obs=2),
        "≥ 3 observaciones": dict(bosque=0.60, caida=0.25, max_tras=0.45, vecinos=3, min_obs=3),
        "≥ 5 vecinos": dict(bosque=0.60, caida=0.25, max_tras=0.45, vecinos=5, min_obs=2),
    }.items():
        total = sum(cc.hectareas(mascara_perdida(cc, **kw)) for cc in cambios.values())
        variantes.append({"variante": etiqueta, "perdida_total_ha": round(total)})
    sens = pd.DataFrame(variantes)
    sens.to_csv(SALIDA / "sensibilidad_umbrales.csv", index=False)
    metricas["cambio"] = {
        "antes": [str(d) for d in antes], "despues": [str(d) for d in despues],
        "perdida_total_ha": round(resumen["perdida_ha"].sum()),
        "recuperacion_total_ha": round(resumen["recuperacion_ha"].sum()),
        "cobertura_media_pct": round(resumen["cobertura_pct"].mean(), 1),
        "sensibilidad": variantes,
    }

    # ------------------------------------------------------------------ 3. Coincidencia con fuego
    print("3/5 Coincidencia pérdida–incendios (FIRMS 90 días)…", flush=True)
    fuegos = focos_periodo(*despues)
    arbol = BallTree(np.radians(fuegos[["latitud", "longitud"]].to_numpy()), metric="haversine")
    zonas = []
    for n, cc in cambios.items():
        z = cc.focos_cambio(cc.perdida, min_ha=1.0)
        if len(z):
            zonas.append(z.assign(provincia=n))
    zonas = pd.concat(zonas, ignore_index=True)
    dist, _ = arbol.query(np.radians(zonas[["latitud", "longitud"]].to_numpy()), k=1)
    zonas["dist_foco_km"] = (dist[:, 0] * 6371).round(2)
    zonas.to_csv(SALIDA / "zonas_perdida.csv", index=False)
    # Referencia: misma prueba con puntos al azar dentro de las provincias
    rng = np.random.default_rng(SEMILLA)
    x0, y0, x1, y1 = geo.region().bounds
    pts = np.column_stack([rng.uniform(y0, y1, 20000), rng.uniform(x0, x1, 20000)])
    pts = pts[geo.asignar_provincia(pts[:, 1], pts[:, 0]) != None][:3000]  # noqa: E711
    dist_azar, _ = arbol.query(np.radians(pts), k=1)
    for km in (1.0, 2.0):
        metricas.setdefault("coincidencia_fuego", {})[f"zonas_a_{km:g}km_pct"] = round(
            100 * (zonas["dist_foco_km"] <= km).mean(), 1)
        metricas["coincidencia_fuego"][f"azar_a_{km:g}km_pct"] = round(
            100 * (dist_azar[:, 0] * 6371 <= km).mean(), 1)
    metricas["coincidencia_fuego"]["focos_viirs_90d"] = len(fuegos)
    metricas["coincidencia_fuego"]["zonas_evaluadas"] = len(zonas)

    # ------------------------------------------------------------------ 4. Muestras visuales
    print("4/5 Láminas de verificación visual…", flush=True)
    muestra = zonas.sample(n=min(20, len(zonas)), random_state=SEMILLA).reset_index(drop=True)
    muestra.insert(0, "id", [f"P{i + 1:02d}" for i in range(len(muestra))])
    muestra.to_csv(SALIDA / "muestra_perdida.csv", index=False)
    filas = []
    for r in muestra.itertuples():
        a = chip(cliente, r.longitud, r.latitud, antes)
        d = chip(cliente, r.longitud, r.latitud, despues)
        dm = superponer_mascara(d, cambios[r.provincia], cambios[r.provincia].perdida, r.longitud, r.latitud,
                                (255, 0, 255))
        filas.append((f"{r.id} {r.provincia} · {r.hectareas} ha · {r.latitud:.4f},{r.longitud:.4f} · "
                      f"foco más cercano {r.dist_foco_km} km", [a, d, dm]))
    for k in range(0, len(filas), 5):
        lamina(filas[k:k + 5], "Pérdida: ANTES (2025) | DESPUÉS (2026) | DESPUÉS + detección (magenta)",
               SALIDA / f"lamina_perdida_{k // 5 + 1}.png")

    recup = []
    for n, cc in cambios.items():
        z = cc.focos_cambio(cc.recuperacion, min_ha=1.0)
        if len(z):
            recup.append(z.assign(provincia=n))
    recup = pd.concat(recup, ignore_index=True).sample(n=10, random_state=SEMILLA).reset_index(drop=True)
    recup.insert(0, "id", [f"R{i + 1:02d}" for i in range(len(recup))])
    recup.to_csv(SALIDA / "muestra_recuperacion.csv", index=False)
    filas = []
    for r in recup.itertuples():
        a = chip(cliente, r.longitud, r.latitud, antes)
        d = chip(cliente, r.longitud, r.latitud, despues)
        dm = superponer_mascara(d, cambios[r.provincia], cambios[r.provincia].recuperacion, r.longitud,
                                r.latitud, (0, 255, 255))
        filas.append((f"{r.id} {r.provincia} · {r.hectareas} ha · {r.latitud:.4f},{r.longitud:.4f}", [a, d, dm]))
    for k in range(0, len(filas), 5):
        lamina(filas[k:k + 5], "Recuperación: ANTES (2025) | DESPUÉS (2026) | DESPUÉS + detección (cian)",
               SALIDA / f"lamina_recuperacion_{k // 5 + 1}.png")

    # Eventos de incendio de mayor severidad: falso color SWIR (cicatrices de quema en rojo oscuro)
    filas = []
    for e in eventos.head(5).itertuples():  # los 5 eventos de mayor FRP (muestra dirigida, no aleatoria)
        hoy = date.today()
        tc = chip(cliente, e.longitud, e.latitud, (hoy - timedelta(days=12), hoy), semiancho=0.02)
        sw = chip(cliente, e.longitud, e.latitud, (hoy - timedelta(days=12), hoy), EVAL_SWIR, semiancho=0.02)
        pre = chip(cliente, e.longitud, e.latitud, (hoy - timedelta(days=60), hoy - timedelta(days=20)),
                   EVAL_SWIR, semiancho=0.02)
        filas.append((f"Evento {e.evento} {e.provincia} · {e.focos} focos · FRP {e.frp_total_mw:.0f} MW · "
                      f"{e.latitud:.4f},{e.longitud:.4f}", [pre, sw, tc]))
    lamina(filas, "Incendios: SWIR previo (−60 a −20 d) | SWIR reciente (12 d) | color real reciente",
           SALIDA / "lamina_incendios.png")

    # ------------------------------------------------------------------ 5. NDVI y aire
    print("5/5 Series NDVI y Sentinel-5P…", flush=True)
    ndvi = pd.concat([indicadores.serie_ndvi(cliente, p) for p in provs.values()])
    aire = pd.concat([indicadores.serie_aire(cliente, p, c) for p in provs.values()
                      for c in indicadores.CONTAMINANTES])
    metricas["ndvi"] = {
        "meses_validos_pct": round(100 * ndvi["media"].notna().mean(), 1),
        "rango": [round(ndvi["media"].min(), 3), round(ndvi["media"].max(), 3)],
        "cobertura_media_pct": round(ndvi["pct_valido"].mean(), 1),
    }
    metricas["aire"] = {
        c: {
            "semanas_validas_pct": round(100 * g["media"].notna().mean(), 1),
            "mediana": round(g["media"].median(), 2),
            "p10_p90": [round(g["media"].quantile(0.1), 2), round(g["media"].quantile(0.9), 2)],
            "valores_negativos": int((g["media"] < 0).sum()),
            "mediana_por_provincia": g.groupby("provincia")["media"].median().round(2).to_dict(),
        }
        for c, g in aire.groupby("contaminante")
    }

    (SALIDA / "metricas.json").write_text(json.dumps(metricas, ensure_ascii=False, indent=2, default=str),
                                          encoding="utf-8")
    print(json.dumps(metricas, ensure_ascii=False, indent=1, default=str))
    print(f"\nResultados en {SALIDA}")


if __name__ == "__main__":
    main()
