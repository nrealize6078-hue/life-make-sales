"""
認証・ユーザー管理（ユーザー別アカウント／ロール／セッション失効）。
- パスワードは pbkdf2-sha256 で salt 付きハッシュ化（標準ライブラリのみ）。
- セッションは sessions テーブルで管理し、ログアウト/削除で即時失効できる。
- 後方互換: ユーザーが1人もおらず APP_PASSWORD が設定済みなら admin を自動作成。
"""
import os
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta

import database as db

_ITER = 200_000
SESSION_DAYS = 7


# ---------- パスワード ----------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER)
        return hmac.compare_digest(dk.hex(), h)
    except Exception:
        return False


# ---------- ユーザー ----------
def _now():
    return datetime.now().isoformat(timespec="seconds")


def create_user(username: str, password: str, role: str = "member", display_name: str = "") -> int:
    username = (username or "").strip()
    if not username:
        raise ValueError("ユーザー名を入力してください")
    if not password or len(password) < 4:
        raise ValueError("パスワードは4文字以上にしてください")
    if role not in ("admin", "member"):
        role = "member"
    conn = db.get_conn()
    try:
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise ValueError("そのユーザー名は既に使われています")
        cur = conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role, active, created_at) VALUES (?,?,?,?,1,?)",
            (username, display_name or username, hash_password(password), role, _now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_users():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, username, display_name, role, active, created_at FROM users ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_users() -> int:
    conn = db.get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
    finally:
        conn.close()


def get_user_by_name(username: str):
    conn = db.get_conn()
    try:
        r = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def set_password(user_id: int, password: str):
    if not password or len(password) < 4:
        raise ValueError("パスワードは4文字以上にしてください")
    conn = db.get_conn()
    try:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user_id))
        conn.commit()
        # パスワード変更時は本人の全セッションを失効
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def update_user(user_id: int, role: str = None, active: int = None, display_name: str = None):
    conn = db.get_conn()
    try:
        cur = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not cur:
            raise ValueError("ユーザーが見つかりません")
        old = dict(cur)
        new_role = role if role in ("admin", "member") else old["role"]
        new_active = old["active"] if active is None else (1 if active else 0)
        new_name = old["display_name"] if display_name is None else display_name
        conn.execute("UPDATE users SET role=?, active=?, display_name=? WHERE id=?",
                     (new_role, new_active, new_name, user_id))
        conn.commit()
        if not new_active:  # 無効化したら全セッション失効
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.commit()
    finally:
        conn.close()


def delete_user(user_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()


# ---------- セッション ----------
def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, user_id, now.isoformat(timespec="seconds"),
             (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def get_session_user(token: str):
    """有効なセッションのトークンからユーザーを返す。無効/期限切れは None。"""
    if not token:
        return None
    conn = db.get_conn()
    try:
        r = conn.execute(
            "SELECT u.id, u.username, u.display_name, u.role, u.active, s.expires_at "
            "FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token=?", (token,)
        ).fetchone()
        if not r:
            return None
        d = dict(r)
        if not d["active"] or d["expires_at"] < datetime.now().isoformat(timespec="seconds"):
            return None
        return {"id": d["id"], "username": d["username"], "display_name": d["display_name"], "role": d["role"]}
    finally:
        conn.close()


def revoke_session(token: str):
    if not token:
        return
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
    finally:
        conn.close()


def revoke_all_for_user(user_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def purge_expired():
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now().isoformat(timespec="seconds"),))
        conn.commit()
    finally:
        conn.close()


def bootstrap(app_password: str):
    """初回起動時のみ: ユーザーが居らず APP_PASSWORD があれば admin を自動作成。"""
    try:
        if count_users() == 0 and app_password:
            create_user("admin", app_password, role="admin", display_name="管理者")
    except Exception:
        pass


def auth_enabled() -> bool:
    """有効ユーザーが1人でも居れば認証ON。"""
    return count_users() > 0
