"""本格的な話者分離つき文字起こし(AssemblyAI)。

音声波形から話者を聞き分け、「誰がいつ何を話したか」を返す。
OpenAI Whisper(話者分離なし)に対して、こちらは speaker_labels を使う。

追加の Python 依存は不要(インストール済みの httpx を使用)。
"""
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

from .config import settings

BASE_URL = "https://api.assemblyai.com/v2"
POLL_INTERVAL_SEC = 3
MAX_WAIT_SEC = 60 * 20  # 最大20分待つ


class DiarizeError(Exception):
    pass


def _headers() -> Dict[str, str]:
    return {"authorization": settings.ASSEMBLYAI_API_KEY}


def _upload(audio_path: Path) -> str:
    """音声をアップロードして一時URLを得る。"""
    with open(audio_path, "rb") as f:
        resp = httpx.post(
            f"{BASE_URL}/upload",
            headers=_headers(),
            content=f.read(),
            timeout=httpx.Timeout(600.0),
        )
    if resp.status_code != 200:
        raise DiarizeError(f"アップロード失敗 ({resp.status_code}): {resp.text[:200]}")
    return resp.json()["upload_url"]


def _request_transcript(audio_url: str) -> str:
    body = {
        "audio_url": audio_url,
        "speaker_labels": True,           # ← 話者分離を有効化
        "language_code": settings.DIARIZE_LANGUAGE,
    }
    resp = httpx.post(f"{BASE_URL}/transcript", headers=_headers(), json=body, timeout=60)
    if resp.status_code not in (200, 201):
        raise DiarizeError(f"文字起こし要求失敗 ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["id"]


def _poll(transcript_id: str) -> Dict[str, Any]:
    waited = 0
    while waited < MAX_WAIT_SEC:
        resp = httpx.get(f"{BASE_URL}/transcript/{transcript_id}", headers=_headers(), timeout=60)
        data = resp.json()
        status = data.get("status")
        if status == "completed":
            return data
        if status == "error":
            raise DiarizeError(f"処理エラー: {data.get('error')}")
        time.sleep(POLL_INTERVAL_SEC)
        waited += POLL_INTERVAL_SEC
    raise DiarizeError("タイムアウト(処理が時間内に完了しませんでした)")


def format_dialogue(utterances: List[Dict[str, Any]], speaker_map: Dict[str, str] | None = None):
    """utterances を Markdown と プレーンテキストに整形する。

    speaker_map で話者ラベル("A")を実名("山田太郎")に置き換えられる。
    """
    speaker_map = speaker_map or {}
    md_lines, plain_lines = [], []
    for u in utterances:
        label = u.get("speaker", "?")
        name = speaker_map.get(label) or f"話者{label}"
        text = (u.get("text") or "").strip()
        md_lines.append(f"**{name}:** {text}")
        plain_lines.append(f"{name}: {text}")
    return "\n\n".join(md_lines), "\n".join(plain_lines)


def transcribe_with_speakers(audio_path: Path, speaker_map: Dict[str, str] | None = None) -> Dict[str, Any]:
    """話者分離つき文字起こし。

    戻り値:
      {
        "transcript": 話者ラベル付きプレーンテキスト,
        "dialogue_md": 話者ラベル付き Markdown,
        "raw_text": 話者なしの全文,
        "speakers": 検出された話者ラベルの一覧,
      }
    """
    if settings.DEMO_MODE:
        from . import demo_data
        utterances = [dict(u) for u in demo_data.DEMO_UTTERANCES]
        dialogue_md, plain = format_dialogue(utterances, speaker_map)
        return {
            "transcript": plain,
            "dialogue_md": dialogue_md,
            "raw_text": " ".join(u["text"] for u in utterances),
            "utterances": utterances,
            "speakers": sorted({u["speaker"] for u in utterances}),
        }

    if not settings.has_assemblyai:
        raise DiarizeError(
            "ASSEMBLYAI_API_KEY が未設定です。.env に設定してください。"
        )

    audio_url = _upload(audio_path)
    transcript_id = _request_transcript(audio_url)
    data = _poll(transcript_id)

    api_utterances = data.get("utterances") or []
    raw_text = (data.get("text") or "").strip()

    if not api_utterances:
        # 話者が分かれなかった場合は全文のみ返す
        return {
            "transcript": raw_text,
            "dialogue_md": "",
            "raw_text": raw_text,
            "utterances": [],
            "speakers": [],
        }

    # 保存用に slim 化(speaker と text のみ)
    utterances = [{"speaker": u.get("speaker", "?"), "text": (u.get("text") or "").strip()} for u in api_utterances]
    dialogue_md, plain = format_dialogue(utterances, speaker_map)
    speakers = sorted({u["speaker"] for u in utterances})
    return {
        "transcript": plain,
        "dialogue_md": dialogue_md,
        "raw_text": raw_text,
        "utterances": utterances,
        "speakers": speakers,
    }
