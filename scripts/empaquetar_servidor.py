"""Empaqueta el sistema completo para instalarlo en otro servidor (código, datos, resultados y caché).

    .venv\\Scripts\\python scripts\\empaquetar_servidor.py

Genera `Descargas\\monitoreo-huanuco-servidor_AAAAMMDD_HHMM.zip` con todo lo necesario:
  - código (app.py, src/, scripts/, docs/, deploy/, requirements*.txt)
  - datos (data/), resultados e historial (salidas/, incluida la base SQLite y las revisiones a mano)
  - caché (.cache/): evita repetir consultas a Copernicus y ahorra cuota
  - credenciales (.env): el ZIP contiene claves, no compartirlo
No incluye el entorno de Python (.venv: se crea en el servidor) ni los respaldos locales.
Los archivos de despliegue se guardan con saltos de línea de Linux.
"""
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from huanuco_monitor import config  # noqa: E402

EXCLUIR = {".venv", "respaldos", "__pycache__", ".idea", "logs", ".git"}
TEXTO_LINUX = {".sh", ".service", ".conf", ".txt"}


def main():
    destino = Path.home() / "Downloads" / f"monitoreo-huanuco-servidor_{datetime.now():%Y%m%d_%H%M}.zip"
    raiz = config.ROOT
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for ruta in sorted(raiz.rglob("*")):
            relativa = ruta.relative_to(raiz)
            if not ruta.is_file() or EXCLUIR & set(relativa.parts) or ruta.suffix == ".pyc":
                continue
            if ruta == config.BASE_DATOS:  # copia consistente aunque el tablero esté abierto
                copia = Path(tmp) / "monitoreo.sqlite"
                with closing(sqlite3.connect(ruta)) as o, closing(sqlite3.connect(copia)) as d:
                    o.backup(d)
                z.write(copia, relativa.as_posix())
            elif relativa.parts[0] == "deploy" and ruta.suffix in TEXTO_LINUX:
                z.writestr(relativa.as_posix(), ruta.read_bytes().replace(b"\r\n", b"\n"))
            else:
                z.write(ruta, relativa.as_posix())
    print(f"Paquete: {destino} ({destino.stat().st_size / 1e6:.0f} MB)")
    print("Contiene .env con credenciales: no compartirlo ni subirlo a internet.")


if __name__ == "__main__":
    main()
