"""Claude による議事録生成・要約・次アクション抽出。"""
import json
import re
from datetime import date
from typing import Any, Dict, List

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


TALK_SYSTEM = """あなたは不動産のトップクローザー育成のプロです。
ライフメイクパートナーズの『人生伴走型』営業方針(押さない・急がせない・潜在客に根拠を伝える)に沿って、
お客様の人生相談カルテ(家計・住環境・万が一・老後・災害・病気 などの現状)をもとに、
クローザーがそのまま使える"提案の切り口・トーク"を作ります。事実に反する断定や煽りは避けること。
"""

TALK_TEMPLATE = """以下はお客様の人生相談カルテです。これをもとに、提案トークを作ってください。

# カルテ
- お客様/件名: {title}
- 家計の現状: {current_situation}
- 住環境の現状・希望: {challenges}
- 万が一への備え: {needs}
- 老後への備え: {budget}
- 災害への備え: {authority}
- 健康・病気への備え: {timeline}
- お客様の想い・背景: {competitors}

出力は次の見出しのMarkdownで(余計な前置きなし):

## このお客様の状況整理(一言で)
## 刺さりやすい切り口(3つ)
（カルテの具体的な数字・事実を引用しながら）

## 4章プレゼンの組み立て方
- ①家は買うべき: …
- ②今買うべき: …
- ③ここを買うべき: …
- ④うちから買うべき: …

## 次の一手(おすすめアクション)
"""


def generate_talk_points(hearing: Dict[str, Any]) -> str:
    """人生相談カルテ(dict)から提案トーク(Markdown)を生成して返す。"""
    if settings.DEMO_MODE:
        return ("## このお客様の状況整理\n【デモ】サンプルの提案トークです。本番はClaudeで生成されます。\n\n"
                "## 刺さりやすい切り口(3つ)\n- 例: 家賃と返済額の比較で『住居費設計』に視点を移す\n")
    if not settings.has_anthropic:
        raise AIError("ANTHROPIC_API_KEY が未設定です。")
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise AIError("anthropic 未インストール") from e

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    g = lambda k: (hearing.get(k) or "（未記入）")
    message = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=2048,
        system=TALK_SYSTEM,
        messages=[{"role": "user", "content": TALK_TEMPLATE.format(
            title=g("title"), current_situation=g("current_situation"), challenges=g("challenges"),
            needs=g("needs"), budget=g("budget"), authority=g("authority"),
            timeline=g("timeline"), competitors=g("competitors"),
        )}],
    )
    return "".join(b.text for b in message.content if b.type == "text").strip()


# ============================================================
#  タスク抽出（AI版） — task_extractor のルールベースの高精度代替
# ============================================================
def _extract_json_array(text: str) -> List[Any]:
    """モデル出力から JSON 配列を取り出してパースする。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise AIError(f"AI 応答から配列を抽出できませんでした: {text[:200]}")
    return json.loads(text[start : end + 1])


TASK_EXTRACT_SYSTEM = """あなたは営業メモ・議事録から「実際にやるべきタスク」を抽出する専門家です。
行動が必要なタスクのみを抽出し、単なる事実・感想・背景説明は除外してください。"""

TASK_EXTRACT_TEMPLATE = """今日の日付は {today} です。
以下のメモ/議事録から、営業担当が行うべきタスク（ToDo）を抽出してください。
「来週」「明日」「月末まで」などの相対的な期限は {today} を基準に YYYY-MM-DD へ変換してください。
緊急・重要なものは優先度を高くしてください。

# メモ
\"\"\"
{text}
\"\"\"

出力は次のJSON配列**のみ**（前後に説明文やコードフェンスを付けない）:
[
  {{"title": "タスク名（簡潔・命令形）", "due_date": "YYYY-MM-DD（不明なら空文字）", "priority": "高|中|低"}}
]
タスクが見つからなければ [] を返してください。"""


def extract_tasks_ai(text: str) -> List[Dict[str, Any]]:
    """メモ/議事録からタスク候補を Claude で抽出。task_extractor と同じ形式の list を返す。"""
    if not text or not text.strip():
        return []
    if not settings.has_anthropic:
        raise AIError("ANTHROPIC_API_KEY が未設定です。")
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise AIError("anthropic パッケージが未インストールです。") from e

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=2048,
        system=TASK_EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": TASK_EXTRACT_TEMPLATE.format(
            today=date.today().isoformat(), text=text[:20_000])}],
    )
    raw = "".join(b.text for b in message.content if b.type == "text")
    data = _extract_json_array(raw)

    out: List[Dict[str, Any]] = []
    for d in data:
        if not isinstance(d, dict):
            continue
        title = (d.get("title") or "").strip()
        if not title:
            continue
        due = (d.get("due_date") or "").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
            due = None
        pri = d.get("priority") if d.get("priority") in ("高", "中", "低") else "中"
        out.append({"title": title[:120], "due_date": due, "priority": pri, "source_text": text[:300]})
    return out


# ============================================================
#  人生相談カルテ 振り分け（AI版） — hearing_parser のルールベース代替
# ============================================================
HEARING_KEYS = ("current_situation", "challenges", "needs", "budget",
                "authority", "timeline", "competitors", "next_action")

HEARING_CLASSIFY_SYSTEM = """あなたは住宅営業の『人生相談カルテ』作成アシスタントです。
お客様との会話テキストを、カルテの各項目に振り分けます。事実に忠実に、推測で内容を付け足さないこと。"""

HEARING_CLASSIFY_TEMPLATE = """以下の会話テキストを読み、人生相談カルテの各項目へ内容を振り分けてください。
各項目には該当する発言を、要約しすぎず元の表現を活かしてまとめます。該当が無い項目は空文字にしてください。

# 各項目の意味
- current_situation: 家計の現状（収入・支出・家賃・貯蓄・ローン等）
- challenges: 住環境の現状・希望（賃貸/持ち家・間取り・立地・引越等）
- needs: 万が一への備え（保険・保障）
- budget: 老後への備え（年金・老後資金）
- authority: 災害への備え（地震・水害・防災）
- timeline: 健康・病気への備え（持病・医療・介護）
- competitors: お客様の想い・家族・将来の希望・価値観
- next_action: 次回までの宿題・約束・次の一手

# 会話
\"\"\"
{text}
\"\"\"

出力は次のJSONオブジェクト**のみ**（前後に説明文やコードフェンスを付けない）:
{{"current_situation":"","challenges":"","needs":"","budget":"","authority":"","timeline":"","competitors":"","next_action":""}}
"""


def classify_hearing_ai(text: str) -> Dict[str, str]:
    """会話テキストを人生相談カルテの各項目へ Claude で振り分け。空でない項目のみの dict を返す。"""
    if not text or not text.strip():
        return {}
    if not settings.has_anthropic:
        raise AIError("ANTHROPIC_API_KEY が未設定です。")
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise AIError("anthropic パッケージが未インストールです。") from e

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=2048,
        system=HEARING_CLASSIFY_SYSTEM,
        messages=[{"role": "user", "content": HEARING_CLASSIFY_TEMPLATE.format(text=text[:20_000])}],
    )
    raw = "".join(b.text for b in message.content if b.type == "text")
    data = _extract_json(raw)
    return {k: data[k].strip() for k in HEARING_KEYS
            if isinstance(data.get(k), str) and data.get(k).strip()}
