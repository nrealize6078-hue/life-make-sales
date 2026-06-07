"""AI議事録の非同期処理(sales_tool の raw sqlite3 版)。

meetings テーブルの音声を文字起こし→(任意で)議事録生成し、AI列を更新する。
ai_status 遷移: queued → processing → transcribed → summarizing → summarized / error
"""
import json
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
    """起動時に呼ぶ。再起動で中断された処理中の面談を error にする。"""
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE meetings SET ai_status='error', error_message=? "
            "WHERE ai_status IN ('queued','processing','summarizing')",
            ("サーバー再起動により処理が中断されました。再処理してください。",),
        )
        conn.commit()
    finally:
        conn.close()


def process_minutes(meeting_id: int, diarize: bool, auto_generate: bool):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        if not row or not row["audio_filename"]:
            return
        _set(conn, meeting_id, ai_status="processing", error_message=None)
        audio_path = settings.UPLOAD_DIR / row["audio_filename"]

        if diarize:
            result = transcribe_with_speakers(audio_path)
            _set(conn, meeting_id,
                 transcript=result["transcript"],
                 utterances=json.dumps(result["utterances"], ensure_ascii=False),
                 dialogue_md=result["dialogue_md"] or None,
                 ai_status="transcribed")
        else:
            text = transcribe_file(audio_path)
            _set(conn, meeting_id, transcript=text, ai_status="transcribed")

        if auto_generate:
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
