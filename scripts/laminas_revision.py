"""Láminas mejoradas para la revisión humana de las muestras N y M (validar_minam.py).

    .venv\\Scripts\\python scripts\\laminas_revision.py

Cada fila muestra recortes Sentinel-2 **compuestos sin nubes** (mediana de las pasadas despejadas, con la
misma máscara que usa el sistema) en lugar de una sola escena:
    ANTES color real | DESPUÉS color real | DESPUÉS falso color SWIR | DESPUÉS + detección (contorno magenta)
En falso color el bosque es verde oscuro y el suelo desnudo o quemado aparece rosado o marrón.

Primero van las zonas que la interpretación asistida por IA marcó como confirmadas (para que el equipo las
verifique) y después las indeterminadas. Genera la plantilla `revision_humana.csv` (nunca la sobrescribe).
Salida en `salidas/validacion/minam/revision/`.
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from huanuco_monitor import config, geo, indicadores  # noqa: E402
from huanuco_monitor.copernicus import ClienteCopernicus, ErrorCopernicus  # noqa: E402

MINAM = config.SALIDAS_DIR / "validacion" / "minam"
SALIDA = MINAM / "revision"
SEMIANCHO = 0.006   # ~1,3 km de lado, igual que las láminas anteriores
PX = 220
COLUMNAS = ["ANTES color real", "DESPUÉS color real", "DESPUÉS falso color", "DESPUÉS + sistema"]
POR_LAMINA = 5


def contorno(img: Image.Image, cc: indicadores.CambioCobertura, mascara: np.ndarray, lon: float, lat: float):
    """Dibuja el borde de los píxeles detectados (deja ver el terreno debajo)."""
    x0, y0, x1, y1 = cc.bbox
    h, w = mascara.shape
    c0 = int((lon - SEMIANCHO - x0) / (x1 - x0) * w)
    c1 = int(np.ceil((lon + SEMIANCHO - x0) / (x1 - x0) * w))
    f0 = int((y1 - (lat + SEMIANCHO)) / (y1 - y0) * h)
    f1 = int(np.ceil((y1 - (lat - SEMIANCHO)) / (y1 - y0) * h))
    sub = np.zeros((f1 - f0, c1 - c0), dtype=np.uint8)
    fs, cs = slice(max(f0, 0), min(f1, h)), slice(max(c0, 0), min(c1, w))
    sub[fs.start - f0:fs.stop - f0, cs.start - c0:cs.stop - c0] = mascara[fs, cs]
    capa = Image.fromarray(sub * 255).resize(img.size, Image.NEAREST)
    borde = capa.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))
    resultado = img.copy()
    resultado.paste(Image.new("RGB", img.size, (255, 0, 255)), mask=borde)
    return resultado


def lamina(filas, titulo, ruta):
    try:
        fuente = ImageFont.truetype("arial.ttf", 15)
        chica = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        fuente = chica = ImageFont.load_default()
    sep = 8
    ancho = len(COLUMNAS) * PX + (len(COLUMNAS) + 1) * sep
    alto_fila = PX + 30
    hoja = Image.new("RGB", (ancho, 62 + len(filas) * alto_fila), "white")
    d = ImageDraw.Draw(hoja)
    d.text((sep, 8), titulo, fill="black", font=fuente)
    for j, c in enumerate(COLUMNAS):
        d.text((sep + j * (PX + sep), 36), c, fill="#555555", font=chica)
    for i, (etiqueta, imgs) in enumerate(filas):
        y = 58 + i * alto_fila
        d.text((sep, y), etiqueta, fill="black", font=fuente)
        for j, im in enumerate(imgs):
            hoja.paste(im, (sep + j * (PX + sep), y + 22))
    hoja.save(ruta)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    met = json.loads((MINAM / "resumen.json").read_text(encoding="utf-8"))["periodos"]
    antes = tuple(date.fromisoformat(d) for d in met["antes"])
    despues = tuple(date.fromisoformat(d) for d in met["despues"])

    zonas = []
    for nombre, muestra, interp in (("N", "muestra_v3.csv", "interpretacion_visual_v3.csv"),
                                    ("M", "muestra_umbral_055.csv", "interpretacion_visual_umbral_055.csv")):
        z = pd.read_csv(MINAM / muestra).merge(
            pd.read_csv(MINAM / interp)[["id", "categoria"]].rename(columns={"categoria": "categoria_ia"}), on="id")
        zonas.append(z.assign(muestra=nombre))
    zonas = pd.concat(zonas, ignore_index=True)
    zonas["orden"] = (zonas["categoria_ia"] != "confirmada").astype(int)
    zonas = zonas.sort_values(["orden", "id"]).reset_index(drop=True)

    config.TTL_IMAGENES = 60 * 86400  # mismas imágenes ya procesadas por validar_minam.py
    cliente = ClienteCopernicus()
    provs = geo.provincias()
    cambios = {}
    filas = {"confirmada": [], "indeterminado": []}
    sin_imagen = []
    for r in zonas.itertuples():
        try:
            if r.provincia not in cambios:
                cambios[r.provincia] = indicadores.cambio_cobertura(cliente, provs[r.provincia], antes, despues)
            cc = cambios[r.provincia]
            a = indicadores.recorte_compuesto(cliente, r.longitud, r.latitud, antes, "color", SEMIANCHO, PX)
            d = indicadores.recorte_compuesto(cliente, r.longitud, r.latitud, despues, "color", SEMIANCHO, PX)
            f = indicadores.recorte_compuesto(cliente, r.longitud, r.latitud, despues, "falso", SEMIANCHO, PX)
        except ErrorCopernicus as e:  # p. ej. cuota mensual agotada: se arma la lámina con lo disponible
            sin_imagen.append(r.id)
            print(f"  {r.id} sin imagen: {str(e)[:90]}", flush=True)
            continue
        etiqueta = (f"{r.id} · {r.provincia} · {r.hectareas} ha · {r.latitud:.4f}, {r.longitud:.4f} · "
                    f"IA: {r.categoria_ia} · MINAM: {'sí' if r.coincide_minam else 'no'}")
        grupo = "confirmada" if r.categoria_ia == "confirmada" else "indeterminado"
        filas[grupo].append((etiqueta, [a, d, f, contorno(d, cc, cc.perdida, r.longitud, r.latitud)]))
        print(f"  {r.id} listo", flush=True)

    titulos = {"confirmada": "Zonas que la IA marcó como CONFIRMADAS — verificar acuerdo",
               "indeterminado": "Zonas que la IA dejó INDETERMINADAS — reinterpretar con imágenes sin nubes"}
    for grupo, lista in filas.items():
        for k in range(0, len(lista), POR_LAMINA):
            lamina(lista[k:k + POR_LAMINA], f"{titulos[grupo]} ({k // POR_LAMINA + 1})",
                   SALIDA / f"revision_{grupo}_{k // POR_LAMINA + 1}.png")

    plantilla = SALIDA / "revision_humana.csv"
    if not plantilla.exists():  # nunca sobrescribir la revisión hecha por el equipo
        zonas[["id", "muestra", "provincia", "categoria_ia"]].assign(
            revisor="", acuerdo_con_ia="", categoria_humana="", observacion="").to_csv(plantilla, index=False)
    print(f"\n{len(filas['confirmada'])} confirmadas y {len(filas['indeterminado'])} indeterminadas en {SALIDA}")
    if sin_imagen:
        print(f"Sin imagen ({len(sin_imagen)}), volver a ejecutar cuando haya cuota: {', '.join(sin_imagen)}")


if __name__ == "__main__":
    main()
