"""Compara la máscara de nubes anterior (v1, solo SCL) con la actual (v2, SCL + s2cloudless) sobre la
MISMA muestra ya interpretada a mano, sin volver a sortear zonas.

    .venv\\Scripts\\python scripts\\comparar_mascara.py

Requiere `salidas/validacion/` de una corrida previa de validar.py (muestras, interpretación y métricas).
Genera en `salidas/validacion/comparacion_mascara/`: tabla por zona, resumen JSON y láminas v1 | v2.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from huanuco_monitor import config, geo, indicadores  # noqa: E402
from huanuco_monitor.copernicus import ClienteCopernicus  # noqa: E402
from validar import CHIP_GRADOS, chip, lamina, superponer_mascara  # noqa: E402

VALIDACION = config.SALIDAS_DIR / "validacion"
SALIDA = VALIDACION / "comparacion_mascara"
MIN_HA = 1.0  # mismo mínimo con el que validar.py definió las zonas

# Máscara v1 (hasta el 24/10/2026): SCL en {4 vegetación, 5 suelo, 6 agua, 11 nieve}, sin s2cloudless.
_SCL_V1 = "[4, 5, 6, 11]"
EVAL_CAMBIO_V1 = f"""//VERSION=3
function setup() {{
  return {{
    input: [
      {{ datasource: "antes", bands: ["B04", "B08", "SCL", "dataMask"] }},
      {{ datasource: "despues", bands: ["B04", "B08", "SCL", "dataMask"] }}
    ],
    output: {{ bands: 3, sampleType: "UINT8" }},
    mosaicking: "ORBIT"
  }};
}}
function mediana(v) {{
  if (v.length === 0) return NaN;
  v.sort(function (a, b) {{ return a - b; }});
  var m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}}
function ndviValidos(muestras) {{
  var v = [];
  for (var i = 0; i < muestras.length; i++) {{
    var s = muestras[i];
    if (s.dataMask === 1 && {_SCL_V1}.indexOf(s.SCL) >= 0) {{
      v.push((s.B08 - s.B04) / (s.B08 + s.B04 + 1e-6));
    }}
  }}
  return v;
}}
function codificar(x) {{
  if (isNaN(x)) return 255;
  return Math.round((Math.max(-1, Math.min(1, x)) + 1) * 100) + 1;
}}
function evaluatePixel(muestras) {{
  var a = ndviValidos(muestras.antes), d = ndviValidos(muestras.despues);
  return [codificar(mediana(a)), codificar(mediana(d)), Math.min(a.length, d.length, 254) + 1];
}}
"""


def ha_en_ventana(cc: indicadores.CambioCobertura, mascara: np.ndarray, lon: float, lat: float) -> float:
    """Hectáreas marcadas dentro de la ventana de inspección de la lámina (±CHIP_GRADOS)."""
    x0, y0, x1, y1 = cc.bbox
    h, w = mascara.shape
    c0 = max(int((lon - CHIP_GRADOS - x0) / (x1 - x0) * w), 0)
    c1 = min(int(np.ceil((lon + CHIP_GRADOS - x0) / (x1 - x0) * w)), w)
    f0 = max(int((y1 - (lat + CHIP_GRADOS)) / (y1 - y0) * h), 0)
    f1 = min(int(np.ceil((y1 - (lat - CHIP_GRADOS)) / (y1 - y0) * h)), h)
    return round(cc.hectareas(mascara[f0:f1, c0:c1]), 1)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    metricas = json.loads((VALIDACION / "metricas.json").read_text(encoding="utf-8"))
    antes = tuple(date.fromisoformat(d) for d in metricas["cambio"]["antes"])
    despues = tuple(date.fromisoformat(d) for d in metricas["cambio"]["despues"])
    interp = pd.read_csv(VALIDACION / "interpretacion_visual.csv")
    muestras = pd.concat([
        pd.read_csv(VALIDACION / "muestra_perdida.csv").assign(tipo="perdida"),
        pd.read_csv(VALIDACION / "muestra_recuperacion.csv").assign(tipo="recuperacion"),
    ], ignore_index=True).merge(interp[["id", "categoria", "observacion"]], on="id", how="left")

    # La v1 se reutiliza de la caché si sigue en disco (no se vuelve a pagar en unidades de procesamiento)
    config.TTL_IMAGENES = 60 * 86400
    cliente = ClienteCopernicus()
    provs = geo.provincias()
    print(f"Periodos: antes {antes[0]}–{antes[1]} · después {despues[0]}–{despues[1]}", flush=True)

    def calcular(nombre):
        # Sin máscara de bosque: este script mide solo el efecto de la máscara de nubes
        v1 = indicadores.cambio_cobertura(cliente, provs[nombre], antes, despues, evalscript=EVAL_CAMBIO_V1,
                                          mascara_bosque=False)
        v2 = indicadores.cambio_cobertura(cliente, provs[nombre], antes, despues, mascara_bosque=False)
        print(f"  {nombre} listo", flush=True)
        return nombre, v1, v2

    with ThreadPoolExecutor(max_workers=4) as ex:
        cambios = {n: (v1, v2) for n, v1, v2 in ex.map(calcular, provs)}

    # ---------------------------------------------------------------- totales por provincia
    prov = pd.DataFrame([{
        "provincia": n,
        "perdida_ha_v1": v1.resumen()["perdida_ha"], "perdida_ha_v2": v2.resumen()["perdida_ha"],
        "recuperacion_ha_v1": v1.resumen()["recuperacion_ha"], "recuperacion_ha_v2": v2.resumen()["recuperacion_ha"],
        "cobertura_pct_v1": v1.resumen()["cobertura_pct"], "cobertura_pct_v2": v2.resumen()["cobertura_pct"],
    } for n, (v1, v2) in cambios.items()])
    prov.to_csv(SALIDA / "totales_por_provincia.csv", index=False)

    # ---------------------------------------------------------------- muestra interpretada
    filas = []
    for r in muestras.itertuples():
        v1, v2 = cambios[r.provincia]
        attr = "perdida" if r.tipo == "perdida" else "recuperacion"
        ha1 = ha_en_ventana(v1, getattr(v1, attr), r.longitud, r.latitud)
        ha2 = ha_en_ventana(v2, getattr(v2, attr), r.longitud, r.latitud)
        filas.append({"id": r.id, "tipo": r.tipo, "provincia": r.provincia, "latitud": r.latitud,
                      "longitud": r.longitud, "categoria": r.categoria, "observacion": r.observacion,
                      "ha_ventana_v1": ha1, "ha_ventana_v2": ha2, "detectada_v2": ha2 >= MIN_HA})
    tabla = pd.DataFrame(filas)
    tabla.to_csv(SALIDA / "muestra_v1_v2.csv", index=False)

    resumen = {"periodos": {"antes": [str(d) for d in antes], "despues": [str(d) for d in despues]},
               "prob_nube_max": config.PROB_NUBE_MAX}
    for tipo, g in tabla.groupby("tipo"):
        confirmada = g["categoria"] == "confirmada"
        sigue = g["detectada_v2"]
        resumen[tipo] = {
            "zonas": len(g),
            "confirmadas": int(confirmada.sum()),
            "precision_v1_pct": round(100 * confirmada.mean(), 1),
            "zonas_que_siguen_v2": int(sigue.sum()),
            "confirmadas_que_siguen_v2": int((confirmada & sigue).sum()),
            "falsas_eliminadas_v2": int((~confirmada & ~sigue).sum()),
            "falsas_que_siguen_v2": int((~confirmada & sigue).sum()),
            "precision_v2_pct": round(100 * (confirmada & sigue).sum() / max(sigue.sum(), 1), 1),
            "por_categoria": {c: {"zonas": len(x), "siguen_v2": int(x["detectada_v2"].sum())}
                              for c, x in g.groupby("categoria")},
        }
    resumen["totales_ha"] = {
        "perdida_v1": round(prov["perdida_ha_v1"].sum()), "perdida_v2": round(prov["perdida_ha_v2"].sum()),
        "recuperacion_v1": round(prov["recuperacion_ha_v1"].sum()),
        "recuperacion_v2": round(prov["recuperacion_ha_v2"].sum()),
        "cobertura_media_pct_v1": round(prov["cobertura_pct_v1"].mean(), 1),
        "cobertura_media_pct_v2": round(prov["cobertura_pct_v2"].mean(), 1),
    }
    (SALIDA / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------------------------------------------------------- láminas v1 | v2
    for tipo, color in (("perdida", (255, 0, 255)), ("recuperacion", (0, 255, 255))):
        filas_lamina = []
        for r in tabla[tabla["tipo"] == tipo].itertuples():
            v1, v2 = cambios[r.provincia]
            attr = "perdida" if tipo == "perdida" else "recuperacion"
            a = chip(cliente, r.longitud, r.latitud, antes)
            d = chip(cliente, r.longitud, r.latitud, despues)
            filas_lamina.append((
                f"{r.id} {r.categoria} · v1 {r.ha_ventana_v1} ha → v2 {r.ha_ventana_v2} ha",
                [a, superponer_mascara(d, v1, getattr(v1, attr), r.longitud, r.latitud, color),
                 superponer_mascara(d, v2, getattr(v2, attr), r.longitud, r.latitud, color)]))
        for k in range(0, len(filas_lamina), 5):
            lamina(filas_lamina[k:k + 5], f"{tipo.capitalize()}: ANTES | DESPUÉS + máscara v1 | DESPUÉS + máscara v2",
                   SALIDA / f"lamina_{tipo}_{k // 5 + 1}.png")

    print(json.dumps(resumen, ensure_ascii=False, indent=1))
    print(f"\nResultados en {SALIDA}")


if __name__ == "__main__":
    main()
