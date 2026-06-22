"""AI議事録の非同期処理(sales_tool の raw sqlite3 版)。

DBキュー方式: meetings.ai_status='queued' を、常駐ワーカースレッドが1件ずつ拾って処理する。
Redis等の外部インフラ不要・1コンテナ完結。再起動でも中断ジョブを自動で再キューする。
ai_status 遷移: queued → processing → transcribed → summarizing → summarized / error
"""
import json
import threading
from pathlib import Path

import database as db  # sales_tool のトップレベルモジュール
from .config import settings
from .transcribe import transcribe_file
from .diarize import transcribe_with_speakers
from .ai import generate_minutes


def _set(conn, meeting_id, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE meetings SET {cols} WHERE id=?", (*fields.values(), meeting_id))
    conn.commit()


def recover_stuck():
    """起動時に呼ぶ。中断(processing/summarizing)を queued に戻して再処理させる。
    queued はそのまま(ワーカーが拾う)。音声が無いのに中断状態のものだけ error。"""
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE meetings SET ai_status='queued', error_message=NULL "
            "WHERE ai_status IN ('processing','summarizing') AND audio_filename IS NOT NULL"
        )
        conn.execute(
            "UPDATE meetings SET ai_status='error', error_message=? "
            "WHERE ai_status IN ('processing','summarizing') AND audio_filename IS NULL",
            ("サーバー再起動により中断されました。",),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  DBキュー + 常駐ワーカー
# ============================================================
_worker_stop = threading.Event()
_worker_thread = None


def claim_next():
    """queued の最古1件を processing に遷移させて掴む。無ければ None。"""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT id, diarize, auto_generate FROM meetings WHERE ai_status='queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        # 楽観ロック: まだ queued の時だけ掴む(複数ワーカー/競合対策)
        cur = conn.execute(
            "UPDATE meetings SET ai_status='processing' WHERE id=? AND ai_status='queued'", (row["id"],)
        )
        conn.commit()
        if cur.rowcount != 1:
            return None
        ag = row["auto_generate"]
        return {"id": row["id"], "diarize": bool(row["diarize"]), "auto_generate": bool(1 if ag is None else ag)}
    finally:
        conn.close()


def worker_loop(poll_sec: float = 2.0):
    """queued を順次処理する常駐ループ。1件ずつ(逐次)処理する。"""
    while not _worker_stop.is_set():
        try:
            job = claim_next()
            if job:
                process_minutes(job["id"], job["diarize"], job["auto_generate"])
                continue  # 続けて次の queued を探す
        except Exception:
            pass
        _worker_stop.wait(poll_sec)


def start_worker():
    """アプリ起動時に常駐ワーカーを開始(冪等)。"""
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return _worker_thread
    _worker_stop.clear()
    _worker_thread = threading.Thread(target=worker_loop, name="minutes-worker", daemon=True)
    _worker_thread.start()
    return _worker_thread


def stop_worker():
    _worker_stop.set()


def process_minutes(meeting_id: int, diarize: bool, auto_generate: bool):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        if not row or not row["audio_filename"]:
            return
        _set(conn, meeting_id, ai_status="processing", error_message=None)
        audio_path = settings.UPLOAD_DIR / row["audio_filename"]

        if diarize and settings.has_assemblyai:
            # 話者分離ON + AssemblyAIキーあり → 話者分離つき文字起こし
            result = transcribe_with_speakers(audio_path)
            _set(conn, meeting_id,
                 transcript=result["transcript"],
                 utterances=json.dumps(result["utterances"], ensure_ascii=False),
                 dialogue_md=result["dialogue_md"] or None,
                 ai_status="transcribed")
        elif settings.LOCAL_WHISPER:
            # ローカルWhisper(無料・キー不要)。話者分離は非対応。
            from .local_whisper import transcribe_local
            text = transcribe_local(audio_path)
            _set(conn, meeting_id, transcript=text, ai_status="transcribed")
        else:
            # OpenAI Whisper(クラウド)
            text = transcribe_file(audio_path)
            _set(conn, meeting_id, transcript=text, ai_status="transcribed")

        # 議事録生成はClaude(またはデモ)が必要。無い場合は文字起こしのみで完了。
        can_generate = settings.DEMO_MODE or settings.has_anthropic
        if auto_generate and can_generate:
            cur = conn.execute("SELECT transcript, title, dialogue_md FROM meetings WHERE id=?", (meeting_id,)).fetchone()
            if cur["transcript"]:
                _set(conn, meeting_id, ai_status="summarizing")
                ai = generate_minutes(transcript=cur["transcript"], title=cur["title"] or "", participants="")
                fields = dict(
                    summary=ai["summary"],
                    minutes_md=ai["minutes_md"],
                    decisions=json.dumps(ai["decisions"], ensure_ascii=False),
                    next_actions=json.dumps(ai["next_actions"], ensure_ascii=False),
                    tags=json.dumps(ai["tags"], ensure_ascii=False),
                    ai_status="summarized",
                )
                if not cur["dialogue_md"] and ai.get("dialogue_md"):
                    fields["dialogue_md"] = ai["dialogue_md"]
                _set(conn, meeting_id, **fields)
    except Exception as e:  # noqa: BLE001
        try:
            _set(conn, meeting_id, ai_status="error", error_message=str(e)[:1000])
        except Exception:
            pass
    finally:
        conn.close()
