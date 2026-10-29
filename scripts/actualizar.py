"""Actualiza los datos satelitales, genera las alertas y exporta los resultados a `salidas/`.

Pensado para ejecutarse de forma programada (Programador de tareas de Windows o cron):

    .venv\\Scripts\\python scripts\\actualizar.py --dias 7 --cobertura
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from huanuco_monitor import almacen, config, monitor  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dias", type=int, default=7, help="días de focos de calor (1-30)")
    ap.add_argument("--cobertura", action="store_true",
                    help="incluye el análisis de pérdida/recuperación de cobertura (más lento)")
    ap.add_argument("--forzar", action="store_true", help="ignora la caché y vuelve a consultar")
    args = ap.parse_args()

    faltan = config.credenciales_faltantes()
    if faltan:
        sys.exit(f"Faltan credenciales en .env: {', '.join(faltan)}")

    print("Consultando NASA FIRMS, Sentinel-2 y Sentinel-5P…", flush=True)
    rep = monitor.generar_reporte(args.dias, con_cambio_cobertura=args.cobertura, forzar=args.forzar)

    if rep.cambios:
        print("Preparando imágenes del tablero (fondo, alertas MINAM y evidencia)…", flush=True)
        rep.errores += monitor.precalentar_tablero(rep.cambios)

    carpeta = config.SALIDAS_DIR / f"{rep.generado:%Y%m%d_%H%M}"
    carpeta.mkdir(parents=True, exist_ok=True)
    rep.focos.to_csv(carpeta / "focos_calor.csv", index=False)
    rep.eventos.to_csv(carpeta / "eventos_incendio.csv", index=False)
    rep.ndvi.to_csv(carpeta / "ndvi_mensual.csv", index=False)
    rep.aire.to_csv(carpeta / "aire_semanal.csv", index=False)
    tabla = rep.tabla_alertas
    tabla.to_csv(carpeta / "alertas.csv", index=False)
    if rep.cambios:
        import pandas as pd
        pd.DataFrame([c.resumen() for c in rep.cambios.values()]).to_csv(
            carpeta / "cambio_cobertura.csv", index=False)
    corrida = almacen.guardar(rep, "actualizar.py", args.dias, str(carpeta))
    (carpeta / "resumen.json").write_text(json.dumps({
        "corrida_bd": corrida,
        "fuentes": {n: e.descripcion for n, e in rep.fuentes.items()},
        "generado": rep.generado.isoformat(),
        "focos": len(rep.focos),
        "eventos": len(rep.eventos),
        "niveles": rep.niveles,
        "alertas": tabla.to_dict("records"),
        "errores": rep.errores,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nFocos de calor: {len(rep.focos)} · eventos: {len(rep.eventos)}")
    print("\nNivel de alerta por provincia:")
    for p, n in sorted(rep.niveles.items(), key=lambda kv: -["sin alerta", "baja", "media", "alta"].index(kv[1])):
        print(f"  {p:<15} {n}")
    if not tabla.empty:
        print("\nAlertas:")
        for r in tabla.itertuples():
            print(f"  [{r.nivel.upper():5}] {r.provincia:<15} {r.tipo:<14} {r.mensaje}")
    for e in rep.errores:
        print(f"  ⚠ {e}")
    print("\nEstado de las fuentes:")
    for n, e in rep.fuentes.items():
        print(f"  {monitor.FUENTES[n]:<26} {e.descripcion}")
    print(f"\nResultados guardados en {carpeta} y en la base de datos (corrida {corrida})")


if __name__ == "__main__":
    main()
