# -*- coding: utf-8 -*-
"""LMP本部コンソール用の Supabase 管理クライアント（標準ライブラリのみ）。

- service_role キーで Supabase REST / Auth Admin API を叩く（RLSをbypass）。
- キーは環境変数から読む。未設定ならこの機能だけ無効化し、SALES本体には影響しない。
- ここでは全加盟店(tenant)を横断して扱うため、取り扱いは本部(hq)に限定すること。
"""
import os
import json
import urllib.request
import urllib.error
import urllib.parse

SUPABASE_URL = (os.getenv("SUPABASE_URL", "") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")).rstrip("/")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

_TIMEOUT = 20


def _looks_like_key(k: str) -> bool:
    """キーが本物っぽいか。テンプレのプレースホルダ(＜貼り付け＞ 等)や
    非ASCII混入を弾く。HTTPヘッダは latin-1 のため全角が混ざると送信時に落ちる。"""
    if not k or len(k) < 20:
        return False
    try:
        k.encode("latin-1")   # 全角・全角記号が混じっていれば False
    except UnicodeEncodeError:
        return False
    return True


def enabled() -> bool:
    """本部コンソールが使えるか（URLとキーが妥当に設定済みか）。"""
    return bool(SUPABASE_URL) and _looks_like_key(SERVICE_KEY)


# ---------- 横断ログイン: Supabaseの共有Cookieを検証する ----------
# ポータル/会計6アプリと同じ Cookie（sb-<ref>-auth-token）を読み、
# Supabase Auth で access_token の有効性を確認して、ログインユーザーを返す。
# anon キーで /auth/v1/user を叩くだけ（JWTシークレット不要）。
ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")
_PROJECT_REF = ""
if SUPABASE_URL:
    try:
        _PROJECT_REF = SUPABASE_URL.split("//", 1)[1].split(".", 1)[0]
    except Exception:
        _PROJECT_REF = ""
SB_COOKIE_NAME = ("sb-" + _PROJECT_REF + "-auth-token") if _PROJECT_REF else ""

# access_token → 検証結果 の短期キャッシュ（トークンは毎回ネットワーク検証しない）
_sess_cache = {}   # token -> (expire_epoch, user_dict or None)
_SESS_TTL = 60     # 秒


def _b64url_json(s: str):
    import base64
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * ((4 - len(s) % 4) % 4)
    return json.loads(base64.b64decode(s).decode("utf-8"))


def _decode_jwt_claims(token: str) -> dict:
    try:
        return _b64url_json(token.split(".")[1])
    except Exception:
        return {}


def parse_sb_cookie(cookie_value: str):
    """sb-<ref>-auth-token の値から session(dict) を得る。"base64-" 形式に対応。"""
    if not cookie_value:
        return None
    try:
        raw = cookie_value
        if raw.startswith("base64-"):
            return _b64url_json(raw[len("base64-"):])
        return json.loads(raw)
    except Exception:
        return None


def validate_session(cookie_value: str):
    """共有Cookieを検証し、ログインユーザーを返す（無効なら None）。
    返り値: {email, user_id, is_hq, tenant_id, role} """
    import time
    if not (SUPABASE_URL and ANON_KEY):
        return None
    sess = parse_sb_cookie(cookie_value)
    if not sess or not sess.get("access_token"):
        return None
    token = sess["access_token"]

    now = time.time()
    hit = _sess_cache.get(token)
    if hit and hit[0] > now:
        return hit[1]

    # Supabase に access_token の有効性を確認
    ok = False
    try:
        req = urllib.request.Request(SUPABASE_URL + "/auth/v1/user", method="GET")
        req.add_header("apikey", ANON_KEY)
        req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            ok = (resp.status == 200)
    except Exception:
        ok = False

    result = None
    if ok:
        claims = _decode_jwt_claims(token)
        result = {
            "email": claims.get("email") or (sess.get("user") or {}).get("email"),
            "user_id": claims.get("sub") or (sess.get("user") or {}).get("id"),
            "is_hq": bool(claims.get("is_hq")),
            "tenant_id": claims.get("tenant_id"),
            "role": claims.get("user_role"),
            "via": "supabase",
        }
    _sess_cache[token] = (now + _SESS_TTL, result)
    if len(_sess_cache) > 500:
        _sess_cache.clear()
    return result


class SupabaseError(Exception):
    pass


def _request(method: str, path: str, query: dict = None, body=None, use_auth_admin=False):
    if not enabled():
        raise SupabaseError("Supabaseが未設定です（SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY）")
    url = SUPABASE_URL + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SERVICE_KEY)
    req.add_header("Authorization", "Bearer " + SERVICE_KEY)
    req.add_header("Content-Type", "application/json")
    if not use_auth_admin:
        # PostgREST: 返却件数や表現の指定
        req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        raise SupabaseError(f"Supabase {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise SupabaseError(f"接続失敗: {e.reason}")


# ---------- 読み取り（(a)(b) 用） ----------
def list_tenants():
    """全加盟企業。"""
    return _request("GET", "/rest/v1/tenant",
                    {"select": "id,name,corporate_number,realize_club_member_id,accounting_method,created_at",
                     "order": "created_at.asc"}) or []


def list_app_users():
    """全 app_user（テナント横断）。"""
    return _request("GET", "/rest/v1/app_user",
                    {"select": "id,tenant_id,email,role,is_hq,acting_tenant_id,created_at",
                     "order": "created_at.asc"}) or []


def list_auth_users():
    """Supabase Auth のユーザー（最終ログイン等）。Admin API。"""
    out = []
    page = 1
    while True:
        res = _request("GET", "/auth/v1/admin/users",
                       {"page": page, "per_page": 200}, use_auth_admin=True)
        users = (res or {}).get("users", []) if isinstance(res, dict) else (res or [])
        if not users:
            break
        out.extend(users)
        if len(users) < 200:
            break
        page += 1
        if page > 20:  # 安全弁
            break
    return out


def find_auth_user_by_email(email: str):
    """Auth に同じメールのユーザーが既にいれば返す（重複作成を防ぐ）。"""
    email = (email or "").strip().lower()
    for u in list_auth_users():
        if (u.get("email") or "").lower() == email:
            return u
    return None


ROLES = ("admin", "accountant", "viewer")


def create_tenant(name: str, rc_member_id: str = None):
    """加盟企業(tenant)を1件作る。既に同名があればそれを返す（重複防止）。"""
    name = (name or "").strip()
    if not name:
        raise SupabaseError("会社名が空です")
    existing = _request("GET", "/rest/v1/tenant",
                        {"select": "id,name,realize_club_member_id", "name": f"eq.{name}"})
    if existing:
        return existing[0]
    body = {"name": name}
    if rc_member_id:
        body["realize_club_member_id"] = rc_member_id
    created = _request("POST", "/rest/v1/tenant", body=body,
                       query={"select": "id,name,realize_club_member_id"})
    # PostgREST は Prefer 次第で配列/オブジェクトを返す
    row = created[0] if isinstance(created, list) else created
    if not row or not row.get("id"):
        # 返却が空でも作成はされている場合があるので取り直す
        again = _request("GET", "/rest/v1/tenant",
                         {"select": "id,name,realize_club_member_id", "name": f"eq.{name}"})
        row = again[0] if again else None
    if not row:
        raise SupabaseError("tenant作成の確認に失敗しました")
    return row


def add_member(email: str, tenant_id: str, role: str = "admin",
               mode: str = "invite", password: str = None):
    """加盟店の利用者を1件作る。
      mode='invite'  : 招待メールを送る（本人がパスワードを設定）
      mode='password': その場でパスワードを設定（email_confirm=true）
    既に同じメールの auth ユーザーがいれば、それを流用して app_user だけ紐付ける。
    戻り値: {'user_id', 'email', 'reused', 'mode'}
    """
    email = (email or "").strip().lower()
    role = role if role in ROLES else "admin"
    if "@" not in email:
        raise SupabaseError(f"メールアドレスが不正です: {email}")

    reused = False
    existing = find_auth_user_by_email(email)
    if existing:
        user_id = existing["id"]
        reused = True
    elif mode == "invite":
        res = _request("POST", "/auth/v1/admin/generate_link",
                       body={"type": "invite", "email": email}, use_auth_admin=True)
        # generate_link は user オブジェクトを含む
        user_id = ((res or {}).get("user") or {}).get("id") or (res or {}).get("id")
        if not user_id:
            u = find_auth_user_by_email(email)
            user_id = u["id"] if u else None
        if not user_id:
            raise SupabaseError("招待ユーザーの作成に失敗しました")
    else:  # password
        if not password or len(password) < 8:
            raise SupabaseError("パスワードは8文字以上にしてください")
        res = _request("POST", "/auth/v1/admin/users",
                       body={"email": email, "password": password, "email_confirm": True},
                       use_auth_admin=True)
        user_id = (res or {}).get("id")
        if not user_id:
            raise SupabaseError("ユーザー作成に失敗しました")

    # app_user に紐付け（upsert）
    _request("POST", "/rest/v1/app_user",
             body={"id": user_id, "tenant_id": tenant_id, "role": role, "email": email},
             query={"on_conflict": "id"})
    return {"user_id": user_id, "email": email, "reused": reused, "mode": mode}


def add_company(name: str, email: str, rc_member_id: str = None,
                role: str = "admin", mode: str = "invite", password: str = None):
    """加盟店を1社追加する（tenant作成 → 利用者作成 → 紐付け）。"""
    tenant = create_tenant(name, rc_member_id)
    member = add_member(email, tenant["id"], role=role, mode=mode, password=password)
    return {"tenant": tenant, "member": member}


def set_hq(email: str, is_hq: bool = True):
    """指定メールの利用者を本部(hq)に昇格/解除する。app_user.is_hq を更新。"""
    u = find_auth_user_by_email(email)
    if not u:
        raise SupabaseError(f"Supabaseに {email} が見つかりません。先に加盟店/ユーザーとして登録してください。")
    _request("PATCH", "/rest/v1/app_user",
             query={"id": f"eq.{u['id']}"},
             body={"is_hq": bool(is_hq)})
    return {"user_id": u["id"], "email": email, "is_hq": bool(is_hq)}


def set_acting_tenant(user_id: str, tenant_id: str = None):
    """本部が「見る加盟店」を切り替える。tenant_id=None で解除（自分に戻る）。
    is_hq=true の利用者にのみ意味がある（フックが is_hq を見て適用）。"""
    _request("PATCH", "/rest/v1/app_user",
             query={"id": f"eq.{user_id}"},
             body={"acting_tenant_id": tenant_id})
    return {"user_id": user_id, "acting_tenant_id": tenant_id}


def get_app_user_by_email(email: str):
    """app_user 行（is_hq / acting_tenant_id 含む）をメールで取得。"""
    u = find_auth_user_by_email(email)
    if not u:
        return None
    rows = _request("GET", "/rest/v1/app_user",
                    {"select": "id,tenant_id,email,role,is_hq,acting_tenant_id", "id": f"eq.{u['id']}"})
    return rows[0] if rows else None


def set_user_active(user_id: str, active: bool):
    """利用者の有効/停止。Supabaseはban_durationで無効化する。"""
    dur = "none" if active else "876000h"  # 停止=100年 ban
    _request("PUT", f"/auth/v1/admin/users/{user_id}",
             body={"ban_duration": dur}, use_auth_admin=True)
    return {"user_id": user_id, "active": active}


def overview():
    """本部ダッシュボード用に、加盟店ごとの利用状況を組み立てる（読み取りのみ）。"""
    tenants = list_tenants()
    app_users = list_app_users()
    auth_users = {u.get("id"): u for u in list_auth_users()}

    # tenant_id → 所属ユーザー
    by_tenant = {}
    for au in app_users:
        by_tenant.setdefault(au.get("tenant_id"), []).append(au)

    rows = []
    for t in tenants:
        members = by_tenant.get(t["id"], [])
        enriched = []
        last_login = None
        for m in members:
            info = auth_users.get(m["id"], {})
            ll = info.get("last_sign_in_at")
            if ll and (last_login is None or ll > last_login):
                last_login = ll
            enriched.append({
                "email": m.get("email") or info.get("email"),
                "role": m.get("role"),
                "is_hq": m.get("is_hq", False),
                "last_sign_in_at": ll,
                "confirmed": bool(info.get("email_confirmed_at") or info.get("confirmed_at")),
            })
        rows.append({
            "tenant_id": t["id"],
            "name": t["name"],
            "rc_member_id": t.get("realize_club_member_id"),
            "member_count": len(members),
            "last_login": last_login,
            "members": enriched,
            "created_at": t.get("created_at"),
        })

    return {
        "tenant_count": len(tenants),
        "user_count": len(app_users),
        "auth_user_count": len(auth_users),
        "hq_count": sum(1 for u in app_users if u.get("is_hq")),
        "tenants": rows,
    }
