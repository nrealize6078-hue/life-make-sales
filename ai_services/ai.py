"""Claude による議事録生成・要約・次アクション抽出。"""
import json
from typing import Any, Dict

from .config import settings


class AIError(Exception):
    pass


SYSTEM_PROMPT = """あなたは一流の議事録作成アシスタントです。
面談・会議の文字起こしテキストを受け取り、構造化された議事録を日本語で作成します。
事実に忠実に、推測で内容を付け足さないこと。発言が曖昧な箇所は無理に断定しないこと。
"""

USER_TEMPLATE = """以下は面談/会議の文字起こしです。これをもとに議事録を作成してください。

# メタ情報
- タイトル: {title}
- 参加者: {participants}

# 文字起こし
\"\"\"
{transcript}
\"\"\"

必ず次の JSON 形式**のみ**で出力してください(前後に説明文やコードフェンスを付けない)。

{{
  "summary": "全体を3〜5文で要約した文章",
  "dialogue_md": "話者を推定して整理した対話のMarkdown。各発言を `**話者名:** 発言内容` の形式で改行区切り。参加者リストから名前を推定し、不明な話者は 話者A/話者B とする。文字起こしに明確な発言者情報がなければ無理に分けず空文字でよい",
  "minutes_md": "議事録本文(Markdown形式)。## 背景 / ## 議論内容 / ## 決定事項 / ## 次のアクション などの見出しで整理",
  "decisions": ["決定事項を箇条書きで", "..."],
  "next_actions": [
    {{"task": "やること", "owner": "担当者(不明なら空文字)", "due": "期限(不明なら空文字)"}}
  ],
  "tags": ["内容を表すタグを3〜6個", "例: 採用面談, 一次面接"]
}}
"""


def _extract_json(text: str) -> Dict[str, Any]:
    """モデル出力から JSON 部分を取り出してパースする。"""
    text = text.strip()
    # コードフェンスが付いてきた場合の保険
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise AIError(f"AI 応答から JSON を抽出できませんでした: {text[:200]}")
    return json.loads(text[start : end + 1])


def generate_minutes(transcript: str, title: str = "", participants: str = "") -> Dict[str, Any]:
    """文字起こしから議事録一式(要約・議事録・決定事項・次アクション・タグ)を生成。"""
    if settings.DEMO_MODE:
        import copy
        from . import demo_data
        return copy.deepcopy(demo_data.DEMO_MINUTES)
    if not settings.has_anthropic:
        raise AIError("ANTHROPIC_API_KEY が未設定です。.env に設定してください。")
    if not transcript or not transcript.strip():
        raise AIError("文字起こしが空です。")

    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise AIError("anthropic パッケージが未インストールです。") from e

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_TEMPLATE.format(
                    title=title or "(無題)",
                    participants=participants or "(不明)",
                    transcript=transcript[:100_000],  # 安全のため上限
                ),
            }
        ],
    )

    raw = "".join(block.text for block in message.content if block.type == "text")
    data = _extract_json(raw)

    # 形を整える(欠損キーの補完)
    return {
        "summary": data.get("summary", ""),
        "dialogue_md": data.get("dialogue_md", "") or "",
        "minutes_md": data.get("minutes_md", ""),
        "decisions": data.get("decisions", []) or [],
        "next_actions": data.get("next_actions", []) or [],
        "tags": data.get("tags", []) or [],
    }
