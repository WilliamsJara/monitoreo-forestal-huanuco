"""Copia de seguridad de la base de datos y de los resultados, con verificación de restauración.

    .venv\\Scripts\\python scripts\\respaldo.py                       # crea y verifica un respaldo
    .venv\\Scripts\\python scripts\\respaldo.py --destino D:\\Respaldos  # además lo copia a otra carpeta/disco
    .venv\\Scripts\\python scripts\\respaldo.py --verificar           # solo verifica el último respaldo

Genera `respaldos/respaldo_AAAAMMDD_HHMM.zip` con:
  - monitoreo.sqlite (copia consistente con la API de respaldo de SQLite, aunque el tablero esté abierto)
  - salidas/ (CSV, JSON, informes, validación e interpretaciones hechas a mano)
  - .env.example y data/ (para poder reinstalar)
Conserva los últimos `--conservar` respaldos (14 por defecto). La verificación extrae el ZIP en una carpeta
temporal, comprueba la integridad de la base (PRAGMA integrity_check), cuenta corridas y alertas, y lee
cada CSV: así se comprueba que el respaldo realmente se puede restaurar.
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from huanuco_monitor import config  # noqa: E402


def crear() -> Path:
    config.RESPALDOS_DIR.mkdir(parents=True, exist_ok=True)
    destino = config.RESPALDOS_DIR / f"respaldo_{datetime.now():%Y%m%d_%H%M}.zip"
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        if config.BASE_DATOS.exists():
            copia = Path(tmp) / "monitoreo.sqlite"
            with closing(sqlite3.connect(config.BASE_DATOS)) as origen, closing(sqlite3.connect(copia)) as dst:
                origen.backup(dst)
            z.write(copia, "salidas/monitoreo.sqlite")
        for ruta in sorted(config.SALIDAS_DIR.rglob("*")):
            if ruta.is_file() and ruta != config.BASE_DATOS and not ruta.name.endswith("-journal"):
                z.write(ruta, ruta.relative_to(config.ROOT).as_posix())
        for extra in [config.ROOT / ".env.example", *sorted(config.DATA_DIR.glob("*"))]:
            if extra.is_file():
                z.write(extra, extra.relative_to(config.ROOT).as_posix())
    return destino


def verificar(zip_path: Path) -> list[str]:
    """Restaura en una carpeta temporal y comprueba el contenido. Devuelve la lista de problemas."""
    problemas = []
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            malo = z.testzip()
            if malo:
                return [f"archivo dañado dentro del ZIP: {malo}"]
            z.extractall(tmp)
        bd = Path(tmp) / "salidas" / "monitoreo.sqlite"
        if bd.exists():
            with closing(sqlite3.connect(bd)) as con:
                estado = con.execute("PRAGMA integrity_check").fetchone()[0]
                if estado != "ok":
                    problemas.append(f"base de datos: {estado}")
                corridas = con.execute("SELECT COUNT(*) FROM corridas").fetchone()[0]
                alertas = con.execute("SELECT COUNT(*) FROM alertas").fetchone()[0]
                print(f"  base de datos íntegra: {corridas} corridas, {alertas} alertas")
        else:
            print("  (todavía no hay base de datos: se crea con la primera corrida de actualizar.py)")
        csvs = list(Path(tmp).rglob("*.csv"))
        for c in csvs:
            try:
                pd.read_csv(c)
            except Exception as e:
                problemas.append(f"{c.name}: {e}")
        print(f"  {len(csvs)} archivos CSV legibles · {sum(1 for _ in Path(tmp).rglob('*') if _.is_file())} archivos")
    return problemas


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--destino", help="carpeta adicional (otro disco, USB o carpeta sincronizada) donde copiarlo")
    ap.add_argument("--conservar", type=int, default=14, help="cuántos respaldos guardar (14 por defecto)")
    ap.add_argument("--verificar", action="store_true", help="solo verificar el último respaldo existente")
    args = ap.parse_args()

    if args.verificar:
        existentes = sorted(config.RESPALDOS_DIR.glob("respaldo_*.zip"))
        if not existentes:
            sys.exit("No hay respaldos en " + str(config.RESPALDOS_DIR))
        zip_path = existentes[-1]
    else:
        zip_path = crear()
        print(f"Respaldo creado: {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")
    print(f"Verificando restauración de {zip_path.name}…")
    problemas = verificar(zip_path)
    if problemas:
        print("RESPALDO CON PROBLEMAS:")
        for p in problemas:
            print("  -", p)
        sys.exit(1)
    print("Respaldo verificado: se puede restaurar.")
    if args.verificar:
        return
    if args.destino:
        Path(args.destino).mkdir(parents=True, exist_ok=True)
        shutil.copy2(zip_path, Path(args.destino) / zip_path.name)
        print(f"Copiado también a {args.destino}")
    for viejo in sorted(config.RESPALDOS_DIR.glob("respaldo_*.zip"))[:-args.conservar]:
        viejo.unlink()
        print(f"Eliminado respaldo antiguo: {viejo.name}")


if __name__ == "__main__":
    main()
