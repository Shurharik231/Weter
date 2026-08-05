#!/usr/bin/env bash
set -euo pipefail

DOMAIN="drinandbloom.ru"
WWW_DOMAIN="www.drinandbloom.ru"
APP_NAME="weter"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
NGINX_FILE="/etc/nginx/sites-available/${DOMAIN}.conf"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запусти скрипт от root: sudo bash deploy_timeweb.sh"
  exit 1
fi

if [[ ! -f "$APP_DIR/app.py" || ! -f "$APP_DIR/requirements.txt" ]]; then
  echo "Ошибка: скрипт должен находиться в корне проекта рядом с app.py и requirements.txt."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Weter Wind Trajectory FastAPI application
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
cat > "$NGINX_FILE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN $WWW_DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
EOF

ln -sf "$NGINX_FILE" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now "$APP_NAME"
systemctl restart nginx

if ! curl -fsS http://127.0.0.1:8000/ >/dev/null; then
  echo "Приложение не ответило на http://127.0.0.1:8000/"
  systemctl --no-pager --full status "$APP_NAME" || true
  exit 1
fi

echo "Приложение запущено."
echo "Перед выпуском SSL убедись, что A-записи $DOMAIN и $WWW_DOMAIN указывают на IP этого сервера."
read -r -p "DNS уже настроен и домен доступен с этого сервера? [y/N] " DNS_OK
if [[ "$DNS_OK" =~ ^[Yy]$ ]]; then
  certbot --nginx --non-interactive --agree-tos --redirect -m "admin@$DOMAIN" -d "$DOMAIN" -d "$WWW_DOMAIN"
  systemctl reload nginx
  echo "Готово: https://$DOMAIN"
else
  echo "SSL пока не выпускался. После настройки DNS выполни:"
  echo "sudo certbot --nginx --redirect -d $DOMAIN -d $WWW_DOMAIN"
fi

echo
echo "Статус: systemctl status $APP_NAME"
echo "Логи:   journalctl -u $APP_NAME -f"
