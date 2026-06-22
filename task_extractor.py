"""
タスク抽出ロジック
- 商談メモ・面談議事録などの自由文から「やること(タスク)」を抽出する。
- 現状は外部APIに依存しないルールベース（オフラインで確実に動く）。
- 将来 Claude API に差し替えられるよう extract_tasks() のインターフェースを固定。
"""
import re
from datetime import datetime, timedelta

# 行動を示す動詞・語尾（これらを含む文をタスク候補とみなす）
ACTION_KEYWORDS = [
    "送る", "送付", "送信", "提出", "作成", "用意", "準備", "確認", "連絡",
    "電話", "メール", "アポ", "訪問", "見積", "提案", "回答", "返信", "共有",
    "調整", "手配", "申請", "登録", "予約", "報告", "フォロー", "対応",
    "TODO", "ToDo", "todo", "やる", "実施", "依頼", "問い合わせ", "相談",
]

# 「〜まで」「次回」など期限を示唆する語
DUE_HINTS = ["まで", "までに", "次回", "来週", "明日", "今週", "月末", "本日中", "今日中"]

# 優先度を上げるキーワード
HIGH_PRIORITY = ["至急", "急ぎ", "すぐ", "本日中", "今日中", "重要", "必ず"]

# 相対日付の語 → 日数
RELATIVE_DATES = {
    "本日": 0, "今日": 0, "本日中": 0, "今日中": 0,
    "明日": 1, "あした": 1,
    "明後日": 2,
    "今週": 4, "今週中": 4,
    "来週": 7,
    "月末": None,  # 月末は別計算
}


def _guess_due_date(text: str):
    """文中の相対表現から期限(ISO日付)を推定する。見つからなければ None。"""
    today = datetime.now().date()

    # 明示的な日付 (M/D, M月D日)
    m = re.search(r"(\d{1,2})[/／月](\d{1,2})", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = today.year
        try:
            cand = datetime(year, month, day).date()
            if cand < today:  # 過去日なら翌年とみなす
                cand = datetime(year + 1, month, day).date()
            return cand.isoformat()
        except ValueError:
            pass

    # 月末
    if "月末" in text:
        if today.month == 12:
            return datetime(today.year, 12, 31).date().isoformat()
        first_next = datetime(today.year, today.month + 1, 1).date()
        return (first_next - timedelta(days=1)).isoformat()

    # 相対語
    for word, days in RELATIVE_DATES.items():
        if days is not None and word in text:
            return (today + timedelta(days=days)).isoformat()

    return None


def _guess_priority(text: str):
    for kw in HIGH_PRIORITY:
        if kw in text:
            return "高"
    return "中"


def _clean(line: str):
    """箇条書き記号や番号を除去して読みやすいタスク名に整える。"""
    line = line.strip()
    line = re.sub(r"^[\-・*●○◦▪️•\d\.\)\s]+", "", line)
    return line.strip()


def extract_tasks(text: str):
    """
    自由文からタスク候補のリストを返す（公開API）。
    Claude が使える設定（APIキーあり & DEMO_MODE無効）なら AI 抽出、
    未設定・デモ・失敗時はルールベースに自動フォールバックする。
    """
    try:
        from ai_services.config import settings as _s
        if _s.has_anthropic and not _s.DEMO_MODE:
            from ai_services.ai import extract_tasks_ai
            return extract_tasks_ai(text)
    except Exception:
        pass  # AI未設定/失敗時はルールベースへ
    return extract_tasks_rule(text)


def extract_tasks_rule(text: str):
    """
    ルールベースのタスク抽出（オフライン・フォールバック用）。
    返り値: [{"title", "due_date", "priority", "source_text"}, ...]
    """
    if not text or not text.strip():
        return []

    results = []
    seen = set()

    # 改行・句点で文を分割
    raw_lines = re.split(r"[\n。]", text)

    for raw in raw_lines:
        line = raw.strip()
        if len(line) < 3:
            continue

        # 行動キーワードを含むか
        if not any(kw in line for kw in ACTION_KEYWORDS):
            continue

        title = _clean(line)
        if not title or title in seen:
            continue
        seen.add(title)

        results.append({
            "title": title[:120],
            "due_date": _guess_due_date(line),
            "priority": _guess_priority(line),
            "source_text": line[:300],
        })

    return results
