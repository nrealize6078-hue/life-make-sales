"""
営業支援ツール  -  FastAPI バックエンド
6機能: タスク抽出 / CRM / 営業育成 / ヒアリングシート(音声) / 商談フロー / 面談管理
すべて1つのSQLite DBを共有し、顧客・商談データが連動する。
"""
import os
import json
import uuid
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Optional, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
import auth
import hubspot_sync
from task_extractor import extract_tasks
from hearing_parser import parse_hearing
from ai_services.config import settings as ai_settings  # これで .env が読み込まれる
from ai_services import jobs_sql
from ai_services.diarize import format_dialogue
from ai_services.ai import generate_minutes as ai_generate_minutes, generate_talk_points as ai_talk_points, AIError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# ----- ログイン認証(ユーザー別アカウント / ロール / セッション失効) -----
# 互換: ユーザーが居らず APP_PASSWORD があれば admin を自動作成して認証ON。
#       ユーザーも APP_PASSWORD も無ければ認証OFF(従来どおり全公開)。
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
_COOKIE = "lms_session"

# ----- 横断ログイン(SSO) -----
# SSO_COOKIE_DOMAIN に ".lifemakepartners.net" を設定すると、Cookie が
# 全サブドメイン(ポータル/eラーニング/SALES/ロープレ/会計系…)へ共有され、
# 1回のログインで全ツールに入れる。未設定なら従来どおりこのホスト限定。
SSO_COOKIE_DOMAIN = os.getenv("SSO_COOKIE_DOMAIN", "").strip()
# ログインAPIを呼べるオリジン(ポータル等)。カンマ区切り。
SSO_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("SSO_ALLOWED_ORIGINS", "").split(",") if o.strip()
]


def _set_session_cookie(response: Response, token: str):
    """セッションCookieを発行する。SSO_COOKIE_DOMAIN 指定時はサブドメイン共通で発行。"""
    kw = dict(httponly=True, samesite="lax", max_age=60 * 60 * 24 * auth.SESSION_DAYS, path="/")
    if SSO_COOKIE_DOMAIN:
        kw["domain"] = SSO_COOKIE_DOMAIN
        kw["secure"] = True  # 本番(https)前提。共通Cookieは必ずSecureで。
    response.set_cookie(_COOKIE, token, **kw)


def _clear_session_cookie(response: Response):
    if SSO_COOKIE_DOMAIN:
        response.delete_cookie(_COOKIE, path="/", domain=SSO_COOKIE_DOMAIN)
    else:
        _clear_session_cookie(response)


def _current_user(request: Request):
    """Cookie のセッショントークンから現在のユーザーを返す(無効なら None)。"""
    return auth.get_session_user(request.cookies.get(_COOKIE))


def _is_authed(request: Request) -> bool:
    return (not auth.auth_enabled()) or _current_user(request) is not None


def _require_admin(request: Request):
    u = _current_user(request)
    if not auth.auth_enabled():
        return None  # 認証OFF時は誰でも管理操作可(ローカル単独利用)
    if not u or not auth.is_hq(u.get("role")):
        raise HTTPException(403, "管理者権限が必要です")
    return u


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時にDB初期化（on_event は非推奨のため lifespan を使用）
    db.init_db()
    auth.bootstrap(APP_PASSWORD)  # 初回のみ admin を自動作成
    auth.purge_expired()          # 期限切れセッションを掃除
    jobs_sql.recover_stuck()      # 中断したAI処理を queued に戻す
    jobs_sql.start_worker()       # DBキューを処理する常駐ワーカーを開始
    yield
    jobs_sql.stop_worker()        # 終了時にワーカーを停止


app = FastAPI(title="ライフメイクセールス (Life Make Sales)", version="3.0.0", lifespan=lifespan)


@app.middleware("http")
async def _no_cache_static(request, call_next):
    """静的ファイル更新後に古いJS/CSSが残らないよう、再検証を強制する。"""
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.startswith("/static"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    # lifemakepartners.net ポータル(lmp.html)からの iframe 埋め込みを許可。
    # それ以外はデフォルトで DENY 相当(frame-ancestors 'self' 系のみ)。
    resp.headers.setdefault(
        "Content-Security-Policy",
        "frame-ancestors 'self' https://lifemakepartners.net https://www.lifemakepartners.net",
    )
    return resp


@app.middleware("http")
async def _sso_cors(request: Request, call_next):
    """横断ログイン用のCORS。SSO_ALLOWED_ORIGINS に載ったオリジン(ポータル等)から
    /api/auth/* を Cookie 付きで呼べるようにする。他のオリジン・他のパスには付けない。"""
    origin = request.headers.get("origin", "")
    allowed = origin in SSO_ALLOWED_ORIGINS and request.url.path.startswith("/api/auth/")

    if allowed and request.method == "OPTIONS":  # プリフライト
        resp = Response(status_code=204)
    else:
        resp = await call_next(request)

    if allowed:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Vary"] = "Origin"
    return resp


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    """認証ON時、業務API(/api/*)を保護する。認証/ヘルスは除外。"""
    p = request.url.path
    if p.startswith("/api/") and not p.startswith("/api/auth/") and p != "/api/ai/health":
        if not _is_authed(request):
            return JSONResponse({"detail": "ログインが必要です"}, status_code=401)
    return await call_next(request)


class LoginIn(BaseModel):
    username: Optional[str] = None
    password: str


class SignupIn(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    code: str


class RegisterCodeIn(BaseModel):
    code: str


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "member"
    display_name: Optional[str] = None


class UserUpdateIn(BaseModel):
    role: Optional[str] = None
    active: Optional[bool] = None
    display_name: Optional[str] = None


class PasswordIn(BaseModel):
    password: str


@app.get("/api/auth/me")
def auth_me(request: Request):
    u = _current_user(request)
    return {
        "auth_enabled": auth.auth_enabled(),
        "authenticated": _is_authed(request),
        "user": u,
        "is_admin": auth.is_hq((u or {}).get("role")) if u else (not auth.auth_enabled()),
    }


@app.post("/api/auth/login")
def auth_login(body: LoginIn, response: Response):
    if not auth.auth_enabled():
        return {"ok": True, "note": "認証は無効です"}
    username = (body.username or "admin").strip()  # 旧UI(username無し)は admin とみなす
    user = auth.get_user_by_name(username)
    if not user or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "ユーザー名またはパスワードが違います")
    token = auth.create_session(user["id"])
    _set_session_cookie(response, token)
    return {"ok": True, "user": {"username": user["username"], "role": user["role"], "display_name": user["display_name"]}}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    auth.revoke_session(request.cookies.get(_COOKIE))
    _clear_session_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request):
    """横断ログインの検証API。各ツールはこれを呼んでログイン状態と権限を判定する。

    返り値: {"authenticated": bool, "user": {...} | None}
      user.role      … hq(本部) / company(会社) / member(社員)  ※admin は hq 相当
      user.company_id… 所属会社ID(本部は None)
      user.is_hq     … 本部かどうか
    """
    u = _current_user(request)
    return {"authenticated": u is not None, "user": u}


# ----- 新規登録（登録コード方式） -----
@app.get("/api/auth/signup_info")
def signup_info():
    """新規登録が有効か（＝登録コードが設定されているか）。"""
    return {"signup_enabled": bool(auth.get_setting("register_code", "").strip())}


@app.post("/api/auth/signup")
def auth_signup(body: SignupIn, response: Response):
    code = auth.get_setting("register_code", "").strip()
    if not code:
        raise HTTPException(400, "現在、新規登録は受け付けていません（管理者が登録コード未設定）")
    if (body.code or "").strip() != code:
        raise HTTPException(403, "登録コードが違います")
    try:
        uid = auth.create_user(body.username, body.password, role="member", display_name=body.display_name or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    token = auth.create_session(uid)
    _set_session_cookie(response, token)
    return {"ok": True}


# ----- 登録コードの設定（管理者のみ） -----
@app.get("/api/settings/register_code")
def get_register_code(request: Request):
    _require_admin(request)
    return {"code": auth.get_setting("register_code", "")}


@app.post("/api/settings/register_code")
def set_register_code(body: RegisterCodeIn, request: Request):
    _require_admin(request)
    auth.set_setting("register_code", (body.code or "").strip())
    return {"ok": True}


# ----- 自分のパスワード変更 -----
@app.post("/api/account/password")
def change_my_password(body: PasswordIn, request: Request):
    u = _current_user(request)
    if auth.auth_enabled() and not u:
        raise HTTPException(401, "ログインが必要です")
    if not u:
        raise HTTPException(400, "認証が無効のため変更できません")
    try:
        auth.set_password(u["id"], body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ----- ユーザー管理(管理者のみ) -----
@app.get("/api/users")
def users_list(request: Request):
    _require_admin(request)
    return auth.list_users()


@app.post("/api/users")
def users_create(body: UserIn, request: Request):
    _require_admin(request)
    try:
        uid = auth.create_user(body.username, body.password, body.role, body.display_name or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": uid}


@app.patch("/api/users/{user_id}")
def users_update(user_id: int, body: UserUpdateIn, request: Request):
    _require_admin(request)
    try:
        auth.update_user(user_id, role=body.role, active=body.active, display_name=body.display_name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/users/{user_id}/password")
def users_set_password(user_id: int, body: PasswordIn, request: Request):
    _require_admin(request)
    try:
        auth.set_password(user_id, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/users/{user_id}")
def users_delete(user_id: int, request: Request):
    admin = _require_admin(request)
    if admin and admin["id"] == user_id:
        raise HTTPException(400, "自分自身は削除できません")
    auth.delete_user(user_id)
    return {"ok": True}


# ----- HubSpot 連携(外部CRM同期) -----
@app.get("/api/integrations/hubspot/status")
def hubspot_status():
    return hubspot_sync.status()


@app.post("/api/integrations/hubspot/push")
def hubspot_push(request: Request):
    _require_admin(request)
    if not hubspot_sync.is_configured():
        raise HTTPException(400, "HUBSPOT_TOKEN が未設定です。サーバーの .env に設定してください。")
    return hubspot_sync.push_all()


@app.post("/api/integrations/hubspot/pull")
def hubspot_pull(request: Request):
    _require_admin(request)
    if not hubspot_sync.is_configured():
        raise HTTPException(400, "HUBSPOT_TOKEN が未設定です。サーバーの .env に設定してください。")
    return hubspot_sync.pull_companies()


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


# ============================================================
#  Pydantic モデル（リクエストボディ）
# ============================================================
class CompanyIn(BaseModel):
    name: str
    customer_type: str = "btob"   # btob=法人 / btoc=個人
    industry: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None


class ProgressLogIn(BaseModel):
    log_date: str
    status: Optional[str] = None
    note: Optional[str] = None


class ContactIn(BaseModel):
    company_id: Optional[int] = None
    name: str
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class DealIn(BaseModel):
    company_id: Optional[int] = None
    title: str
    stage: str = "反響・予約"
    amount: int = 0
    probability: int = 0
    expected_close: Optional[str] = None
    owner: Optional[str] = None
    notes: Optional[str] = None


class StageIn(BaseModel):
    stage: str


class TaskIn(BaseModel):
    title: str
    source_text: Optional[str] = None
    due_date: Optional[str] = None
    priority: str = "中"
    status: str = "未着手"
    company_id: Optional[int] = None
    deal_id: Optional[int] = None


class TaskUpdateIn(BaseModel):
    title: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None


class ExtractIn(BaseModel):
    text: str


class BulkTasksIn(BaseModel):
    tasks: List[TaskIn]


class VoiceParseIn(BaseModel):
    text: str


class MeetingIn(BaseModel):
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    deal_id: Optional[int] = None
    title: str
    scheduled_at: Optional[str] = None
    duration_min: int = 60
    location: Optional[str] = None
    meeting_type: str = "オンライン"
    status: str = "予定"
    agenda: Optional[str] = None
    minutes: Optional[str] = None
    attendees: Optional[str] = None   # 同席者（ご家族など・個人面談向け）


class HearingIn(BaseModel):
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    deal_id: Optional[int] = None
    title: str
    current_situation: Optional[str] = None
    challenges: Optional[str] = None
    needs: Optional[str] = None
    budget: Optional[str] = None
    authority: Optional[str] = None
    timeline: Optional[str] = None
    competitors: Optional[str] = None
    next_action: Optional[str] = None
    raw_voice_text: Optional[str] = None


class ProgressIn(BaseModel):
    module_id: int
    member: str
    status: str = "未学習"
    score: Optional[int] = None
    memo: Optional[str] = None


def _validate_stage(stage: str) -> str:
    """不正なステージは弾く（ダッシュボード集計の500を根本防止）。"""
    if stage not in db.DEAL_STAGES:
        raise HTTPException(400, f"不正なステージです: {stage}")
    return stage


# ============================================================
#  ダッシュボード集計（リッチ化）
# ============================================================
@app.get("/api/dashboard")
def dashboard():
    conn = db.get_conn()
    try:
        c = conn.cursor()
        companies = c.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        open_deals = c.execute(
            "SELECT COUNT(*) FROM deals WHERE stage NOT IN ('契約','失注')"
        ).fetchone()[0]
        won = c.execute("SELECT COUNT(*) FROM deals WHERE stage='契約'").fetchone()[0]
        lost = c.execute("SELECT COUNT(*) FROM deals WHERE stage='失注'").fetchone()[0]
        pipeline_amount = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM deals WHERE stage NOT IN ('契約','失注')"
        ).fetchone()[0]
        won_amount = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM deals WHERE stage='契約'"
        ).fetchone()[0]
        # 加重見込み（金額 × 確度）
        weighted = c.execute(
            "SELECT COALESCE(SUM(amount * probability / 100.0),0) FROM deals WHERE stage NOT IN ('契約','失注')"
        ).fetchone()[0]
        open_tasks = c.execute("SELECT COUNT(*) FROM tasks WHERE status != '完了'").fetchone()[0]
        upcoming = c.execute("SELECT COUNT(*) FROM meetings WHERE status='予定'").fetchone()[0]

        today = date.today().isoformat()
        overdue_tasks = c.execute(
            "SELECT COUNT(*) FROM tasks WHERE status != '完了' AND due_date IS NOT NULL AND due_date < ?",
            (today,),
        ).fetchone()[0]

        win_rate = round(won / (won + lost) * 100) if (won + lost) > 0 else 0
        # クローザー向けKPI
        avg_won_amount = round(won_amount / won) if won > 0 else 0
        from datetime import datetime as _dt, timedelta as _td
        _today = _dt.now()
        _week_start = (_today - _td(days=_today.weekday())).date().isoformat()
        _week_end = (_today - _td(days=_today.weekday()) + _td(days=7)).date().isoformat()
        this_week_meetings = c.execute(
            "SELECT COUNT(*) FROM meetings WHERE scheduled_at >= ? AND scheduled_at < ?",
            (_week_start, _week_end),
        ).fetchone()[0]

        # ステージ別件数・金額（未知ステージでも壊れないよう setdefault）
        stage_counts = {s: 0 for s in db.DEAL_STAGES}
        stage_amounts = {s: 0 for s in db.DEAL_STAGES}
        for row in c.execute(
            "SELECT stage, COUNT(*) c, COALESCE(SUM(amount),0) a FROM deals GROUP BY stage"
        ).fetchall():
            stage_counts.setdefault(row["stage"], 0)
            stage_amounts.setdefault(row["stage"], 0)
            stage_counts[row["stage"]] = row["c"]
            stage_amounts[row["stage"]] = row["a"]

        # 今日以降の面談（直近5件）
        upcoming_meetings = rows_to_dicts(c.execute(
            "SELECT m.id, m.title, m.scheduled_at, m.meeting_type, co.name AS company_name "
            "FROM meetings m LEFT JOIN companies co ON m.company_id=co.id "
            "WHERE m.status='予定' ORDER BY m.scheduled_at IS NULL, m.scheduled_at LIMIT 5"
        ).fetchall())

        # 未完了タスク（優先度・期限順、直近6件）
        todo = rows_to_dicts(c.execute(
            "SELECT t.id, t.title, t.due_date, t.priority, co.name AS company_name "
            "FROM tasks t LEFT JOIN companies co ON t.company_id=co.id "
            "WHERE t.status != '完了' "
            "ORDER BY CASE t.priority WHEN '高' THEN 0 WHEN '中' THEN 1 ELSE 2 END, "
            "t.due_date IS NULL, t.due_date LIMIT 6"
        ).fetchall())

        return {
            "companies": companies,
            "open_deals": open_deals,
            "won": won,
            "lost": lost,
            "pipeline_amount": pipeline_amount,
            "won_amount": won_amount,
            "weighted_amount": round(weighted),
            "open_tasks": open_tasks,
            "overdue_tasks": overdue_tasks,
            "upcoming_meetings": upcoming,
            "win_rate": win_rate,
            "avg_won_amount": avg_won_amount,
            "this_week_meetings": this_week_meetings,
            "stage_counts": stage_counts,
            "stage_amounts": stage_amounts,
            "today_str": today,
            "upcoming_meeting_list": upcoming_meetings,
            "todo_list": todo,
        }
    finally:
        conn.close()


@app.get("/api/activity")
def activity(limit: int = 12):
    """各テーブルの最近の更新を統合したアクティビティ履歴。"""
    conn = db.get_conn()
    try:
        items = []
        for row in conn.execute(
            "SELECT d.title, d.updated_at AS ts, d.stage, co.name AS company FROM deals d "
            "LEFT JOIN companies co ON d.company_id=co.id ORDER BY d.updated_at DESC LIMIT ?", (limit,)
        ).fetchall():
            items.append({"type": "deal", "icon": "📈", "text": f"商談「{row['title']}」（{row['stage']}）", "company": row["company"], "ts": row["ts"]})
        for row in conn.execute(
            "SELECT m.title, m.created_at AS ts, co.name AS company FROM meetings m "
            "LEFT JOIN companies co ON m.company_id=co.id ORDER BY m.created_at DESC LIMIT ?", (limit,)
        ).fetchall():
            items.append({"type": "meeting", "icon": "📅", "text": f"面談「{row['title']}」", "company": row["company"], "ts": row["ts"]})
        for row in conn.execute(
            "SELECT h.title, h.created_at AS ts, co.name AS company FROM hearing_sheets h "
            "LEFT JOIN companies co ON h.company_id=co.id ORDER BY h.created_at DESC LIMIT ?", (limit,)
        ).fetchall():
            items.append({"type": "hearing", "icon": "🎤", "text": f"ヒアリング「{row['title']}」", "company": row["company"], "ts": row["ts"]})
        for row in conn.execute(
            "SELECT t.title, t.created_at AS ts, co.name AS company FROM tasks t "
            "LEFT JOIN companies co ON t.company_id=co.id ORDER BY t.created_at DESC LIMIT ?", (limit,)
        ).fetchall():
            items.append({"type": "task", "icon": "✅", "text": f"タスク「{row['title']}」", "company": row["company"], "ts": row["ts"]})
        items.sort(key=lambda x: x["ts"] or "", reverse=True)
        return items[:limit]
    finally:
        conn.close()


# ============================================================
#  CRM: 会社
# ============================================================
@app.get("/api/companies")
def list_companies():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT c.*, "
            "(SELECT COUNT(*) FROM deals d WHERE d.company_id=c.id AND d.stage NOT IN ('契約','失注')) AS open_deals, "
            "(SELECT COUNT(*) FROM contacts ct WHERE ct.company_id=c.id) AS contact_count "
            "FROM companies c ORDER BY c.created_at DESC"
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.get("/api/companies/{company_id}")
def get_company(company_id: int):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        if not row:
            raise HTTPException(404, "会社が見つかりません")
        company = dict(row)
        company["contacts"] = rows_to_dicts(
            conn.execute("SELECT * FROM contacts WHERE company_id=? ORDER BY id", (company_id,)).fetchall())
        company["deals"] = rows_to_dicts(
            conn.execute("SELECT * FROM deals WHERE company_id=? ORDER BY updated_at DESC", (company_id,)).fetchall())
        company["meetings"] = rows_to_dicts(
            conn.execute("SELECT * FROM meetings WHERE company_id=? ORDER BY scheduled_at DESC", (company_id,)).fetchall())
        company["tasks"] = rows_to_dicts(
            conn.execute("SELECT * FROM tasks WHERE company_id=? ORDER BY (status='完了'), created_at DESC", (company_id,)).fetchall())
        company["hearings"] = rows_to_dicts(
            conn.execute("SELECT id, title, created_at FROM hearing_sheets WHERE company_id=? ORDER BY created_at DESC", (company_id,)).fetchall())
        company["progress"] = rows_to_dicts(
            conn.execute("SELECT * FROM progress_logs WHERE company_id=? ORDER BY log_date DESC, id DESC", (company_id,)).fetchall())
        return company
    finally:
        conn.close()


# ----- 顧客の進捗ログ（日付ごとの進捗状況） -----
@app.get("/api/companies/{company_id}/progress")
def list_progress_logs(company_id: int):
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM progress_logs WHERE company_id=? ORDER BY log_date DESC, id DESC", (company_id,)).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.post("/api/companies/{company_id}/progress")
def add_progress_log(company_id: int, body: ProgressLogIn):
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO progress_logs (company_id, log_date, status, note, created_at) VALUES (?,?,?,?,?)",
            (company_id, body.log_date, body.status, body.note, now_iso()),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.delete("/api/progress/{log_id}")
def delete_progress_log(log_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM progress_logs WHERE id=?", (log_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/companies")
def create_company(body: CompanyIn):
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO companies (name, customer_type, industry, address, phone, email, website, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (body.name, body.customer_type or "btob", body.industry, body.address, body.phone,
             body.email, body.website, body.notes, now_iso()),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/companies/{company_id}")
def update_company(company_id: int, body: CompanyIn):
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE companies SET name=?, customer_type=?, industry=?, address=?, phone=?, email=?, website=?, notes=? WHERE id=?",
            (body.name, body.customer_type or "btob", body.industry, body.address, body.phone,
             body.email, body.website, body.notes, company_id),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/companies/{company_id}")
def delete_company(company_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM companies WHERE id=?", (company_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ============================================================
#  CRM: 担当者
# ============================================================
@app.get("/api/contacts")
def list_contacts():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT c.*, co.name AS company_name FROM contacts c "
            "LEFT JOIN companies co ON c.company_id=co.id ORDER BY c.id DESC"
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.post("/api/contacts")
def create_contact(body: ContactIn):
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO contacts (company_id, name, title, email, phone, notes, created_at) VALUES (?,?,?,?,?,?,?)",
            (body.company_id, body.name, body.title, body.email, body.phone, body.notes, now_iso()),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.delete("/api/contacts/{contact_id}")
def delete_contact(contact_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ============================================================
#  商談フロー: 商談（パイプライン）
# ============================================================
@app.get("/api/stages")
def get_stages():
    return db.DEAL_STAGES


@app.get("/api/deals")
def list_deals():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT d.*, co.name AS company_name FROM deals d "
            "LEFT JOIN companies co ON d.company_id=co.id ORDER BY d.updated_at DESC"
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.post("/api/deals")
def create_deal(body: DealIn):
    _validate_stage(body.stage)
    conn = db.get_conn()
    try:
        ts = now_iso()
        cur = conn.execute(
            "INSERT INTO deals (company_id, title, stage, amount, probability, expected_close, owner, notes, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (body.company_id, body.title, body.stage, body.amount, body.probability,
             body.expected_close, body.owner, body.notes, ts, ts),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/deals/{deal_id}")
def update_deal(deal_id: int, body: DealIn):
    _validate_stage(body.stage)
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE deals SET company_id=?, title=?, stage=?, amount=?, probability=?, expected_close=?, owner=?, notes=?, updated_at=? WHERE id=?",
            (body.company_id, body.title, body.stage, body.amount, body.probability,
             body.expected_close, body.owner, body.notes, now_iso(), deal_id),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.patch("/api/deals/{deal_id}/stage")
def move_deal_stage(deal_id: int, body: StageIn):
    """商談フローのカード移動（ステージ変更）専用。"""
    _validate_stage(body.stage)
    conn = db.get_conn()
    try:
        # 契約/失注に動かしたら確度も自動調整
        prob = None
        if body.stage == "契約":
            prob = 100
        elif body.stage == "失注":
            prob = 0
        if prob is not None:
            conn.execute("UPDATE deals SET stage=?, probability=?, updated_at=? WHERE id=?",
                         (body.stage, prob, now_iso(), deal_id))
        else:
            conn.execute("UPDATE deals SET stage=?, updated_at=? WHERE id=?",
                         (body.stage, now_iso(), deal_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# 4章プレゼンの進捗チェックリスト(家は買うべき→今→ここ→うち)
PRESENTATION_STEPS = ["人生相談", "①家は買うべき", "②今買うべき", "③ここを買うべき", "④うちから買うべき", "資金計画", "クロージング"]


class PresentationIn(BaseModel):
    presentation: dict  # {"①家は買うべき": true, ...}


@app.get("/api/presentation_steps")
def presentation_steps():
    return {"steps": PRESENTATION_STEPS}


@app.patch("/api/deals/{deal_id}/presentation")
def update_presentation(deal_id: int, body: PresentationIn):
    conn = db.get_conn()
    try:
        if not conn.execute("SELECT 1 FROM deals WHERE id=?", (deal_id,)).fetchone():
            raise HTTPException(404, "商談が見つかりません")
        conn.execute("UPDATE deals SET presentation=?, updated_at=? WHERE id=?",
                     (json.dumps(body.presentation, ensure_ascii=False), now_iso(), deal_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/deals/{deal_id}")
def delete_deal(deal_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM deals WHERE id=?", (deal_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ============================================================
#  タスク抽出 / タスク管理
# ============================================================
@app.post("/api/tasks/extract")
def tasks_extract(body: ExtractIn):
    """自由文からタスク候補を返す（DBには保存しない。プレビュー用）。"""
    return {"candidates": extract_tasks(body.text)}


@app.get("/api/tasks")
def list_tasks():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT t.*, co.name AS company_name, d.title AS deal_title FROM tasks t "
            "LEFT JOIN companies co ON t.company_id=co.id "
            "LEFT JOIN deals d ON t.deal_id=d.id "
            "ORDER BY (t.status='完了'), "
            "CASE t.priority WHEN '高' THEN 0 WHEN '中' THEN 1 ELSE 2 END, "
            "t.due_date IS NULL, t.due_date"
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.post("/api/tasks")
def create_task(body: TaskIn):
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO tasks (title, source_text, due_date, priority, status, company_id, deal_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (body.title, body.source_text, body.due_date, body.priority, body.status,
             body.company_id, body.deal_id, now_iso()),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.post("/api/tasks/bulk")
def create_tasks_bulk(body: BulkTasksIn):
    """複数タスクを一括登録（議事録/ヒアリングからの抽出連携用）。"""
    conn = db.get_conn()
    try:
        ts = now_iso()
        n = 0
        for t in body.tasks:
            conn.execute(
                "INSERT INTO tasks (title, source_text, due_date, priority, status, company_id, deal_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (t.title, t.source_text, t.due_date, t.priority, t.status, t.company_id, t.deal_id, ts),
            )
            n += 1
        conn.commit()
        return {"created": n}
    finally:
        conn.close()


@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdateIn):
    conn = db.get_conn()
    try:
        cur = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not cur:
            raise HTTPException(404, "タスクが見つかりません")
        old = dict(cur)
        title = body.title if body.title is not None else old["title"]
        due_date = body.due_date if body.due_date is not None else old["due_date"]
        priority = body.priority if body.priority is not None else old["priority"]
        status = body.status if body.status is not None else old["status"]
        if status == "完了":
            done_at = now_iso() if old["status"] != "完了" else old["done_at"]
        else:
            done_at = None
        conn.execute(
            "UPDATE tasks SET title=?, due_date=?, priority=?, status=?, done_at=? WHERE id=?",
            (title, due_date, priority, status, done_at, task_id),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ============================================================
#  面談管理
# ============================================================
@app.get("/api/meetings")
def list_meetings():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT m.*, co.name AS company_name, ct.name AS contact_name, d.title AS deal_title "
            "FROM meetings m "
            "LEFT JOIN companies co ON m.company_id=co.id "
            "LEFT JOIN contacts ct ON m.contact_id=ct.id "
            "LEFT JOIN deals d ON m.deal_id=d.id "
            "ORDER BY m.scheduled_at IS NULL, m.scheduled_at"
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.post("/api/meetings")
def create_meeting(body: MeetingIn):
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO meetings (company_id, contact_id, deal_id, title, scheduled_at, duration_min, location, meeting_type, status, agenda, minutes, attendees, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (body.company_id, body.contact_id, body.deal_id, body.title, body.scheduled_at,
             body.duration_min, body.location, body.meeting_type, body.status, body.agenda, body.minutes, body.attendees, now_iso()),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/meetings/{meeting_id}")
def update_meeting(meeting_id: int, body: MeetingIn):
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE meetings SET company_id=?, contact_id=?, deal_id=?, title=?, scheduled_at=?, duration_min=?, location=?, meeting_type=?, status=?, agenda=?, minutes=?, attendees=? WHERE id=?",
            (body.company_id, body.contact_id, body.deal_id, body.title, body.scheduled_at,
             body.duration_min, body.location, body.meeting_type, body.status, body.agenda, body.minutes, body.attendees, meeting_id),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/meetings/{meeting_id}")
def delete_meeting(meeting_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM meetings WHERE id=?", (meeting_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ============================================================
#  AI議事録（音声→文字起こし→議事録/要約/次アクション/話者分離）
#  meetings テーブルを共有し、商談・顧客・タスクと連携する。
# ============================================================
ALLOWED_AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".webm", ".mp4", ".mpga", ".ogg", ".oga", ".flac", ".opus"}
_AI_JSON_FIELDS = ("utterances", "speaker_map", "decisions", "next_actions", "tags")


def _minutes_dict(row):
    """meetings 行を dict 化し、JSON文字列のAI列をパースして返す。"""
    d = dict(row)
    for f in _AI_JSON_FIELDS:
        v = d.get(f)
        if v:
            try:
                d[f] = json.loads(v)
            except Exception:
                d[f] = None
    return d


@app.get("/api/ai/health")
def ai_health():
    return {
        "demo_mode": ai_settings.DEMO_MODE,
        "anthropic_configured": ai_settings.has_anthropic,
        "openai_configured": ai_settings.has_openai,
        "assemblyai_configured": ai_settings.has_assemblyai,
        "local_whisper": ai_settings.LOCAL_WHISPER,
        "can_generate": ai_settings.DEMO_MODE or ai_settings.has_anthropic,
        "claude_model": ai_settings.CLAUDE_MODEL,
    }


@app.delete("/api/minutes/{meeting_id}")
def delete_minutes(meeting_id: int):
    """議事録(meetings行)と、ひもづくアップロード音声ファイルを削除する。
    /api/meetings/{id} と異なり、残骸となる音声ファイルもディスクから消す。"""
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT audio_filename FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        conn.execute("DELETE FROM meetings WHERE id=?", (meeting_id,))
        conn.commit()
    finally:
        conn.close()
    # 音声ファイルの後始末(残骸防止)。失敗してもDB削除は成立しているので握りつぶす。
    if row and row["audio_filename"]:
        try:
            (ai_settings.UPLOAD_DIR / row["audio_filename"]).unlink(missing_ok=True)
        except Exception:
            pass
    return {"ok": True}


@app.get("/api/minutes")
def list_minutes():
    """AI議事録に関係する面談(音声/文字起こし/議事録のいずれかを持つ)を一覧。"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT m.id, m.title, m.scheduled_at, m.created_at, m.ai_status, m.summary, m.tags, "
            "m.company_id, m.deal_id, co.name AS company_name, d.title AS deal_title "
            "FROM meetings m "
            "LEFT JOIN companies co ON m.company_id=co.id "
            "LEFT JOIN deals d ON m.deal_id=d.id "
            "WHERE m.audio_filename IS NOT NULL OR m.transcript IS NOT NULL OR m.ai_status IS NOT NULL "
            "ORDER BY m.created_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("tags"):
                try:
                    d["tags"] = json.loads(d["tags"])
                except Exception:
                    d["tags"] = None
            out.append(d)
        return out
    finally:
        conn.close()


@app.get("/api/minutes/{meeting_id}")
def get_minutes(meeting_id: int):
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT m.*, co.name AS company_name, d.title AS deal_title "
            "FROM meetings m LEFT JOIN companies co ON m.company_id=co.id "
            "LEFT JOIN deals d ON m.deal_id=d.id WHERE m.id=?", (meeting_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "記録が見つかりません")
        return _minutes_dict(row)
    finally:
        conn.close()


@app.post("/api/minutes/upload")
async def minutes_upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    diarize: bool = Form(False),
    auto_generate: bool = Form(True),
    company_id: Optional[int] = Form(None),
    deal_id: Optional[int] = Form(None),
    contact_id: Optional[int] = Form(None),
):
    """音声をアップロードして非同期で文字起こし→議事録生成。meetings 行を作成して返す。"""
    ext = "." + (file.filename or "audio.webm").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_AUDIO_EXT:
        raise HTTPException(400, f"対応していない音声形式です: {ext}")

    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = ai_settings.UPLOAD_DIR / saved_name
    max_bytes = ai_settings.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    with open(saved_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                out.close()
                saved_path.unlink(missing_ok=True)
                raise HTTPException(413, f"ファイルが大きすぎます(上限 {ai_settings.MAX_UPLOAD_MB}MB)")
            out.write(chunk)
    if size == 0:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(400, "空のファイルです")

    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO meetings (company_id, contact_id, deal_id, title, status, meeting_type, "
            "audio_filename, diarize, auto_generate, ai_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (company_id, contact_id, deal_id, title, "実施済", "オンライン",
             saved_name, 1 if diarize else 0, 1 if auto_generate else 0, "queued", now_iso()),
        )
        conn.commit()
        mid = cur.lastrowid
    finally:
        conn.close()

    # 常駐ワーカー(jobs_sql)が queued を拾って処理する
    return {"id": mid, "ai_status": "queued"}


class MinutesTextIn(BaseModel):
    title: str
    transcript: str
    company_id: Optional[int] = None
    deal_id: Optional[int] = None
    contact_id: Optional[int] = None


@app.post("/api/minutes/text")
def minutes_from_text(body: MinutesTextIn):
    """貼り付けたテキストから記録を作成(議事録生成は /generate で)。"""
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO meetings (company_id, contact_id, deal_id, title, status, meeting_type, "
            "transcript, ai_status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (body.company_id, body.contact_id, body.deal_id, body.title, "実施済", "オンライン",
             body.transcript, "transcribed", now_iso()),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.post("/api/minutes/{meeting_id}/generate")
def minutes_generate(meeting_id: int):
    """文字起こしから議事録一式を生成する(同期)。"""
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記録が見つかりません")
        if not row["transcript"]:
            raise HTTPException(400, "文字起こしがありません")
        try:
            ai = ai_generate_minutes(transcript=row["transcript"], title=row["title"] or "", participants="")
        except AIError as e:
            raise HTTPException(502, f"議事録生成に失敗: {e}")
        fields = dict(
            summary=ai["summary"], minutes_md=ai["minutes_md"],
            decisions=json.dumps(ai["decisions"], ensure_ascii=False),
            next_actions=json.dumps(ai["next_actions"], ensure_ascii=False),
            tags=json.dumps(ai["tags"], ensure_ascii=False),
            ai_status="summarized",
        )
        if not row["dialogue_md"] and ai.get("dialogue_md"):
            fields["dialogue_md"] = ai["dialogue_md"]
        cols = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE meetings SET {cols} WHERE id=?", (*fields.values(), meeting_id))
        conn.commit()
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        return _minutes_dict(row)
    finally:
        conn.close()


class SpeakerMapIn(BaseModel):
    speaker_map: dict


@app.patch("/api/minutes/{meeting_id}/speakers")
def minutes_speakers(meeting_id: int, body: SpeakerMapIn):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記録が見つかりません")
        if not row["utterances"]:
            raise HTTPException(400, "話者分離データがありません")
        utt = json.loads(row["utterances"])
        md, plain = format_dialogue(utt, body.speaker_map)
        conn.execute(
            "UPDATE meetings SET speaker_map=?, dialogue_md=?, transcript=? WHERE id=?",
            (json.dumps(body.speaker_map, ensure_ascii=False), md, plain, meeting_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        return _minutes_dict(row)
    finally:
        conn.close()


@app.post("/api/minutes/{meeting_id}/reprocess")
def minutes_reprocess(meeting_id: int, background: BackgroundTasks):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記録が見つかりません")
        if not row["audio_filename"]:
            raise HTTPException(400, "音声がない記録は再処理できません")
        if not (ai_settings.UPLOAD_DIR / row["audio_filename"]).exists():
            raise HTTPException(400, "音声ファイルが見つかりません")
        conn.execute("UPDATE meetings SET ai_status='queued', auto_generate=1, error_message=NULL WHERE id=?", (meeting_id,))
        conn.commit()
    finally:
        conn.close()
    # 常駐ワーカー(jobs_sql)が queued を拾って処理する
    return {"id": meeting_id, "ai_status": "queued"}


@app.get("/api/minutes/{meeting_id}/export.md", response_class=PlainTextResponse)
def minutes_export_md(meeting_id: int):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記録が見つかりません")
        d = _minutes_dict(row)
        lines = [f"# {d.get('title') or '議事録'}", ""]
        if d.get("summary"):
            lines += ["## 要約", "", d["summary"], ""]
        if d.get("decisions"):
            lines += ["## 決定事項", ""] + [f"- {x}" for x in d["decisions"]] + [""]
        if d.get("next_actions"):
            lines += ["## 次のアクション", ""]
            for a in d["next_actions"]:
                if isinstance(a, dict):
                    o = f" @{a['owner']}" if a.get("owner") else ""
                    due = f"(期限: {a['due']})" if a.get("due") else ""
                    lines.append(f"- [ ] {a.get('task','')}{o}{due}")
                else:
                    lines.append(f"- [ ] {a}")
            lines.append("")
        if d.get("minutes_md"):
            lines += ["## 議事録", "", d["minutes_md"], ""]
        if d.get("dialogue_md"):
            lines += ["## 発言録", "", d["dialogue_md"], ""]
        return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="minutes_{meeting_id}.md"'})
    finally:
        conn.close()


@app.post("/api/minutes/{meeting_id}/actions_to_tasks")
def minutes_actions_to_tasks(meeting_id: int):
    """議事録の次アクションを Sales Hub のタスクに登録(機能間連携)。"""
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記録が見つかりません")
        actions = json.loads(row["next_actions"]) if row["next_actions"] else []
        if not actions:
            raise HTTPException(400, "登録できる次アクションがありません")
        created = 0
        for a in actions:
            task = a.get("task") if isinstance(a, dict) else str(a)
            due = a.get("due") if isinstance(a, dict) else None
            if not task:
                continue
            # 期限が「来週中」等の自然文の場合は due_date を空にする(YYYY-MM-DD以外)
            due_date = due if (due and len(due) == 10 and due[4] == "-") else None
            conn.execute(
                "INSERT INTO tasks (title, source_text, due_date, priority, status, company_id, deal_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (task, f"議事録「{row['title']}」より", due_date, "中", "未着手",
                 row["company_id"], row["deal_id"], now_iso()),
            )
            created += 1
        conn.commit()
        return {"created": created}
    finally:
        conn.close()


class MinutesLinkIn(BaseModel):
    company_id: Optional[int] = None
    deal_id: Optional[int] = None


@app.patch("/api/minutes/{meeting_id}/link")
def minutes_link(meeting_id: int, body: MinutesLinkIn):
    """議事録を顧客/商談にひも付け(変更)。"""
    conn = db.get_conn()
    try:
        if not conn.execute("SELECT 1 FROM meetings WHERE id=?", (meeting_id,)).fetchone():
            raise HTTPException(404, "記録が見つかりません")
        conn.execute("UPDATE meetings SET company_id=?, deal_id=? WHERE id=?",
                     (body.company_id, body.deal_id, meeting_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


class ActionIndexIn(BaseModel):
    index: int


@app.post("/api/minutes/{meeting_id}/action_to_task")
def minutes_action_to_task(meeting_id: int, body: ActionIndexIn):
    """次アクションを1件だけタスク化(ワンクリックTo-Do)。"""
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記録が見つかりません")
        actions = json.loads(row["next_actions"]) if row["next_actions"] else []
        if body.index < 0 or body.index >= len(actions):
            raise HTTPException(400, "アクションが見つかりません")
        a = actions[body.index]
        task = a.get("task") if isinstance(a, dict) else str(a)
        due = a.get("due") if isinstance(a, dict) else None
        if not task:
            raise HTTPException(400, "空のアクションです")
        due_date = due if (due and len(due) == 10 and due[4] == "-") else None
        conn.execute(
            "INSERT INTO tasks (title, source_text, due_date, priority, status, company_id, deal_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (task, f"議事録「{row['title']}」より", due_date, "中", "未着手",
             row["company_id"], row["deal_id"], now_iso()),
        )
        conn.commit()
        return {"ok": True, "task": task}
    finally:
        conn.close()


# ============================================================
#  ヒアリングシート（音声入力対応）
# ============================================================
@app.post("/api/hearings/parse_voice")
def hearings_parse_voice(body: VoiceParseIn):
    """音声で話した生テキストを各項目へ自動振り分け。"""
    return {"fields": parse_hearing(body.text)}


@app.get("/api/hearings")
def list_hearings():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT h.*, co.name AS company_name FROM hearing_sheets h "
            "LEFT JOIN companies co ON h.company_id=co.id ORDER BY h.created_at DESC"
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.get("/api/hearings/{hearing_id}")
def get_hearing(hearing_id: int):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM hearing_sheets WHERE id=?", (hearing_id,)).fetchone()
        if not row:
            raise HTTPException(404, "人生相談カルテが見つかりません")
        return dict(row)
    finally:
        conn.close()


@app.post("/api/hearings/{hearing_id}/talk_points")
def hearing_talk_points(hearing_id: int):
    """人生相談カルテから AI が提案トーク(切り口)を生成する。"""
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM hearing_sheets WHERE id=?", (hearing_id,)).fetchone()
        if not row:
            raise HTTPException(404, "人生相談カルテが見つかりません")
        try:
            md = ai_talk_points(dict(row))
        except AIError as e:
            raise HTTPException(502, f"提案トーク生成に失敗: {e}")
        conn.execute("UPDATE hearing_sheets SET talk_points=? WHERE id=?", (md, hearing_id))
        conn.commit()
        return {"talk_points": md}
    finally:
        conn.close()


@app.post("/api/hearings")
def create_hearing(body: HearingIn):
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO hearing_sheets (company_id, contact_id, deal_id, title, current_situation, challenges, needs, budget, authority, timeline, competitors, next_action, raw_voice_text, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (body.company_id, body.contact_id, body.deal_id, body.title, body.current_situation,
             body.challenges, body.needs, body.budget, body.authority, body.timeline,
             body.competitors, body.next_action, body.raw_voice_text, now_iso()),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/hearings/{hearing_id}")
def update_hearing(hearing_id: int, body: HearingIn):
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE hearing_sheets SET company_id=?, contact_id=?, deal_id=?, title=?, current_situation=?, challenges=?, needs=?, budget=?, authority=?, timeline=?, competitors=?, next_action=?, raw_voice_text=? WHERE id=?",
            (body.company_id, body.contact_id, body.deal_id, body.title, body.current_situation,
             body.challenges, body.needs, body.budget, body.authority, body.timeline,
             body.competitors, body.next_action, body.raw_voice_text, hearing_id),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/hearings/{hearing_id}")
def delete_hearing(hearing_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM hearing_sheets WHERE id=?", (hearing_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ============================================================
#  営業育成システム
# ============================================================
@app.get("/api/training/modules")
def list_modules():
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT * FROM training_modules ORDER BY sort_order, id").fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.get("/api/training/progress")
def list_progress(member: Optional[str] = None):
    conn = db.get_conn()
    try:
        if member:
            rows = conn.execute("SELECT * FROM training_progress WHERE member=?", (member,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM training_progress").fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.post("/api/training/progress")
def upsert_progress(body: ProgressIn):
    """メンバー×モジュールの進捗を登録/更新（1組につき1行）。"""
    conn = db.get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM training_progress WHERE module_id=? AND member=?",
            (body.module_id, body.member)).fetchone()
        ts = now_iso()
        if existing:
            conn.execute(
                "UPDATE training_progress SET status=?, score=?, memo=?, updated_at=? WHERE id=?",
                (body.status, body.score, body.memo, ts, existing["id"]))
        else:
            conn.execute(
                "INSERT INTO training_progress (module_id, member, status, score, memo, updated_at) VALUES (?,?,?,?,?,?)",
                (body.module_id, body.member, body.status, body.score, body.memo, ts))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ============================================================
#  ①幸せ意識度チェック（飛込・1回目アンケート）
# ============================================================
class HappinessIn(BaseModel):
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    deal_id: Optional[int] = None
    title: str
    answers: dict = {}        # {q1:'yes'|'no'|'', ...}
    memo: Optional[str] = None


def _no_count(answers: dict) -> int:
    return sum(1 for v in (answers or {}).values() if v == "no")


@app.get("/api/happiness")
def list_happiness():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT h.*, co.name AS company_name FROM happiness_checks h "
            "LEFT JOIN companies co ON h.company_id=co.id ORDER BY h.created_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["answers"] = json.loads(d["answers"]) if d["answers"] else {}
            except Exception:
                d["answers"] = {}
            out.append(d)
        return out
    finally:
        conn.close()


@app.get("/api/happiness/{check_id}")
def get_happiness(check_id: int):
    conn = db.get_conn()
    try:
        r = conn.execute(
            "SELECT h.*, co.name AS company_name FROM happiness_checks h "
            "LEFT JOIN companies co ON h.company_id=co.id WHERE h.id=?", (check_id,)).fetchone()
        if not r:
            raise HTTPException(404, "見つかりません")
        d = dict(r)
        d["answers"] = json.loads(d["answers"]) if d["answers"] else {}
        return d
    finally:
        conn.close()


@app.post("/api/happiness")
def create_happiness(body: HappinessIn):
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO happiness_checks (company_id, contact_id, deal_id, title, answers, no_count, memo, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (body.company_id, body.contact_id, body.deal_id, body.title,
             json.dumps(body.answers, ensure_ascii=False), _no_count(body.answers), body.memo, now_iso()),
        )
        conn.commit()
        return {"id": cur.lastrowid, "no_count": _no_count(body.answers)}
    finally:
        conn.close()


@app.put("/api/happiness/{check_id}")
def update_happiness(check_id: int, body: HappinessIn):
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE happiness_checks SET company_id=?, contact_id=?, deal_id=?, title=?, answers=?, no_count=?, memo=? WHERE id=?",
            (body.company_id, body.contact_id, body.deal_id, body.title,
             json.dumps(body.answers, ensure_ascii=False), _no_count(body.answers), body.memo, check_id),
        )
        conn.commit()
        return {"ok": True, "no_count": _no_count(body.answers)}
    finally:
        conn.close()


@app.delete("/api/happiness/{check_id}")
def delete_happiness(check_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM happiness_checks WHERE id=?", (check_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ============================================================
#  ②ライフメイクカルテ（2回目アンケート・全項目JSON）
# ============================================================
class KarteIn(BaseModel):
    company_id: Optional[int] = None
    contact_id: Optional[int] = None
    deal_id: Optional[int] = None
    title: str
    data: dict = {}


@app.get("/api/kartes")
def list_kartes():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT k.id, k.title, k.company_id, k.deal_id, k.created_at, co.name AS company_name "
            "FROM lifemake_kartes k LEFT JOIN companies co ON k.company_id=co.id ORDER BY k.created_at DESC"
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


@app.get("/api/kartes/{karte_id}")
def get_karte(karte_id: int):
    conn = db.get_conn()
    try:
        r = conn.execute(
            "SELECT k.*, co.name AS company_name FROM lifemake_kartes k "
            "LEFT JOIN companies co ON k.company_id=co.id WHERE k.id=?", (karte_id,)).fetchone()
        if not r:
            raise HTTPException(404, "見つかりません")
        d = dict(r)
        try:
            d["data"] = json.loads(d["data"]) if d["data"] else {}
        except Exception:
            d["data"] = {}
        return d
    finally:
        conn.close()


@app.post("/api/kartes")
def create_karte(body: KarteIn):
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO lifemake_kartes (company_id, contact_id, deal_id, title, data, created_at) VALUES (?,?,?,?,?,?)",
            (body.company_id, body.contact_id, body.deal_id, body.title,
             json.dumps(body.data, ensure_ascii=False), now_iso()),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/kartes/{karte_id}")
def update_karte(karte_id: int, body: KarteIn):
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE lifemake_kartes SET company_id=?, contact_id=?, deal_id=?, title=?, data=? WHERE id=?",
            (body.company_id, body.contact_id, body.deal_id, body.title,
             json.dumps(body.data, ensure_ascii=False), karte_id),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/kartes/{karte_id}")
def delete_karte(karte_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM lifemake_kartes WHERE id=?", (karte_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ============================================================
#  アオ先生（lmp.html 埋め込み用・公開チャット窓口）
#  注意: /api/ 配下ではないため _auth_gate の保護対象外＝ログイン不要で公開。
#        濫用対策として ai_services/aisensei.py 側でレート制限・入力上限を実施。
# ============================================================
# アオを埋め込む静的サイト(lmp.html)のオリジン。ここからのクロスオリジン呼び出しのみ許可。
_AISENSEI_ALLOWED_ORIGINS = {
    "https://lifemakepartners.net",
    "https://www.lifemakepartners.net",
}


def _aisensei_json(request: Request, payload: dict, status: int = 200) -> JSONResponse:
    """/aisensei 専用の応答。許可オリジンにだけ CORS ヘッダを付ける（他機能には影響しない）。"""
    resp = JSONResponse(payload, status_code=status)
    origin = request.headers.get("origin", "")
    if origin in _AISENSEI_ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    return resp


@app.get("/aisensei")
def aisensei_page():
    """アオの動作を単体で確認できるテスト用チャット画面。"""
    return FileResponse(os.path.join(STATIC_DIR, "aisensei.html"))


@app.get("/aisensei/chat")
def aisensei_chat(request: Request, q: str = "", h: str = ""):
    """アオ回答API。lmp.html の __aoAsk が期待する GET 契約に合わせる。
       クエリ: q=質問, h=履歴JSON([{role,content}]) / 返り値: {ok, reply}。
       失敗時は ok:false を返し、フロントは自動でローカルKBへフォールバックする。"""
    from ai_services import aisensei
    # リバースプロキシ(nginx等)経由の場合は X-Forwarded-For に実IPが入る
    ip = ((request.headers.get("x-forwarded-for", "").split(",")[0].strip())
          or (request.client.host if request.client else "unknown"))
    if not aisensei.check_rate_limit(ip):
        return _aisensei_json(request, {"ok": False, "error": "rate_limited"}, 429)
    history: List[dict] = []
    if h:
        try:
            parsed = json.loads(h)
            if isinstance(parsed, list):
                history = parsed
        except Exception:
            history = []
    try:
        answer = aisensei.reply(q, history)
    except aisensei.AISenseiError as e:
        # キー未設定・空入力などは 200 + ok:false で穏当に返す（フロントはKBへ）
        return _aisensei_json(request, {"ok": False, "error": str(e)}, 200)
    return _aisensei_json(request, {"ok": True, "reply": answer}, 200)


# ============================================================
#  静的ファイル（フロントエンド）
# ============================================================
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8123, reload=False)
