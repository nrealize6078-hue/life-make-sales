"""
ヒアリング音声の自動振り分け
- 「シート全体を話した生テキスト」を、BANT＋課題などの各項目へキーワードで振り分ける。
- 文（句点・改行区切り）ごとにスコアリングし、最も近い項目へ割り当てる。
- 外部API不要。将来 Claude API での高精度分類に差し替え可能（interfaceは parse_hearing で固定）。
"""
import re

# 人生相談カルテ：DBカラム -> 人生6大項目+α を示唆するキーワード群
#   current_situation=家計 / challenges=住環境 / needs=万が一 / budget=老後 /
#   authority=災害 / timeline=健康 / competitors=想い・背景 / next_action=次の一手
FIELD_KEYWORDS = {
    "next_action": ["次回", "次の", "宿題", "フォロー", "持ち帰", "送付", "提案", "約束", "までに", "提出", "アクション"],
    "current_situation": ["家計", "収入", "支出", "貯金", "貯蓄", "家賃", "住居費", "ローン返済", "収支", "お金", "毎月", "手取り", "節約"],
    "challenges": ["住まい", "住環境", "賃貸", "マイホーム", "部屋", "間取り", "広さ", "立地", "通勤", "引越", "住みたい", "持ち家", "戸建", "マンション"],
    "needs": ["万が一", "保険", "生命保険", "死亡", "遺族", "もしも", "備え", "保障"],
    "budget": ["老後", "年金", "リタイア", "退職", "老後資金", "セカンドライフ", "将来の生活"],
    "authority": ["災害", "地震", "防災", "水害", "台風", "ハザード", "避難"],
    "timeline": ["健康", "病気", "医療", "持病", "体調", "介護", "通院", "健診"],
    "competitors": ["想い", "家族", "子供", "子ども", "将来", "夢", "大切", "価値観", "ライフプラン", "暮らし", "希望"],
}

# 判定の優先順（next_action を先に＝「次回までに〜」が他項目に吸われないよう）
FIELD_PRIORITY = ["next_action", "needs", "budget", "authority", "timeline", "current_situation", "challenges", "competitors"]


def _split_sentences(text: str):
    parts = re.split(r"[。\n!！?？]", text)
    return [p.strip() for p in parts if p.strip()]


def parse_hearing(text: str):
    """
    生テキストを各項目へ振り分けて返す（公開API）。
    Claude が使える設定（APIキーあり & DEMO_MODE無効）なら AI 振り分け、
    未設定・デモ・失敗時はキーワードベースに自動フォールバックする。
    返り値: {field_key: "文1 文2", ...}（該当なしのキーは含めない）
    """
    try:
        from ai_services.config import settings as _s
        if _s.has_anthropic and not _s.DEMO_MODE:
            from ai_services.ai import classify_hearing_ai
            return classify_hearing_ai(text)
    except Exception:
        pass  # AI未設定/失敗時はキーワードベースへ
    return parse_hearing_rule(text)


def parse_hearing_rule(text: str):
    """
    キーワードベースの振り分け（オフライン・フォールバック用）。
    返り値: {field_key: "文1 文2", ...}（該当なしのキーは含めない）
    """
    result = {}
    if not text or not text.strip():
        return result

    for sentence in _split_sentences(text):
        best_field = None
        best_score = 0
        for field in FIELD_PRIORITY:
            score = 0
            for kw in FIELD_KEYWORDS[field]:
                if kw in sentence:
                    # 長いキーワードほど高スコア（より具体的な一致を優先）
                    score += len(kw)
            # 優先度の高い項目に僅かな下駄をはかせる
            if score > best_score:
                best_score = score
                best_field = field

        # どの項目にも一致しなければ「現状」に寄せる
        target = best_field if best_field else "current_situation"
        if target in result:
            result[target] += " " + sentence
        else:
            result[target] = sentence

    return result
