"""ローカルWhisper(faster-whisper)をサブプロセスで呼び出す。

sales_tool 本体は Python3.14、faster-whisper は Python3.9 の whisper_venv に
入っているため、別プロセスとして実行して結果(テキスト)を受け取る。
"""
import json
import subprocess
from pathlib import Path

from .config import settings

_ROOT = Path(__file__).resolve().parent.parent  # sales_tool/
WHISPER_PY = _ROOT / "whisper_venv" / "Scripts" / "python.exe"
WHISPER_SCRIPT = _ROOT / "whisper_local.py"


class LocalWhisperError(Exception):
    pass


def available() -> bool:
    return WHISPER_PY.exists() and WHISPER_SCRIPT.exists()


def transcribe_local(audio_path: Path) -> str:
    """ローカルWhisperで文字起こしして全文テキストを返す。"""
    if not available():
        raise LocalWhisperError("ローカルWhisper環境(whisper_venv)が見つかりません。")
    try:
        proc = subprocess.run(
            [str(WHISPER_PY), str(WHISPER_SCRIPT), str(audio_path), settings.WHISPER_LOCAL_MODEL],
            capture_output=True, timeout=3600,
        )
    except Exception as e:  # noqa: BLE001
        raise LocalWhisperError(f"実行に失敗: {e}") from e

    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "ignore")[-600:]
        raise LocalWhisperError(f"文字起こしに失敗: {msg}")

    out = proc.stdout.decode("utf-8", "ignore")
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                return (data.get("text") or "").strip()
            except Exception:
                continue
    return ""
