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
from task_extractor import extract_tasks
from hearing_parser import parse_hearing
from ai_services.config import settings as ai_settings  # これで .env が読み込まれる
from ai_services import jobs_sql
from ai_services.diarize import format_dialogue
from ai_services.ai import generate_minutes as ai_generate_minutes, AIError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# ----- ログイン認証(APP_PASSWORD が空なら無効=従来どおり) -----
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
_COOKIE = "lms_session"


def _session_token() -> str:
    return hashlib.sha256(("lms:" + APP_PASSWORD).encode()).hexdigest()


def _is_authed(request: Request) -> bool:
    return (not APP_PASSWORD) or request.cookies.get(_COOKIE) == _session_token()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時にDB初期化（on_event は非推奨のため lifespan を使用）
    db.init_db()
    jobs_sql.recover_stuck()  # 再起動で中断したAI処理を復旧
    yield


app = FastAPI(title="ライフメイクセールス (Life Make Sales)", version="3.0.0", lifespan=lifespan)


@app.middleware("http")
async def _no_cache_static(request, call_next):
    """静的ファイル更新後に古いJS/CSSが残らないよう、再検証を強制する。"""
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.startswith("/static"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    """APP_PASSWORD 設定時、業務API(/api/*)を保護する。認証/ヘルスは除外。"""
    p = request.url.path
    if APP_PASSWORD and p.startswith("/api/") and not p.startswith("/api/auth/") and p != "/api/ai/health":
        if not _is_authed(request):
            return JSONResponse({"detail": "ログインが必要です"}, status_code=401)
    return await call_next(request)


class LoginIn(BaseModel):
    password: str


@app.get("/api/auth/me")
def auth_me(request: Request):
    return {"auth_enabled": bool(APP_PASSWORD), "authenticated": _is_authed(request)}


@app.post("/api/auth/login")
def auth_login(body: LoginIn, response: Response):
    if not APP_PASSWORD:
        return {"ok": True, "note": "認証は無効です"}
    if body.password != APP_PASSWORD:
        raise HTTPException(401, "パスワードが違います")
    response.set_cookie(_COOKIE, _session_token(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return {"ok": True}


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(_COOKIE)
    return {"ok": True}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


# ============================================================
#  Pydantic モデル（リクエストボディ）
# ============================================================
class CompanyIn(BaseModel):
    name: str
    industry: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None


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
    stage: str = "リード"
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
            "SELECT COUNT(*) FROM deals WHERE stage NOT IN ('受注','失注')"
        ).fetchone()[0]
        won = c.execute("SELECT COUNT(*) FROM deals WHERE stage='受注'").fetchone()[0]
        lost = c.execute("SELECT COUNT(*) FROM deals WHERE stage='失注'").fetchone()[0]
        pipeline_amount = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM deals WHERE stage NOT IN ('受注','失注')"
        ).fetchone()[0]
        won_amount = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM deals WHERE stage='受注'"
        ).fetchone()[0]
        # 加重見込み（金額 × 確度）
        weighted = c.execute(
            "SELECT COALESCE(SUM(amount * probability / 100.0),0) FROM deals WHERE stage NOT IN ('受注','失注')"
        ).fetchone()[0]
        open_tasks = c.execute("SELECT COUNT(*) FROM tasks WHERE status != '完了'").fetchone()[0]
        upcoming = c.execute("SELECT COUNT(*) FROM meetings WHERE status='予定'").fetchone()[0]

        today = date.today().isoformat()
        overdue_tasks = c.execute(
            "SELECT COUNT(*) FROM tasks WHERE status != '完了' AND due_date IS NOT NULL AND due_date < ?",
            (today,),
        ).fetchone()[0]

        win_rate = round(won / (won + lost) * 100) if (won + lost) > 0 else 0

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
            "(SELECT COUNT(*) FROM deals d WHERE d.company_id=c.id AND d.stage NOT IN ('受注','失注')) AS open_deals, "
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
        return company
    finally:
        conn.close()


@app.post("/api/companies")
def create_company(body: CompanyIn):
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO companies (name, industry, address, phone, website, notes, created_at) VALUES (?,?,?,?,?,?,?)",
            (body.name, body.industry, body.address, body.phone, body.website, body.notes, now_iso()),
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
            "UPDATE companies SET name=?, industry=?, address=?, phone=?, website=?, notes=? WHERE id=?",
            (body.name, body.industry, body.address, body.phone, body.website, body.notes, company_id),
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
        # 受注/失注に動かしたら確度も自動調整
        prob = None
        if body.stage == "受注":
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
            "INSERT INTO meetings (company_id, contact_id, deal_id, title, scheduled_at, duration_min, location, meeting_type, status, agenda, minutes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (body.company_id, body.contact_id, body.deal_id, body.title, body.scheduled_at,
             body.duration_min, body.location, body.meeting_type, body.status, body.agenda, body.minutes, now_iso()),
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
            "UPDATE meetings SET company_id=?, contact_id=?, deal_id=?, title=?, scheduled_at=?, duration_min=?, location=?, meeting_type=?, status=?, agenda=?, minutes=? WHERE id=?",
            (body.company_id, body.contact_id, body.deal_id, body.title, body.scheduled_at,
             body.duration_min, body.location, body.meeting_type, body.status, body.agenda, body.minutes, meeting_id),
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
ALLOWED_AUDIO_EXT = {".mp3", ".m4a", ".wav", ".webm", ".mp4", ".mpga", ".ogg", ".flac"}
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
        "claude_model": ai_settings.CLAUDE_MODEL,
    }


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
            "audio_filename, diarize, ai_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (company_id, contact_id, deal_id, title, "実施済", "オンライン",
             saved_name, 1 if diarize else 0, "queued", now_iso()),
        )
        conn.commit()
        mid = cur.lastrowid
    finally:
        conn.close()

    background.add_task(jobs_sql.process_minutes, mid, diarize, auto_generate)
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
        conn.execute("UPDATE meetings SET ai_status='queued', error_message=NULL WHERE id=?", (meeting_id,))
        conn.commit()
        diar = bool(row["diarize"])
    finally:
        conn.close()
    background.add_task(jobs_sql.process_minutes, meeting_id, diar, True)
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
            raise HTTPException(404, "ヒアリングシートが見つかりません")
        return dict(row)
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
#  静的ファイル（フロントエンド）
# ============================================================
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8123, reload=False)
