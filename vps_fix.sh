#!/usr/bin/env bash
# VPSのアプリを最新版に更新し、管理者(admin)パスワードを再設定する。
# データは消えません（DBはそのまま、adminのパスワードだけ作り直し）。
set -e
cd /opt/life-make-sales

echo "==== 最新版に更新 ===="
git pull --ff-only || { git fetch; git reset --hard origin/master; }
./.venv/bin/pip install -r requirements.txt -q

echo
read -r -p "▶ 新しい管理者(admin)パスワードを入力してEnter: " NEWPW < /dev/tty

./.venv/bin/python - "$NEWPW" <<'PY'
import sys
from datetime import datetime
sys.path.insert(0, '.')
import auth, database as db
db.init_db()
pw = sys.argv[1].strip()
conn = db.get_conn()
row = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
h = auth.hash_password(pw)
if row:
    conn.execute("UPDATE users SET password_hash=?, active=1, role='admin' WHERE username='admin'", (h,))
else:
    conn.execute(
        "INSERT INTO users (username, display_name, password_hash, role, active, created_at) "
        "VALUES ('admin','管理者',?, 'admin', 1, ?)",
        (h, datetime.now().isoformat(timespec='seconds')))
conn.commit()
conn.execute("DELETE FROM sessions")  # 古いログインを失効
conn.commit()
conn.close()
print("RESET-OK")
PY

systemctl restart lms
echo
echo "==== OK-FIXED ===="
echo " 更新＋パスワード再設定 完了！"
echo " ログイン: ID = admin / 今入力したパスワード"
