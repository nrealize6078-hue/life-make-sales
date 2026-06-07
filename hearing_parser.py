"""
ヒアリング音声の自動振り分け
- 「シート全体を話した生テキスト」を、BANT＋課題などの各項目へキーワードで振り分ける。
- 文（句点・改行区切り）ごとにスコアリングし、最も近い項目へ割り当てる。
- 外部API不要。将来 Claude API での高精度分類に差し替え可能（interfaceは parse_hearing で固定）。
"""
import re

# 項目キー -> その項目を示唆するキーワード群
FIELD_KEYWORDS = {
    "budget": ["予算", "費用", "コスト", "金額", "円", "万円", "価格", "値段", "いくら", "投資", "ご予算"],
    "authority": ["決裁", "決済者", "決裁者", "承認", "稟議", "権限", "社長", "役員", "部長", "課長", "担当", "窓口", "決める"],
    "timeline": ["時期", "導入", "スケジュール", "いつ", "来期", "今期", "来月", "今月", "年内", "四半期", "納期", "開始", "タイミング"],
    "competitors": ["競合", "他社", "比較", "相見積", "あいみつ", "コンペ", "検討中", "候補", "対抗"],
    "challenges": ["課題", "困", "問題", "悩", "不満", "ペイン", "ボトルネック", "うまくいかな", "できていない", "手間", "非効率", "ミス"],
    "needs": ["要望", "欲しい", "したい", "ニーズ", "期待", "実現", "理想", "求め", "あったらいい", "希望", "ゴール"],
    "current_situation": ["現状", "今は", "現在", "使って", "運用", "体制", "やり方", "既存", "従来", "いま"],
    "next_action": ["次回", "次の", "アクション", "宿題", "フォロー", "持ち帰", "送付", "提案", "見積", "約束", "までに", "提出"],
}

# 表示順（next_action は最後に判定したい＝「次回までに〜」が他項目に吸われないよう優先度高め）
FIELD_PRIORITY = ["next_action", "budget", "authority", "timeline", "competitors", "challenges", "needs", "current_situation"]


def _split_sentences(text: str):
    parts = re.split(r"[。\n!！?？]", text)
    return [p.strip() for p in parts if p.strip()]


def parse_hearing(text: str):
    """
    生テキストを各項目へ振り分けて返す。
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
