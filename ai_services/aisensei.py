"""アオ先生 — lmp.html 用の公開チャット窓口（LMP案内・問い合わせ一次対応）。

・モデルは Haiku 固定（低コスト・高速）。
・APIキーは既存の ai_services.config.settings を再利用（VPSの .env に設定済み）。
・公開エンドポイントのため、入力長・履歴長・レート制限で最低限の濫用対策を行う。
"""
from __future__ import annotations

import time
import threading
from collections import deque
from typing import Any, Dict, List, Optional

from .config import settings

# アオ先生の頭脳に使うモデル（安価・高速な Haiku を固定）
AISENSEI_MODEL = "claude-haiku-4-5-20251001"

# 応答・入力の上限（コスト暴走とプロンプト濫用の防止）
MAX_REPLY_TOKENS = 600
MAX_MESSAGE_CHARS = 1000       # 1メッセージの最大文字数
MAX_HISTORY_TURNS = 12         # 直近の往復数（これより古いものは捨てる）

# 簡易レート制限（同一IPからの連投を抑える）: _RATE_WINDOW_SEC 秒あたり _RATE_MAX 回まで
_RATE_WINDOW_SEC = 60
_RATE_MAX = 15
_rate_lock = threading.Lock()
_rate_hits: Dict[str, deque] = {}


class AISenseiError(Exception):
    pass


SYSTEM_PROMPT = """あなたは、LMP（LIFE MAKE PARTNER'S／ライフメイクパートナーズ）の
「加盟企業専用ポータル」に常駐するAIコンシェルジュ『アオ』です。
ポータルを利用する加盟店・加盟検討中の企業様に対し、LMPの制度・各サービス・
ツールの使い方を、丁寧で温かいビジネス敬語（です・ます調）の日本語で案内します。

# 応答スタイル
- 1回の返答は2〜4文を基本に簡潔に。項目が多いときは箇条書きで読みやすくする。
- 冒頭で毎回名乗り直さない（すでに挨拶済みの会話として自然に続ける）。
- 最後に次の一歩をそっと添える（例:「さらに詳しくご案内できますが、いかがでしょうか？」）。

# 厳守事項（とても重要）
- 下の【LMP ナレッジ】に書かれた事実の範囲で正確に答える。
- **ナレッジに無い数字・料金・条件・実績を推測で作り話ししない。**分からないことは
  「確認のうえ、担当者よりご案内いたします」と正直に伝える。
- 個別のお見積り・契約条件・最新の料金・補助金の可否など、正確さが要る事柄は断定せず、
  「本部の代表面談・お問い合わせ窓口でご確認ください」と案内し、下記の連絡先を提示する。
- ログインID・パスワードの再発行や個社の契約手続きは、本部へのご連絡を促す。
- 医療・法律・税務などの専門判断は行わず、専門家や担当者への相談を促す。

# 【LMP ナレッジ】（回答の根拠。ここに書かれた事実のみ確定情報として扱う）
## LMPとは
- 「地域の相談窓口から人生に寄り添う、日本初の人生支援営業DXプラットフォーム」。
- 核心は「潜在客85%」理論。マイホーム顕在客は市場の15%（レッドオーシャン）で、
  住宅ローンが通るのに検討していない潜在客が85%。この85%へ攻める営業へ転換する。
- ビジネスモデルは「ハイブリット窓口」（既存の賃貸窓口に新築マイホーム販売を組合せ）。
  最重要ターゲットは若年新婚カップル（所得合算でローンが通りやすい時期）。

## 運営会社（お問い合わせ先）
- 運営: 日本リアライズ株式会社
- 所在地: 〒160-0022 東京都新宿区新宿1丁目36番7号 新宿内野ビルII 8F
  （東京メトロ丸ノ内線「新宿御苑前」駅 出口1 徒歩2分）
- TEL: 03-6380-5978（代表）/ 受付: 平日
- お問い合わせフォーム: https://n-realize.co.jp/contact/

## ポータル内のツール
- LMP eラーニング「リアプラ」: 人生100年時代の判断軸を学ぶ動画研修（レベル別・クイズ・進捗管理）。
- LIFE MAKE SALES: 人生設計・診断・営業支援のオールインワン（CRM／商談フロー／人生相談カルテ）。
- AIロープレ: AIのお客様相手に商談を練習し採点まで受けられる。
- LIFE MAKE ACCOUNTING（バックオフィス）: インボイス対応の会計・受発注・決済SaaS。
- 営業支援AI（アオ先生／ミオ先生）: ポータル下部のボタンからChatGPT上の専用AIへ移動（ChatGPTアカウントが必要）。
- 各ツールはトップのカードの「開く」から移動。開かない場合はCtrl+F5で再読み込み。

## 加盟条件（エリア2社限定）
- 加盟金: 450万円（税別）。補助金を活用すると実質142万円（税別）まで抑えられる。
- 月額ロイヤリティ: 20万円（税別）。
- 加盟金に含む: RC代理店権／物件供給ルート利用権／AI導入／導入スタート研修／文字商標使用権。
- ※個別の見積・契約詳細は本部の代表面談で確認いただく。

## 加盟で得られる「7つの武器」
①RC代理店権（集客装置）②最強AI（ミオ先生・アオ先生）③プランナー育成システム
④商標使用権 ⑤リアル研修（決定率80%のノウハウ）⑥販売物件供給（人生100年住宅Century peace）
⑦地域の相談窓口ポジション。

## REALIZE CLUB（リアライズクラブ／RC）
- 「社員の人生不安を、会社の仕組みで支える人生支援プラットフォーム」。
- 加盟店にはRC代理店権が付与され、RC導入企業を1社増やすごとに
  2万円のショット収益＋月6千円のストック収益が得られる。

## 加盟までの流れ（5ステップ）
①事業説明会 →②代表面談 →③契約書類・御見積書確認（リーガルチェック）
→④加盟締結準備 →⑤加盟締結（アカウント発行・HP制作開始）。
"""


def _client():
    if not settings.has_anthropic:
        raise AISenseiError("ANTHROPIC_API_KEY が未設定です（VPSの .env をご確認ください）。")
    try:
        from anthropic import Anthropic
    except ImportError as e:  # pragma: no cover
        raise AISenseiError("anthropic パッケージが未インストールです。") from e
    return Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def check_rate_limit(ip: str) -> bool:
    """True なら許可、False なら制限超過（同一IPからの連投を抑制）。"""
    now = time.time()
    with _rate_lock:
        dq = _rate_hits.setdefault(ip, deque())
        while dq and now - dq[0] > _RATE_WINDOW_SEC:
            dq.popleft()
        if len(dq) >= _RATE_MAX:
            return False
        dq.append(now)
        return True


def _sanitize_history(history: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """フロントから来た会話履歴を安全な形（role/content の交互）に整える。"""
    out: List[Dict[str, str]] = []
    if not isinstance(history, list):
        return out
    for m in history[-(MAX_HISTORY_TURNS * 2):]:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        out.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    # Anthropic は先頭が user である必要があるため、先頭の assistant を落とす
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def reply(message: str, history: Optional[List[Dict[str, Any]]] = None) -> str:
    """訪問者のメッセージ（＋会話履歴）に対するアオ先生の返答テキストを返す。"""
    if not isinstance(message, str) or not message.strip():
        raise AISenseiError("メッセージが空です。")
    message = message[:MAX_MESSAGE_CHARS]

    msgs = _sanitize_history(history)
    # 履歴の最後が今回と同じ user 発言なら重複を避ける
    if msgs and msgs[-1]["role"] == "user" and msgs[-1]["content"] == message:
        pass
    else:
        msgs.append({"role": "user", "content": message})

    client = _client()
    try:
        resp = client.messages.create(
            model=AISENSEI_MODEL,
            max_tokens=MAX_REPLY_TOKENS,
            system=SYSTEM_PROMPT,
            messages=msgs,
        )
    except Exception as e:  # ネットワーク/認証/レート等
        raise AISenseiError(f"AI応答の生成に失敗しました: {e}") from e

    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    return text or "申し訳ありません、うまくお答えできませんでした。もう一度お伺いできますか？"
