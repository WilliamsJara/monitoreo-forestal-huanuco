#!/usr/bin/env bash
# Instala o actualiza el sistema en un servidor Linux (Ubuntu/Debian) sin Docker.
#
#   sudo bash deploy/instalar.sh            (ejecutar dentro de la carpeta descomprimida del paquete)
#
# Qué hace:
#   1. Copia el proyecto a /opt/monitoreo-huanuco (conserva .env, salidas/ y .cache/ si ya existen).
#   2. Crea el entorno de Python con las versiones exactas de requirements-lock.txt.
#   3. Registra el servicio systemd "monitoreo-huanuco" (Streamlit en 127.0.0.1:8501, ruta /carpeta).
#   4. Programa en cron la actualización diaria (06:00) y el respaldo (06:30).
#   5. Si hay nginx, instala el bloque de proxy para http://<servidor>/carpeta/.
set -euo pipefail

DESTINO=/opt/monitoreo-huanuco
USUARIO=${SUDO_USER:-$(whoami)}
ORIGEN="$(cd "$(dirname "$0")/.." && pwd)"

echo "== 1. Paquetes del sistema"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip rsync >/dev/null
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Se necesita Python 3.10 o superior"'

echo "== 2. Copia del proyecto a $DESTINO"
mkdir -p "$DESTINO"
rsync -a --exclude '.venv' --exclude '__pycache__' "$ORIGEN/" "$DESTINO/"
mkdir -p "$DESTINO/logs"
chown -R "$USUARIO":"$USUARIO" "$DESTINO"
chmod 600 "$DESTINO/.env" 2>/dev/null || echo "   AVISO: falta $DESTINO/.env (credenciales). Copiarlo antes de usar el sistema."

echo "== 3. Entorno de Python"
sudo -u "$USUARIO" python3 -m venv "$DESTINO/.venv"
sudo -u "$USUARIO" "$DESTINO/.venv/bin/pip" install -q --upgrade pip
if ! sudo -u "$USUARIO" "$DESTINO/.venv/bin/pip" install -q -r "$DESTINO/requirements-lock.txt"; then
    echo "   Versiones exactas no disponibles para este Python: se instalan las compatibles"
    sudo -u "$USUARIO" "$DESTINO/.venv/bin/pip" install -q -r "$DESTINO/requirements.txt"
fi

echo "== 4. Servicio del tablero"
sed "s/__USUARIO__/$USUARIO/" "$DESTINO/deploy/monitoreo-huanuco.service" > /etc/systemd/system/monitoreo-huanuco.service
systemctl daemon-reload
systemctl enable --now monitoreo-huanuco
systemctl restart monitoreo-huanuco

echo "== 5. Tareas diarias (cron del usuario $USUARIO)"
( crontab -u "$USUARIO" -l 2>/dev/null | grep -v 'monitoreo-huanuco' ; cat "$DESTINO/deploy/cron.txt" ) | crontab -u "$USUARIO" -

echo "== 6. Proxy web"
if command -v nginx >/dev/null 2>&1; then
    cp "$DESTINO/deploy/nginx-carpeta.conf" /etc/nginx/snippets/monitoreo-huanuco.conf
    echo "   Agregar esta línea dentro del bloque 'server { ... }' del sitio (p. ej. /etc/nginx/sites-enabled/default):"
    echo "       include snippets/monitoreo-huanuco.conf;"
    echo "   y luego:  sudo nginx -t && sudo systemctl reload nginx"
else
    echo "   nginx no está instalado: ver deploy/nginx-carpeta.conf (o usar el bloque de Apache del manual)"
fi

echo
echo "Listo. Estado del servicio:"
systemctl --no-pager --lines=3 status monitoreo-huanuco || true
echo "Prueba local:  curl -s http://127.0.0.1:8501/carpeta/_stcore/health   (debe responder ok)"
