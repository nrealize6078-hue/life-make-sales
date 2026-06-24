#!/usr/bin/env bash
# ライフメイクセールス VPS設置（nginx共存版・既存サイトに触れない）
# 使い方: root で  bash <(curl -fsSL <URL>)  または  curl ...| bash
set -e
APPDIR=/opt/life-make-sales
PORT=8123
REPO=https://github.com/nrealize6078-hue/life-make-sales.git

[ "$(id -u)" = 0 ] || { echo "rootで実行してください"; exit 1; }

echo "==== 依存をインストール ===="
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y python3 python3-venv python3-pip git >/dev/null

echo "==== アプリを取得 ===="
if [ -d "$APPDIR/.git" ]; then
  cd "$APPDIR"; git pull --ff-only || { git fetch; git reset --hard origin/master; }
else
  git clone "$REPO" "$APPDIR"; cd "$APPDIR"
fi

echo "==== ライブラリ導入 ===="
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip -q
./.venv/bin/pip install -r requirements.txt -q

# .env（ログインパスワードを設定）
if [ ! -f .env ]; then
  cp .env.example .env
  read -r -p "▶ アプリのログインパスワードを決めて入力: " PW < /dev/tty
  ./.venv/bin/python - "$PW" <<'PY'
import re,sys
s=open('.env',encoding='utf-8').read()
s=re.sub(r'^APP_PASSWORD=.*$','APP_PASSWORD='+sys.argv[1],s,count=1,flags=re.M)
open('.env','w',encoding='utf-8').write(s)
PY
fi

read -r -p "▶ 公開するサブドメイン (例 sales.lifemakepartners.net): " DOMAIN < /dev/tty

echo "==== 常駐サービス化(24時間) ===="
cat >/etc/systemd/system/lms.service <<EOF
[Unit]
Description=Life Make Sales
After=network.target
[Service]
WorkingDirectory=$APPDIR
ExecStart=$APPDIR/.venv/bin/uvicorn main:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable lms >/dev/null 2>&1
systemctl restart lms

echo "==== nginx に追加(既存サイトはそのまま) ===="
# server_name を指定したブロックを足すだけ。default も既存設定も削除しない＝共存。
cat >/etc/nginx/conf.d/lms.conf <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 600M;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 1800s;
    }
}
EOF
nginx -t && systemctl reload nginx

echo
echo "================================================="
echo " ✅ アプリ設置完了！（既存サイトはそのまま動いています）"
echo "-------------------------------------------------"
echo " 次の2つで公開URLが完成します:"
echo " 1) DNSで  $DOMAIN  を  162.43.38.50  に向ける(Aレコード)"
echo " 2) 反映後、HTTPS化:"
echo "      apt-get install -y certbot python3-certbot-nginx"
echo "      certbot --nginx -d $DOMAIN"
echo " 動作確認(DNS反映後): http://$DOMAIN/"
echo "================================================="
