#!/usr/bin/env bash
# ライフメイクセールス セットアップ＆起動（Mac / Linux 用）
# 使い方: bash setup.sh
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  ライフメイクセールス (Life Make Sales)"
echo "============================================"

# .env が無ければテンプレートから作成
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "[初回] .env を作成しました。必要に応じて APIキー等を編集してください。"
fi

# Python 仮想環境
PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "[初回] Python仮想環境を作成中..."
  "$PY" -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

echo
echo "起動します → http://127.0.0.1:8123  (停止: Ctrl+C)"
echo
# 既定ブラウザを開く（環境により無効でも問題なし）
( command -v open >/dev/null && open http://127.0.0.1:8123 ) 2>/dev/null || \
( command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:8123 ) 2>/dev/null || true

exec ./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8123
