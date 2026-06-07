"""
SQLite データベース層
- 標準ライブラリ sqlite3 のみ使用（追加インストール不要）
- アプリ起動時にスキーマを自動作成し、初回のみサンプルデータを投入
"""
import sqlite3
import os
from datetime import datetime, timedelta

# DB保存先。クラウドでは DATABASE_PATH 環境変数で永続ディスク上に向ける。
DB_PATH = os.getenv("DATABASE_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "sales_tool.db")
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)


def get_conn():
    """1リクエストごとに接続を返す。row_factory で dict 風アクセスを可能にする。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# 商談ステージ（商談フローの段階定義）
DEAL_STAGES = [
    "リード",
    "アプローチ",
    "ヒアリング",
    "提案",
    "見積",
    "クロージング",
    "受注",
    "失注",
]


SCHEMA = """
-- 会社 / 顧客（CRM中核）
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    industry TEXT,
    address TEXT,
    phone TEXT,
    website TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

-- 担当者（会社にひもづく人）
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    name TEXT NOT NULL,
    title TEXT,
    email TEXT,
    phone TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL
);

-- 商談（商談フロー / パイプライン）
CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    title TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'リード',
    amount INTEGER DEFAULT 0,
    probability INTEGER DEFAULT 0,
    expected_close TEXT,
    owner TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL
);

-- タスク（タスク抽出 / ToDo）
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_text TEXT,
    due_date TEXT,
    priority TEXT DEFAULT '中',
    status TEXT DEFAULT '未着手',
    company_id INTEGER,
    deal_id INTEGER,
    created_at TEXT NOT NULL,
    done_at TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
    FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE SET NULL
);

-- 面談（面談管理）
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    contact_id INTEGER,
    deal_id INTEGER,
    title TEXT NOT NULL,
    scheduled_at TEXT,
    duration_min INTEGER DEFAULT 60,
    location TEXT,
    meeting_type TEXT DEFAULT 'オンライン',
    status TEXT DEFAULT '予定',
    agenda TEXT,
    minutes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
    FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE SET NULL
);

-- ヒアリングシート（音声入力対応）
CREATE TABLE IF NOT EXISTS hearing_sheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    contact_id INTEGER,
    deal_id INTEGER,
    title TEXT NOT NULL,
    -- 各項目を個別カラムで保持（BANT + 課題/背景）
    current_situation TEXT,   -- 現状
    challenges TEXT,          -- 課題・困りごと
    needs TEXT,               -- 要望・ニーズ
    budget TEXT,              -- 予算 (Budget)
    authority TEXT,           -- 決裁者 (Authority)
    timeline TEXT,            -- 導入時期 (Timeline)
    competitors TEXT,         -- 競合・比較対象
    next_action TEXT,         -- 次のアクション
    raw_voice_text TEXT,      -- 音声入力の生テキスト
    created_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
    FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE SET NULL
);

-- 営業育成：学習モジュール
CREATE TABLE IF NOT EXISTS training_modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    sort_order INTEGER DEFAULT 0
);

-- 営業育成：習得チェック / 進捗
CREATE TABLE IF NOT EXISTS training_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER NOT NULL,
    member TEXT NOT NULL,
    status TEXT DEFAULT '未学習',
    score INTEGER,
    memo TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (module_id) REFERENCES training_modules(id) ON DELETE CASCADE
);
"""


def init_db():
    """スキーマ作成 + 初回シード。"""
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    _seed(conn)
    conn.close()


# meetings テーブルに後付けする AI議事録用カラム(名前: 型)
_MEETING_AI_COLUMNS = {
    "audio_filename": "TEXT",
    "diarize": "INTEGER DEFAULT 0",
    "transcript": "TEXT",
    "summary": "TEXT",
    "minutes_md": "TEXT",
    "dialogue_md": "TEXT",
    "utterances": "TEXT",      # JSON 文字列
    "speaker_map": "TEXT",     # JSON 文字列
    "decisions": "TEXT",       # JSON 文字列
    "next_actions": "TEXT",    # JSON 文字列
    "tags": "TEXT",            # JSON 文字列
    "ai_status": "TEXT",       # queued/processing/transcribed/summarizing/summarized/error
    "error_message": "TEXT",
}


def _migrate(conn):
    """既存DBに不足カラムを追加する簡易マイグレーション。"""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(meetings)")}
    for name, decl in _MEETING_AI_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE meetings ADD COLUMN {name} {decl}")
    conn.commit()


def _seed(conn):
    """データが空のときだけサンプルを投入する。"""
    now = datetime.now().isoformat(timespec="seconds")

    # --- 営業育成モジュール（常に最新の標準カリキュラムを保証） ---
    if conn.execute("SELECT COUNT(*) FROM training_modules").fetchone()[0] == 0:
        modules = [
            ("基礎", "営業の基本姿勢とマインドセット",
             "・顧客の成功が自分の成功。\n・売り込むのではなく課題を一緒に解決する。\n・約束は必ず守り、レスポンスは早く。", 1),
            ("基礎", "アポイント獲得の型",
             "1. 相手の課題仮説を立てる\n2. 会う価値（メリット）を一言で\n3. 日程は二者択一で提案\n4. 断られても次回接点を残す", 2),
            ("ヒアリング", "BANT条件の聞き出し方",
             "Budget(予算) / Authority(決裁者) / Need(必要性) / Timeline(時期)。\n直接聞かず、背景→現状→課題→理想の順で会話を展開する。", 3),
            ("ヒアリング", "課題の深掘り（なぜを5回）",
             "表面的な要望の裏にある『本当の困りごと』を掘る。\n『なぜそれが必要なのですか？』を繰り返し、定量的な影響まで聞く。", 4),
            ("提案", "提案資料の組み立て",
             "現状→課題→あるべき姿→解決策→効果→費用→導入ステップ。\n顧客の言葉をそのまま使うと刺さりやすい。", 5),
            ("クロージング", "反論処理とクロージング",
             "よくある反論（高い/今じゃない/検討する）への切り返しを用意。\nテストクロージングで温度感を測り、次の一歩を明確に握る。", 6),
        ]
        conn.executemany(
            "INSERT INTO training_modules (category, title, content, sort_order) VALUES (?,?,?,?)",
            modules,
        )
        conn.commit()

    # --- 取引・顧客サンプル（初回のみ。各ステージに商談が並ぶデモ） ---
    if conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0:
        cur = conn.cursor()

        def days(n):
            return (datetime.now() + timedelta(days=n)).date().isoformat()

        def at(n, h):
            return (datetime.now() + timedelta(days=n)).replace(
                hour=h, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")

        # 会社・担当者・商談・面談をまとめて投入
        companies = [
            # (name, industry, address, phone, website, notes,
            #   contact(name,title,email,phone),
            #   deal(title, stage, amount, prob, close_days, notes))
            ("株式会社サンプル商事", "卸売", "東京都千代田区1-1-1", "03-1234-5678", "https://example.com",
             "展示会で名刺交換。福利厚生サービスに関心あり。",
             ("山田 太郎", "総務部長", "yamada@example.com", "090-0000-0001"),
             ("福利厚生サービス導入", "ヒアリング", 1200000, 40, 30, "従業員300名規模。月額課金モデルを提案予定。")),
            ("グリーンテック工業", "製造", "大阪府大阪市北区2-2-2", "06-2222-3333", "https://greentech.example.jp",
             "工場のDX推進中。現場改善ツールを比較検討。",
             ("佐藤 花子", "DX推進室 室長", "sato@greentech.example.jp", "090-0000-0002"),
             ("現場DXパッケージ", "提案", 3500000, 60, 21, "競合2社と比較中。ROIを資料で訴求。")),
            ("みらいフーズ株式会社", "食品", "愛知県名古屋市中区3-3-3", "052-444-5555", "https://miraifoods.example.jp",
             "多店舗展開。シフト管理の効率化が課題。",
             ("鈴木 一郎", "経営企画 部長", "suzuki@miraifoods.example.jp", "090-0000-0003"),
             ("シフト管理SaaS", "見積", 980000, 70, 14, "見積提示済み。決裁は今月末予定。")),
            ("ABCコンサルティング", "サービス", "福岡県福岡市博多区4-4-4", "092-666-7777", "https://abc-c.example.jp",
             "紹介経由のリード。まずは情報交換から。",
             ("高橋 美咲", "代表取締役", "takahashi@abc-c.example.jp", "090-0000-0004"),
             ("営業代行プラン", "リード", 600000, 15, 45, "初回アプローチ前。ニーズ未確認。")),
            ("日本ロジ流通", "物流", "神奈川県横浜市西区5-5-5", "045-888-9999", "https://nipponlogi.example.jp",
             "繁忙期の人員配置に課題。導入実績を重視。",
             ("田中 健", "物流統括 マネージャー", "tanaka@nipponlogi.example.jp", "090-0000-0005"),
             ("配車最適化システム", "クロージング", 2400000, 85, 7, "最終承認待ち。来週受注見込み。")),
            ("スマイル歯科クリニック", "医療", "北海道札幌市中央区6-6-6", "011-100-2000", "https://smile-dc.example.jp",
             "予約管理の効率化で成約。今後の追加提案余地あり。",
             ("渡辺 由美", "院長", "watanabe@smile-dc.example.jp", "090-0000-0006"),
             ("予約管理システム", "受注", 750000, 100, -3, "先月受注。導入サポート中。")),
        ]

        first_deal_id = first_company_id = first_contact_id = None
        for i, (name, ind, addr, tel, web, note, ct, dl) in enumerate(companies):
            cur.execute(
                "INSERT INTO companies (name, industry, address, phone, website, notes, created_at) VALUES (?,?,?,?,?,?,?)",
                (name, ind, addr, tel, web, note, now))
            cid = cur.lastrowid
            cur.execute(
                "INSERT INTO contacts (company_id, name, title, email, phone, notes, created_at) VALUES (?,?,?,?,?,?,?)",
                (cid, ct[0], ct[1], ct[2], ct[3], "", now))
            ctid = cur.lastrowid
            cur.execute(
                "INSERT INTO deals (company_id, title, stage, amount, probability, expected_close, owner, notes, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cid, dl[0], dl[1], dl[2], dl[3], days(dl[4]), "自分", dl[5], now, now))
            did = cur.lastrowid
            if i == 0:
                first_company_id, first_contact_id, first_deal_id = cid, ctid, did

        # 面談（予定・実施済）
        cur.execute(
            "INSERT INTO meetings (company_id, contact_id, deal_id, title, scheduled_at, duration_min, location, meeting_type, status, agenda, minutes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (first_company_id, first_contact_id, first_deal_id, "課題ヒアリング面談", at(2, 14), 60,
             "Zoom", "オンライン", "予定", "現状の福利厚生制度と課題を確認する。", "", now))
        cur.execute(
            "INSERT INTO meetings (company_id, contact_id, deal_id, title, scheduled_at, duration_min, location, meeting_type, status, agenda, minutes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (2, None, 2, "提案プレゼン", at(4, 10), 90, "先方会議室", "対面", "予定",
             "ROIシミュレーションを提示し、競合比較で優位性を訴求。", "", now))

        # タスク（期限・優先度を散らす）
        tasks = [
            ("提案資料を作成して送付する", "面談メモより自動抽出", days(2), "高", "未着手", first_company_id, first_deal_id),
            ("ROIシミュレーションを準備する", "商談メモより", days(3), "高", "進行中", 2, 2),
            ("見積の決裁状況を確認する", "", days(1), "中", "未着手", 3, 3),
            ("導入事例集を送付する", "", days(5), "中", "未着手", 5, 5),
            ("受注後の導入キックオフを調整", "", days(4), "低", "未着手", 6, 6),
        ]
        for t in tasks:
            cur.execute(
                "INSERT INTO tasks (title, source_text, due_date, priority, status, company_id, deal_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)", (*t, now))

        # ヒアリングシート（記入済みサンプル1件）
        cur.execute(
            "INSERT INTO hearing_sheets (company_id, contact_id, deal_id, title, current_situation, challenges, needs, "
            "budget, authority, timeline, competitors, next_action, raw_voice_text, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (2, None, 2, "グリーンテック工業 初回ヒアリング",
             "紙とExcelで現場日報を管理。集計に毎月20時間かかっている。",
             "リアルタイムで進捗が見えず、不良対応が後手に回る。",
             "現場のスマホ入力で日報を自動集計したい。",
             "年間300〜400万円", "DX推進室長＋工場長の合議。最終は役員会。",
             "来期（4月）から本格導入したい。", "他社2製品と比較中。",
             "次回までにROIシミュレーションと導入事例を提示する。", "", now))

        conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"DB初期化完了: {DB_PATH}")
