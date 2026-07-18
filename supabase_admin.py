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
