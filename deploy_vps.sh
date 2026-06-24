#!/usr/bin/env bash
# ============================================================
#  ライフメイクセールス  Xserver VPS 自動デプロイ
#  使い方（VPSにSSHログイン後）:
#     sudo bash deploy_vps.sh
#  これ1つで: 依存導入→クローン→常駐サービス化(24時間)→nginx公開 まで行う。
#  再実行すると最新コードに更新して再起動する（git pull）。
# ============================================================
set -e

APPDIR="/opt/life-make-sales"
PORT=8123

# リポジトリURL。private の場合は GH_TOKEN を渡すと認証付きで取得する:
#   GH_TOKEN=ghp_xxx sudo -E bash deploy_vps.sh
if [ -n "$GH_TOKEN" ]; then
  REPO="https://${GH_TOKEN}@github.com/nrealize6078-hue/life-make-sales.git"
else
  REPO="https://github.com/nrealize6078-hue/life-make-sales.git"
fi

echo "============================================"
echo "  ライフメイクセールス VPSセットアップ"
echo "============================================"

# root 確認
if [ "$(id -u)" != "0" ]; then
  echo "▲ sudo で実行してください:  sudo bash deploy_vps.sh"
  exit 1
fi

# パッケージマネージャ自動判定（Ubuntu=apt / AlmaLinux等=dnf）
if command -v apt-get >/dev/null 2>&1; then
  PM=apt; export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y python3 python3-venv python3-pip git nginx curl
elif command -v dnf >/dev/null 2>&1; then
  PM=dnf
  dnf install -y python3 python3-pip git nginx curl
else
  echo "▲ 対応していないOSです（apt も dnf も見つかりません）"
  exit 1
fi

# 取得 or 更新
if [ -d "$APPDIR/.git" ]; then
  echo "[更新] 既存のアプリを最新に更新します..."
  cd "$APPDIR" && git pull --ff-only || (git fetch && git reset --hard origin/master)
else
  echo "[取得] GitHubからアプリを取得します..."
  git clone "$REPO" "$APPDIR"
  cd "$APPDIR"
fi

# Python仮想環境＋依存
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

# .env（無ければテンプレートから作成し、パスワードを設定）
if [ ! -f .env ]; then
  cp .env.example .env
  if [ -z "$APP_PASSWORD" ]; then
    echo
    read -r -p "ログインパスワードを決めて入力してください（後で変更可）: " APP_PASSWORD
  fi
  # APP_PASSWORD を反映（/ などの記号に強い置換）
  python3 - "$APP_PASSWORD" <<'PYEOF'
import re, sys
pw = sys.argv[1]
s = open('.env', encoding='utf-8').read()
s = re.sub(r'^APP_PASSWORD=.*$', 'APP_PASSWORD=' + pw, s, count=1, flags=re.M)
open('.env','w',encoding='utf-8').write(s)
PYEOF
  echo "[.env] 作成しました（APIキー等は後で .env を編集）"
fi

# 24時間常駐サービス（systemd・自動再起動・起動時に自動開始）
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
systemctl enable lms
systemctl restart lms

# nginx リバースプロキシ（80番ポート → アプリ）。音声アップロードのため上限を拡大。
DOMAIN="${DOMAIN:-_}"
cat >/etc/nginx/conf.d/lms.conf <<EOF
server {
    listen 80;
    server_name ${DOMAIN};
    client_max_body_size 600M;
    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 1800s;
    }
}
EOF
# Ubuntu の既定サイトが competing しないよう無効化
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
nginx -t && systemctl enable nginx && systemctl restart nginx

# OS内ファイアウォール（あれば）でHTTP/HTTPSを許可
if command -v ufw >/dev/null 2>&1; then ufw allow 80/tcp >/dev/null 2>&1 || true; ufw allow 443/tcp >/dev/null 2>&1 || true; fi
if command -v firewall-cmd >/dev/null 2>&1; then firewall-cmd --permanent --add-service=http >/dev/null 2>&1 || true; firewall-cmd --permanent --add-service=https >/dev/null 2>&1 || true; firewall-cmd --reload >/dev/null 2>&1 || true; fi

IP=$(curl -s --max-time 5 https://api.ipify.org || echo "<VPSのIPアドレス>")
echo
echo "============================================"
echo "  ✅ セットアップ完了！"
echo "  ブラウザで  http://${IP}/  を開いてください"
echo "  ログイン: admin / 設定したパスワード"
echo "============================================"
echo "  状態確認:  systemctl status lms"
echo "  ログ:      journalctl -u lms -f"
echo "  ※Xserver VPS の管理画面『パケットフィルター』で 80番(と443番)を許可してください"
echo "  ※独自ドメインでHTTPS化する場合は: DEPLOY_VPS.md の手順を参照"
