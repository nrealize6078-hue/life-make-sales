#!/usr/bin/env bash
# VPS上のアプリを最新版に更新する（git pull → 依存更新 → 再起動）。
# DBは自動マイグレーションされ、データは消えません。
set -e
cd /opt/life-make-sales
git pull --ff-only || { git fetch; git reset --hard origin/master; }
./.venv/bin/pip install -r requirements.txt -q
systemctl restart lms
echo "==== OK-UPDATED ===="
echo " 最新版に更新しました（データはそのまま）"
