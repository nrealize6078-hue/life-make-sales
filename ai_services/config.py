"""AI議事録エンジンの設定。sales_tool/.env を読む。"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    _ROOT = Path(__file__).resolve().parent.parent  # sales_tool/
    load_dotenv(_ROOT / ".env")
except Exception:
    _ROOT = Path(__file__).resolve().parent.parent


class _Settings:
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ASSEMBLYAI_API_KEY: str = os.getenv("ASSEMBLYAI_API_KEY", "")

    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "whisper-1")
    DIARIZE_LANGUAGE: str = os.getenv("DIARIZE_LANGUAGE", "ja")

    DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes", "on")

    # ローカルWhisper(無料・キー不要・PCで処理)。true で文字起こしをローカル実行。
    LOCAL_WHISPER: bool = os.getenv("LOCAL_WHISPER", "false").lower() in ("1", "true", "yes", "on")
    WHISPER_LOCAL_MODEL: str = os.getenv("WHISPER_LOCAL_MODEL", "small")  # tiny/base/small/medium

    UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", str(_ROOT / "data" / "uploads")))
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "500"))

    @property
    def has_anthropic(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY)

    @property
    def has_openai(self) -> bool:
        return bool(self.OPENAI_API_KEY)

    @property
    def has_assemblyai(self) -> bool:
        return bool(self.ASSEMBLYAI_API_KEY)


settings = _Settings()
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
