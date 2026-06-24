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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")  # ワーカーとWeb処理の書込競合に備える
    return conn


# 商談ステージ（クロージング導線：反響→人生相談→4章プレゼン→交渉→契約）
DEAL_STAGES = [
    "反響・予約",
    "人生相談",
    "プレゼン",
    "交渉",
    "契約",
    "失注",
]
# 旧ステージ → 新ステージ の対応（既存データ移行用）
STAGE_MIGRATION = {
    "リード": "反響・予約",
    "アプローチ": "反響・予約",
    "ヒアリング": "人生相談",
    "提案": "プレゼン",
    "見積": "交渉",
    "クロージング": "交渉",
    "受注": "契約",
    "失注": "失注",
}

# トップクローザー育成カリキュラム（PDF「トップクローザー研修プログラム」準拠）
# (category, title, content, sort_order)
TOP_CLOSER_CURRICULUM = [
    ("基礎", "クローザーの基本姿勢",
     "・後悔しない選択を“共に創る”。\n・売り込まない／急がせない。潜在客に“根拠”を伝える。\n・約束は必ず守り、レスポンスは早く。", 1),
    ("基礎", "賃貸窓口からマイホームへの導線",
     "リアライズクラブ(福利厚生)で企業導入 → 完全予約制 → マイホーム提案。\n誰もやっていないブルーオーシャンの導線。", 2),
    ("人生相談", "人生6大項目の整理",
     "家計・住環境・万が一・老後・災害・病気の現状を一緒に見える化。\n“買う/買わない”ではなく“住居費設計”へ視点を移す。", 3),
    ("人生相談", "人生相談カルテの作り方",
     "お客様の現状把握 → 不安の言語化 → 次の一手。\nヒアリングを“雑談”から“設計”に変え、警戒心を下げる。", 4),
    ("プレゼン", "4章プレゼンの型",
     "①家は買うべき ②今買うべき ③ここを買うべき ④うちから買うべき。\n各章の根拠を順に積み上げ、納得で進める。", 5),
    ("プレゼン", "よくある質問Q&A対応",
     "「賃貸で十分」「今じゃない」等への根拠ベースの返し。\n潜在客に根拠を伝える手法でオーバートークを避ける。", 6),
    ("交渉・クロージング", "完全交渉マニュアル(ルーティン化)",
     "交渉を仕組み化・ルーティン化。\nテストクロージングで温度感を測り、次の一歩を明確に握る。", 7),
    ("契約・手続き", "契約と住宅ローン手続き",
     "売買/請負契約・重要事項説明・住宅ローン手続きの型。\nマニュアルに沿って進め、専属スタッフがフォロー。", 8),
    ("集客・RC導線", "リアライズクラブからの集客",
     "福利厚生(RC)で企業導入 → 完全予約制 → マイホーム提案へつなぐB2B2C導線。", 9),
    ("ツール活用", "AI(ミオ/アオ/ディグラム)とリアプラ",
     "ミオ先生=お客様の整理と安心／アオ先生=クローザーの判断と覚悟／ディグラムGPT=物件調査・広告・ロープレ・契約支援。\nリアプラ=24時間の学習管理。", 10),
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
    stage TEXT NOT NULL DEFAULT '反響・予約',
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

-- 認証：ユーザー（クローザー）アカウント
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    password_hash TEXT NOT NULL,   -- pbkdf2 salt$hash
    role TEXT NOT NULL DEFAULT 'member',  -- admin / member
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- 認証：ログインセッション（トークン失効に対応）
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ①幸せ意識度チェック（飛込・1回目アンケート）
CREATE TABLE IF NOT EXISTS happiness_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    contact_id INTEGER,
    deal_id INTEGER,
    title TEXT NOT NULL,
    answers TEXT,        -- JSON {q1:'yes'|'no'|'', ...}
    no_count INTEGER DEFAULT 0,
    memo TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
    FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE SET NULL
);

-- ②ライフメイクカルテ（2回目アンケート・全項目をJSONで保持）
CREATE TABLE IF NOT EXISTS lifemake_kartes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    contact_id INTEGER,
    deal_id INTEGER,
    title TEXT NOT NULL,
    data TEXT,           -- JSON 全項目
    created_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
    FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE SET NULL
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
    "auto_generate": "INTEGER DEFAULT 1",  # キュー処理時に議事録生成まで行うか
}


def _ensure_columns(conn, table, columns):
    existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _migrate(conn):
    """既存DBに不足カラムを追加する簡易マイグレーション。"""
    _ensure_columns(conn, "meetings", _MEETING_AI_COLUMNS)
    # 商談: 4章プレゼン進捗(JSON), 顧客の人生相談カルテ: AI提案トーク(JSON)
    _ensure_columns(conn, "deals", {"presentation": "TEXT"})
    _ensure_columns(conn, "hearing_sheets", {"talk_points": "TEXT"})

    # HubSpot連携: 外部CRMのオブジェクトIDを保持(再同期で重複作成しないため)
    _ensure_columns(conn, "companies", {"hubspot_id": "TEXT"})
    _ensure_columns(conn, "contacts", {"hubspot_id": "TEXT"})
    _ensure_columns(conn, "deals", {"hubspot_id": "TEXT"})

    # 旧ステージの商談を新ステージへ移行
    for old, new in STAGE_MIGRATION.items():
        if old != new:
            conn.execute("UPDATE deals SET stage=? WHERE stage=?", (new, old))

    # 育成カリキュラムをトップクローザー版へ差し替え(新版が未投入なら入れ替え)
    has_new = conn.execute(
        "SELECT COUNT(*) FROM training_modules WHERE title='4章プレゼンの型'"
    ).fetchone()[0]
    if not has_new:
        conn.execute("DELETE FROM training_modules")
        conn.executemany(
            "INSERT INTO training_modules (category, title, content, sort_order) VALUES (?,?,?,?)",
            TOP_CLOSER_CURRICULUM,
        )
    conn.commit()


def _seed(conn):
    """データが空のときだけサンプルを投入する。"""
    now = datetime.now().isoformat(timespec="seconds")

    # --- 育成カリキュラム（空なら投入。通常は _migrate で最新化済み） ---
    if conn.execute("SELECT COUNT(*) FROM training_modules").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO training_modules (category, title, content, sort_order) VALUES (?,?,?,?)",
            TOP_CLOSER_CURRICULUM,
        )
        conn.commit()

    # --- 取引・顧客サンプル（SEED_SAMPLE=true のときだけ投入。既定は実データ運用） ---
    if os.getenv("SEED_SAMPLE", "false").lower() in ("1", "true", "yes") \
            and conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0:
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
             ("福利厚生サービス導入", "人生相談", 1200000, 40, 30, "従業員300名規模。月額課金モデルを提案予定。")),
            ("グリーンテック工業", "製造", "大阪府大阪市北区2-2-2", "06-2222-3333", "https://greentech.example.jp",
             "工場のDX推進中。現場改善ツールを比較検討。",
             ("佐藤 花子", "DX推進室 室長", "sato@greentech.example.jp", "090-0000-0002"),
             ("現場DXパッケージ", "プレゼン", 3500000, 60, 21, "競合2社と比較中。ROIを資料で訴求。")),
            ("みらいフーズ株式会社", "食品", "愛知県名古屋市中区3-3-3", "052-444-5555", "https://miraifoods.example.jp",
             "多店舗展開。シフト管理の効率化が課題。",
             ("鈴木 一郎", "経営企画 部長", "suzuki@miraifoods.example.jp", "090-0000-0003"),
             ("シフト管理SaaS", "交渉", 980000, 70, 14, "見積提示済み。決裁は今月末予定。")),
            ("ABCコンサルティング", "サービス", "福岡県福岡市博多区4-4-4", "092-666-7777", "https://abc-c.example.jp",
             "紹介経由のリード。まずは情報交換から。",
             ("高橋 美咲", "代表取締役", "takahashi@abc-c.example.jp", "090-0000-0004"),
             ("営業代行プラン", "反響・予約", 600000, 15, 45, "初回アプローチ前。ニーズ未確認。")),
            ("日本ロジ流通", "物流", "神奈川県横浜市西区5-5-5", "045-888-9999", "https://nipponlogi.example.jp",
             "繁忙期の人員配置に課題。導入実績を重視。",
             ("田中 健", "物流統括 マネージャー", "tanaka@nipponlogi.example.jp", "090-0000-0005"),
             ("配車最適化システム", "交渉", 2400000, 85, 7, "最終承認待ち。来週受注見込み。")),
            ("スマイル歯科クリニック", "医療", "北海道札幌市中央区6-6-6", "011-100-2000", "https://smile-dc.example.jp",
             "予約管理の効率化で成約。今後の追加提案余地あり。",
             ("渡辺 由美", "院長", "watanabe@smile-dc.example.jp", "090-0000-0006"),
             ("予約管理システム", "契約", 750000, 100, -3, "先月受注。導入サポート中。")),
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
