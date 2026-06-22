"""
HubSpot 連携（外部CRM同期）— ゲート式。
- 環境変数 HUBSPOT_TOKEN（Private App トークン）が無ければ全機能オフ（is_configured()==False）。
- ローカルの会社/担当者/商談を HubSpot へ push（作成 or 更新）。重複作成を防ぐため hubspot_id を保持。
- HubSpot の会社を pull してローカルへ取り込む（基本実装）。
- 通信は httpx（openai SDK 依存で同梱済み）。外部呼び出しは全て try/except で安全に。

⚠️ 実接続の検証には HubSpot の Private App トークンが必要（未提供のため未検証）。
   トークンを HUBSPOT_TOKEN に設定すれば有効化される（AI機能と同じ「設定したら動く」方式）。
"""
import os
from datetime import datetime

import database as db

API = "https://api.hubapi.com"


def _token() -> str:
    return os.getenv("HUBSPOT_TOKEN", "").strip()


def is_configured() -> bool:
    return bool(_token())


def status() -> dict:
    return {"configured": is_configured()}


def _client():
    import httpx
    return httpx.Client(
        base_url=API,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        timeout=20.0,
    )


def _upsert(client, obj_type: str, hubspot_id, properties: dict):
    """hubspot_id があれば PATCH(更新)、無ければ POST(作成)。新規IDを返す。"""
    # 空値は送らない
    props = {k: v for k, v in properties.items() if v not in (None, "")}
    if hubspot_id:
        r = client.patch(f"/crm/v3/objects/{obj_type}/{hubspot_id}", json={"properties": props})
        if r.status_code == 404:  # 既に削除されていたら作り直す
            r = client.post(f"/crm/v3/objects/{obj_type}", json={"properties": props})
    else:
        r = client.post(f"/crm/v3/objects/{obj_type}", json={"properties": props})
    r.raise_for_status()
    return r.json().get("id")


def push_all() -> dict:
    """ローカルの会社・担当者・商談を HubSpot へ同期する。"""
    if not is_configured():
        return {"ok": False, "error": "HUBSPOT_TOKEN が未設定です。"}

    result = {"ok": True, "companies": 0, "contacts": 0, "deals": 0, "errors": []}
    conn = db.get_conn()
    try:
        client = _client()
        with client:
            # 会社
            for c in conn.execute("SELECT * FROM companies").fetchall():
                try:
                    hid = _upsert(client, "companies", c["hubspot_id"], {
                        "name": c["name"], "phone": c["phone"],
                        "address": c["address"], "website": c["website"],
                    })
                    if hid and hid != c["hubspot_id"]:
                        conn.execute("UPDATE companies SET hubspot_id=? WHERE id=?", (hid, c["id"]))
                        conn.commit()
                    result["companies"] += 1
                except Exception as e:
                    result["errors"].append(f"会社「{c['name']}」: {str(e)[:120]}")

            # 担当者（contacts は email がキー。無ければ氏名で作成）
            for ct in conn.execute("SELECT * FROM contacts").fetchall():
                try:
                    hid = _upsert(client, "contacts", ct["hubspot_id"], {
                        "firstname": ct["name"], "email": ct["email"],
                        "phone": ct["phone"], "jobtitle": ct["title"],
                    })
                    if hid and hid != ct["hubspot_id"]:
                        conn.execute("UPDATE contacts SET hubspot_id=? WHERE id=?", (hid, ct["id"]))
                        conn.commit()
                    result["contacts"] += 1
                except Exception as e:
                    result["errors"].append(f"担当者「{ct['name']}」: {str(e)[:120]}")

            # 商談（dealstage はパイプライン依存のため送らない＝安全側）
            for d in conn.execute("SELECT * FROM deals").fetchall():
                try:
                    hid = _upsert(client, "deals", d["hubspot_id"], {
                        "dealname": d["title"],
                        "amount": str(d["amount"] or 0),
                    })
                    if hid and hid != d["hubspot_id"]:
                        conn.execute("UPDATE deals SET hubspot_id=? WHERE id=?", (hid, d["id"]))
                        conn.commit()
                    result["deals"] += 1
                except Exception as e:
                    result["errors"].append(f"商談「{d['title']}」: {str(e)[:120]}")
    finally:
        conn.close()
    return result


def pull_companies(limit: int = 100) -> dict:
    """HubSpot の会社をローカルへ取り込む（hubspot_id で重複回避）。"""
    if not is_configured():
        return {"ok": False, "error": "HUBSPOT_TOKEN が未設定です。"}

    result = {"ok": True, "imported": 0, "updated": 0, "errors": []}
    conn = db.get_conn()
    try:
        client = _client()
        with client:
            r = client.get("/crm/v3/objects/companies",
                           params={"limit": min(limit, 100), "properties": "name,phone,address,website"})
            r.raise_for_status()
            now = datetime.now().isoformat(timespec="seconds")
            for item in r.json().get("results", []):
                hid = item.get("id")
                p = item.get("properties", {})
                name = p.get("name") or "(名称未設定)"
                existing = conn.execute("SELECT id FROM companies WHERE hubspot_id=?", (hid,)).fetchone()
                if existing:
                    conn.execute("UPDATE companies SET name=?, phone=?, address=?, website=? WHERE id=?",
                                 (name, p.get("phone"), p.get("address"), p.get("website"), existing["id"]))
                    result["updated"] += 1
                else:
                    conn.execute(
                        "INSERT INTO companies (name, phone, address, website, notes, hubspot_id, created_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (name, p.get("phone"), p.get("address"), p.get("website"),
                         "HubSpotから取り込み", hid, now))
                    result["imported"] += 1
            conn.commit()
    except Exception as e:
        result = {"ok": False, "error": str(e)[:200]}
    finally:
        conn.close()
    return result
