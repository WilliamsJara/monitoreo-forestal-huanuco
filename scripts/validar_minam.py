"""Validación independiente de la pérdida de bosque con las capas oficiales de MINAM / PNCB (Geobosques).

    .venv\\Scripts\\python scripts\\validar_minam.py

Compara tres versiones del detector sobre los mismos periodos de la validación anterior:
  v1  máscara de nubes SCL (hasta el 24/10/2026), sin máscara de bosque, umbral tras pérdida 0,45
  v2  máscara de nubes SCL + s2cloudless, sin máscara de bosque, umbral 0,45
  v3  v2 + máscara de bosque oficial MINAM, con el umbral vigente en config (sistema actual)

Referencia: alertas tempranas MINAM acumuladas 2026 y pérdida antrópica 2025 (Landsat, 30 m), un sensor y
un método distintos de los del sistema (Sentinel-2, 10-20 m). Genera además una muestra NUEVA de zonas v3
para fotointerpretación, sin tocar `interpretacion_visual.csv`.
Salida en `salidas/validacion/minam/`.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from huanuco_monitor import config, geo, indicadores, referencias  # noqa: E402
from huanuco_monitor.copernicus import ClienteCopernicus  # noqa: E402
from comparar_mascara import EVAL_CAMBIO_V1, ha_en_ventana  # noqa: E402
from validar import chip, lamina, superponer_mascara  # noqa: E402

VALIDACION = config.SALIDAS_DIR / "validacion"
SALIDA = VALIDACION / "minam"
SEMILLA = 2026
SEMILLA_UMBRAL = 2027
UMBRAL_ANTERIOR = 0.45  # NDVI_MAX_TRAS_PERDIDA hasta el 24/10/2026 (con el que se sorteó la muestra N)
N_MUESTRA = 30
BLOQUE = 16      # mismas celdas que `focos_cambio`
MIN_HA = 1.0


def dilatar(m: np.ndarray, r: int = 1) -> np.ndarray:
    """Tolerancia de ±r píxeles (diferencias de georreferenciación y de borde entre Landsat y Sentinel-2)."""
    p = np.pad(m, r)
    h, w = m.shape
    salida = np.zeros_like(m)
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            salida |= p[r + di:r + di + h, r + dj:r + dj + w]
    return salida


def zonas(mascara: np.ndarray, ha_pixel: float, ref_d: np.ndarray):
    """Celdas BLOQUE×BLOQUE con ≥ MIN_HA marcadas y si coinciden con la referencia (dilatada)."""
    h, w = mascara.shape
    filas = []
    for i in range(0, h, BLOQUE):
        for j in range(0, w, BLOQUE):
            b = mascara[i:i + BLOQUE, j:j + BLOQUE]
            ha = b.sum() * ha_pixel
            if ha >= MIN_HA:
                filas.append((i, j, ha, bool((b & ref_d[i:i + BLOQUE, j:j + BLOQUE]).any())))
    return filas


def metricas(cc, mascara, ref, frac_alertas, base_bosque):
    """Precisión por píxel y por zona frente a MINAM, sensibilidad frente a las alertas 2026 y azar.

    `frac_alertas` es la fracción de cada píxel cubierta por alertas de 30 m: la sensibilidad se pondera
    por esa fracción (un claro de 30 m dentro de un píxel de 110 m casi no cambia su NDVI) y se informa
    también solo para píxeles cubiertos al menos a la mitad.
    """
    ref_d = dilatar(ref)
    z = zonas(mascara, cc.ha_pixel, ref_d)
    obs = cc.comparable
    detectado = dilatar(mascara)
    grande = (frac_alertas >= 0.5) & obs
    return {
        "pix": int(mascara.sum()), "pix_coinciden": int((mascara & ref_d).sum()),
        "zonas": len(z), "zonas_coinciden": sum(c for *_, c in z),
        "alerta_frac": float(frac_alertas[obs].sum()),
        "alerta_frac_detectada": float(frac_alertas[obs & detectado].sum()),
        "alerta_grande_pix": int(grande.sum()), "alerta_grande_detectada": int((grande & detectado).sum()),
        "azar_pix": int(base_bosque.sum()), "azar_pix_coinciden": int((base_bosque & ref_d).sum()),
        "ha_pixel": cc.ha_pixel,
    }


class umbral:
    """Cambia temporalmente parámetros de `config` (los umbrales se leen al calcular las máscaras)."""

    def __init__(self, **valores):
        self.valores = valores

    def __enter__(self):
        self.originales = {k: getattr(config, k) for k in self.valores}
        for k, v in self.valores.items():
            setattr(config, k, v)

    def __exit__(self, *exc):
        for k, v in self.originales.items():
            setattr(config, k, v)


def porcentaje(a, b):
    return round(100 * a / b, 1) if b else None


def resumir(filas: list[dict]) -> dict:
    df = pd.DataFrame(filas)
    s = df.sum(numeric_only=True)
    return {
        "perdida_ha": round(float((df["pix"] * df["ha_pixel"]).sum())),
        "zonas": int(s["zonas"]),
        "precision_zonas_pct": porcentaje(s["zonas_coinciden"], s["zonas"]),
        "precision_pixeles_pct": porcentaje(s["pix_coinciden"], s["pix"]),
        "azar_pixeles_pct": porcentaje(s["azar_pix_coinciden"], s["azar_pix"]),
        "alertas_minam_observables_ha": round(float((df["alerta_frac"] * df["ha_pixel"]).sum())),
        "sensibilidad_ponderada_pct": porcentaje(s["alerta_frac_detectada"], s["alerta_frac"]),
        "sensibilidad_alertas_grandes_pct": porcentaje(s["alerta_grande_detectada"], s["alerta_grande_pix"]),
    }


def perdida_con(cc, tras: float) -> np.ndarray:
    with umbral(NDVI_MAX_TRAS_PERDIDA=tras):
        return cc.perdida


def muestra_fotointerpretacion(cliente, datos, antes, despues, nombre, prefijo, semilla, mascara_de, titulo,
                               umbral_muestra=None) -> dict:
    """Sortea N_MUESTRA zonas de `mascara_de(cc)` (solo la primera vez), con láminas y plantilla CSV."""
    ruta = SALIDA / f"muestra_{nombre}.csv"
    if ruta.exists():
        muestra = pd.read_csv(ruta)
        return {"zonas": len(muestra), "semilla": semilla, "coinciden_minam": int(muestra["coincide_minam"].sum()),
                "nota": "muestra existente reutilizada"}
    with umbral(**(umbral_muestra or {})):
        mascaras = {n: mascara_de(d[2]) for n, d in datos.items()}
    zonas_m = [datos[n][2].focos_cambio(m, min_ha=MIN_HA).assign(provincia=n) for n, m in mascaras.items()]
    zonas_m = pd.concat([z for z in zonas_m if len(z)], ignore_index=True)
    muestra = zonas_m.sample(n=min(N_MUESTRA, len(zonas_m)), random_state=semilla).reset_index(drop=True)
    muestra.insert(0, "id", [f"{prefijo}{i + 1:02d}" for i in range(len(muestra))])
    muestra["coincide_minam"] = [
        ha_en_ventana(datos[r.provincia][2], dilatar(datos[r.provincia][3] | datos[r.provincia][4])
                      & mascaras[r.provincia], r.longitud, r.latitud) > 0
        for r in muestra.itertuples()]
    muestra.to_csv(ruta, index=False)
    plantilla = SALIDA / f"interpretacion_visual_{nombre}.csv"
    if not plantilla.exists():  # nunca sobrescribir una interpretación ya hecha a mano
        muestra[["id"]].assign(tipo="perdida", categoria="", observacion="").to_csv(plantilla, index=False)
    filas_lamina = []
    for r in muestra.itertuples():
        _, _, cc, alertas, p25, _ = datos[r.provincia]
        a = chip(cliente, r.longitud, r.latitud, antes)
        d = chip(cliente, r.longitud, r.latitud, despues)
        filas_lamina.append((
            f"{r.id} {r.provincia} · {r.hectareas} ha · {r.latitud:.4f},{r.longitud:.4f} · "
            f"MINAM {'sí' if r.coincide_minam else 'no'}",
            [a, superponer_mascara(d, cc, mascaras[r.provincia], r.longitud, r.latitud, (255, 0, 255)),
             superponer_mascara(d, cc, alertas | p25, r.longitud, r.latitud, (255, 230, 0))]))
    for k in range(0, len(filas_lamina), 5):
        lamina(filas_lamina[k:k + 5], titulo, SALIDA / f"lamina_{nombre}_{k // 5 + 1}.png")
    return {"zonas": len(muestra), "zonas_disponibles": len(zonas_m), "semilla": semilla,
            "coinciden_minam": int(muestra["coincide_minam"].sum())}


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    met_prev = json.loads((VALIDACION / "metricas.json").read_text(encoding="utf-8"))["cambio"]
    antes = tuple(date.fromisoformat(d) for d in met_prev["antes"])
    despues = tuple(date.fromisoformat(d) for d in met_prev["despues"])
    config.TTL_IMAGENES = 60 * 86400  # reutiliza las imágenes ya procesadas (no gasta unidades de Copernicus)
    cliente = ClienteCopernicus()
    provs = geo.provincias()
    print(f"Periodos: antes {antes[0]}–{antes[1]} · después {despues[0]}–{despues[1]}", flush=True)

    def calcular(nombre):
        v1 = indicadores.cambio_cobertura(cliente, provs[nombre], antes, despues, evalscript=EVAL_CAMBIO_V1,
                                          mascara_bosque=False)
        v3 = indicadores.cambio_cobertura(cliente, provs[nombre], antes, despues)
        if v3.bosque_ref is None:
            raise RuntimeError(f"{nombre}: {v3.referencia}")
        v2 = replace(v3, bosque_ref=None, alguna_vez_bosque=None, referencia="sin máscara de bosque")
        args = (v3.bbox, *v3.dentro.shape[::-1])
        frac_alertas = np.where(v3.dentro, referencias.fraccion("alertas_2026", *args), 0.0)
        alertas = frac_alertas > 0
        perdida_2025 = (referencias.fraccion("perdida_2025", *args) > 0) & v3.dentro
        print(f"  {nombre} listo", flush=True)
        return nombre, v1, v2, v3, alertas, perdida_2025, frac_alertas

    with ThreadPoolExecutor(max_workers=4) as ex:
        datos = {r[0]: r[1:] for r in ex.map(calcular, provs)}

    # ---------------------------------------------------------------- métricas por versión y provincia
    por_version = {"v1": [], "v2": [], "v3": []}
    por_provincia = []
    for nombre, (v1, v2, v3, alertas, p25, frac) in datos.items():
        ref = alertas | p25
        base = v3.comparable & v3.bosque_ref  # bosque observable: probabilidad de coincidir por azar
        for etiqueta, cc in (("v1", v1), ("v2", v2), ("v3", v3)):
            # v1 y v2 son versiones históricas: se evalúan con el umbral que tenían (0,45)
            with umbral(**({} if etiqueta == "v3" else {"NDVI_MAX_TRAS_PERDIDA": UMBRAL_ANTERIOR})):
                m = metricas(cc, cc.perdida, ref, frac, base)
            por_version[etiqueta].append(m)
            if etiqueta == "v3":
                por_provincia.append({
                    "provincia": nombre, "perdida_ha_v3": round(m["pix"] * m["ha_pixel"], 1),
                    "zonas": m["zonas"], "zonas_coinciden_minam": m["zonas_coinciden"],
                    "precision_zonas_pct": porcentaje(m["zonas_coinciden"], m["zonas"]),
                    "alertas_minam_observables_ha": round(m["alerta_frac"] * m["ha_pixel"], 1),
                    "sensibilidad_ponderada_pct": porcentaje(m["alerta_frac_detectada"], m["alerta_frac"]),
                    "bosque_minam_pct": round(100 * v3.bosque_ref[v3.dentro].mean(), 1),
                    "cobertura_pct": round(v3.cobertura_pct, 1),
                })
    pd.DataFrame(por_provincia).to_csv(SALIDA / "minam_por_provincia.csv", index=False)
    resumen = {
        "periodos": {"antes": [str(d) for d in antes], "despues": [str(d) for d in despues]},
        "referencia": "MINAM/PNCB: alertas tempranas acumuladas 2026 + pérdida antrópica 2025 (Geobosques)",
        "tolerancia": "±1 píxel del sistema",
        "versiones": {k: resumir(v) for k, v in por_version.items()},
        "recuperacion_ha": {"v2": round(sum(d[1].hectareas(d[1].recuperacion) for d in datos.values())),
                            "v3": round(sum(d[2].hectareas(d[2].recuperacion) for d in datos.values()))},
    }

    # ---------------------------------------------------------------- umbrales: precisión vs. sensibilidad
    variantes = {
        f"sistema actual (tras ≤ {config.NDVI_MAX_TRAS_PERDIDA})": {},
        f"tras pérdida ≤ {UMBRAL_ANTERIOR} (umbral anterior)": {"NDVI_MAX_TRAS_PERDIDA": UMBRAL_ANTERIOR},
        "tras pérdida ≤ 0,65": {"NDVI_MAX_TRAS_PERDIDA": 0.65},
        "caída ≥ 0,20": {"CAIDA_NDVI_DEFORESTACION": 0.20},
        "caída ≥ 0,15": {"CAIDA_NDVI_DEFORESTACION": 0.15},
        "2 vecinos": {"MIN_VECINOS": 2},
        "1 observación": {"MIN_OBSERVACIONES": 1},
        "caída 0,20 · tras ≤ 0,55 · 2 vecinos": {"CAIDA_NDVI_DEFORESTACION": 0.20, "NDVI_MAX_TRAS_PERDIDA": 0.55,
                                                "MIN_VECINOS": 2},
    }
    tabla_var = []
    for etiqueta, cambios_cfg in variantes.items():
        with umbral(**cambios_cfg):
            filas_v = [metricas(v3, v3.perdida, alertas | p25, frac, v3.comparable & v3.bosque_ref)
                       for _, _, v3, alertas, p25, frac in datos.values()]
        tabla_var.append({"variante": etiqueta, **resumir(filas_v)})
    pd.DataFrame(tabla_var).to_csv(SALIDA / "umbrales_precision_sensibilidad.csv", index=False)
    resumen["umbrales"] = tabla_var

    # ---------------------------------------------------------------- muestra anterior (interpretada) con v3
    interp = pd.read_csv(VALIDACION / "interpretacion_visual.csv")
    previa = pd.concat([
        pd.read_csv(VALIDACION / "muestra_perdida.csv").assign(tipo="perdida"),
        pd.read_csv(VALIDACION / "muestra_recuperacion.csv").assign(tipo="recuperacion"),
    ]).merge(interp[["id", "categoria"]], on="id")
    filas = []
    for r in previa.itertuples():
        v3 = datos[r.provincia][2]
        m = v3.perdida if r.tipo == "perdida" else v3.recuperacion
        filas.append({"id": r.id, "tipo": r.tipo, "categoria": r.categoria,
                      "ha_ventana_v3": ha_en_ventana(v3, m, r.longitud, r.latitud)})
    previa = pd.DataFrame(filas).assign(detectada_v3=lambda d: d["ha_ventana_v3"] >= MIN_HA)
    previa.to_csv(SALIDA / "muestra_anterior_v3.csv", index=False)
    resumen["muestra_anterior_v3"] = {
        tipo: {c: f"{int(x['detectada_v3'].sum())} de {len(x)} siguen" for c, x in g.groupby("categoria")}
        | {"precision_pct": porcentaje(((g["categoria"] == "confirmada") & g["detectada_v3"]).sum(),
                                       g["detectada_v3"].sum())}
        for tipo, g in previa.groupby("tipo")
    }

    # ---------------------------------------------------------------- muestras para fotointerpretación
    # N: 30 zonas del sistema con el umbral anterior (0,45). M: 30 zonas que solo aparecen al subirlo.
    # Cada muestra se sortea una sola vez: si su CSV ya existe se reutiliza, para no desalinear la
    # interpretación hecha a mano.
    resumen["muestra_nueva"] = muestra_fotointerpretacion(
        cliente, datos, antes, despues, "v3", "N", SEMILLA,
        lambda cc: cc.perdida, "ANTES (2025) | DESPUÉS + sistema (magenta) | DESPUÉS + MINAM (amarillo)",
        umbral_muestra={"NDVI_MAX_TRAS_PERDIDA": UMBRAL_ANTERIOR})
    resumen["muestra_umbral"] = muestra_fotointerpretacion(
        cliente, datos, antes, despues, f"umbral_{round(config.NDVI_MAX_TRAS_PERDIDA * 100):03d}", "M",
        SEMILLA_UMBRAL, lambda cc: cc.perdida & ~perdida_con(cc, UMBRAL_ANTERIOR),
        f"ANTES (2025) | DESPUÉS + agregado por el umbral {config.NDVI_MAX_TRAS_PERDIDA} (magenta) | "
        "DESPUÉS + MINAM (amarillo)")

    (SALIDA / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2, default=str),
                                         encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=1, default=str))
    print(f"\nResultados en {SALIDA}")


if __name__ == "__main__":
    main()
