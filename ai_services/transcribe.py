"""音声 → テキスト 文字起こし。

OpenAI Whisper API を使用。将来別エンジン(ローカル Whisper 等)に差し替え
られるよう、transcribe_file() という単一の関数インターフェイスに集約している。
"""
from pathlib import Path

from .config import settings


class TranscribeError(Exception):
    pass


def transcribe_file(audio_path: Path, language: str = "ja") -> str:
    """音声ファイルを文字起こしして全文テキストを返す。"""
    if settings.DEMO_MODE:
        from . import demo_data
        return demo_data.DEMO_TRANSCRIPT
    if not settings.has_openai:
        raise TranscribeError(
            "OPENAI_API_KEY が未設定です。.env に設定してください。"
        )

    try:
        from openai import OpenAI
    except ImportError as e:
        raise TranscribeError("openai パッケージが未インストールです。") from e

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=settings.WHISPER_MODEL,
            file=f,
            language=language,
            response_format="text",
        )

    # response_format="text" の場合は文字列が返る
    text = result if isinstance(result, str) else getattr(result, "text", str(result))
    return text.strip()
