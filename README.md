# ライフメイクセールス（Life Make Sales）

住宅営業クローザー向けの統合営業支援Webアプリです（FastAPI + SQLite、ビルド不要のSPA）。
データは既定でこのPC内のSQLite（`sales_tool.db`）に保存されます。設定により本物のAI（Claude/Whisper）やクラウド公開も可能です。

## 機能一覧

| 機能 | 説明 |
|------|------|
| 📊 ダッシュボード | 統計カード＋パイプライン棒グラフ＋今日のタスク＋予定面談＋アクティビティ履歴。加重見込み・受注率・期限超過も表示 |
| ✅ タスク抽出 | 商談メモ／議事録を貼る・話すと「やること」を自動抽出（期限・優先度も推定）。検索／状態・優先度フィルタ付き |
| 🏢 CRM（顧客） | 顧客企業・担当者を内蔵管理。詳細画面に商談/面談/タスク/アクティビティ履歴＋クイック追加。検索付き |
| 📈 商談フロー | カンバン形式。ドラッグでステージ移動、列ごとの金額合計、パイプライン総額・加重見込みを表示 |
| 🎤 ヒアリングシート | BANT＋課題ヒアリング。各項目を音声入力できるほか、**「シート全体を話す→AIが項目へ自動振り分け」**。次アクションをワンクリックでタスク化 |
| 📅 面談管理 | 予約・アジェンダ・議事録（音声入力可）・実施状況を管理。**議事録からタスク自動抽出**。検索／状態フィルタ付き |
| 🎓 営業育成 | 標準カリキュラム＋習得状況・理解度（採点）の進捗管理。習得率バー表示 |

## 機能間の連携（Sales Hub の強み）

- 面談の**議事録 → タスク自動抽出**（顧客・商談に自動ひもづけ）
- ヒアリングの**次アクション → タスク化**（ワンクリック）
- 顧客詳細から**商談／面談／ヒアリング／タスクをクイック追加**
- すべてのデータが1つのDBで連動し、ダッシュボード・顧客詳細に**アクティビティ履歴**として集約

## 起動方法（かんたん）

1. `起動.bat` をダブルクリック
   - 初回のみ自動で `.env` 作成＋ライブラリをインストールします（数分）
2. 自動でブラウザが開きます（開かない場合は手動で http://127.0.0.1:8123 ）
3. 終了するときは、黒いウィンドウで **Ctrl + C**

---

## 🖥️ 別のPCでセットアップする（再現手順）

このプロジェクトは GitHub（`life-make-sales`）に保管されています。別のPCでは以下だけで環境を再現できます。
**コードは git で同期されますが、`.env`（APIキー等）と `sales_tool.db`（データ）は同期されません**（安全のため）。

### Windows
```powershell
git clone https://github.com/nrealize6078-hue/life-make-sales.git
cd life-make-sales
# 起動.bat をダブルクリック（初回に .env 作成と依存インストールを自動実行）
```

### Mac / Linux
```bash
git clone https://github.com/nrealize6078-hue/life-make-sales.git
cd life-make-sales
bash setup.sh
```

### セットアップ後にやること
1. `.env` を開き、必要なら設定（何もしなくても `DEMO_MODE=true` で全機能を試せます）
   - 本物のAIを使う → `DEMO_MODE=false` ＋ `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` など
   - ネット公開する → `APP_PASSWORD` を設定（初回起動でその値の管理者 admin が作られます）
2. （任意）無料のローカル文字起こしを使う → `setup_whisper.bat` を実行し、`.env` で `LOCAL_WHISPER=true`
3. データを引き継ぐ場合 → 旧PCの `sales_tool.db` を新PCの同じ場所にコピー

### 手動で起動する場合
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn main:app --host 127.0.0.1 --port 8123
```

---

## 📁 プロジェクト構成

```
life-make-sales/
├── main.py                 … FastAPI 本体（全APIエンドポイント）
├── database.py             … SQLite スキーマ・初期データ・自動マイグレーション
├── auth.py                 … 認証（ユーザー/ロール/セッション・pbkdf2）
├── task_extractor.py       … タスク抽出（AI＋ルールベース自動切替）
├── hearing_parser.py       … 人生相談カルテ振り分け（AI＋ルールベース）
├── hubspot_sync.py         … HubSpot連携（任意・HUBSPOT_TOKENで有効化）
├── ai_services/            … AIエンジン
│   ├── config.py           …   .env 読み込み・設定
│   ├── ai.py               …   Claude（議事録/抽出/分類/提案トーク）
│   ├── transcribe.py       …   OpenAI Whisper（クラウド文字起こし）
│   ├── local_whisper.py    …   ローカル文字起こし呼び出し
│   ├── diarize.py          …   AssemblyAI（話者分離）
│   └── jobs_sql.py         …   DBキュー＋常駐ワーカー（AI議事録の非同期処理）
├── whisper_local.py        … whisper_venv 側で動く文字起こしスクリプト
├── static/                 … フロントエンド（index.html / app.js / style.css）
├── requirements.txt        … 本体の依存（.venv）
├── requirements-whisper.txt… ローカル文字起こしの依存（whisper_venv・任意）
├── .env.example            … 環境変数テンプレート（.env はこれを基に作る）
├── 起動.bat / setup.sh     … セットアップ＆起動（Windows / Mac・Linux）
├── setup_whisper.bat       … ローカル文字起こし環境の構築（任意）
├── Dockerfile / render.yaml / Procfile … クラウド配備用（DEPLOY.md 参照）
└── 設計書.md               … システム設計書
```

**git に含まれないもの**（各PCで生成・各自設定）: `.env` / `sales_tool.db` / `data/`（音声） / `.venv/` / `whisper_venv/`

## 音声入力について

- ブラウザ標準の **Web Speech API** を使用（追加インストール不要）
- **Google Chrome / Microsoft Edge** を推奨
- 初回はマイクの使用許可を求められます → 「許可」を選択
- 🎤 ボタンを押す → 話す → もう一度押すと停止＆文字入力されます

## 技術構成

- バックエンド: FastAPI + Uvicorn
- データベース: SQLite（標準ライブラリ、追加DB不要）
- フロントエンド: バニラJS（ビルド不要の単一SPA）

## 実装済みの拡張ポイント

- **タスク抽出／カルテ振り分けのAI化**: `ANTHROPIC_API_KEY` 設定＆`DEMO_MODE=false` で Claude、未設定時はルールベースに自動フォールバック
- **外部CRM連携**: `HUBSPOT_TOKEN` 設定で HubSpot 同期が有効化（CRM画面「🔗 HubSpot」）
- **AI議事録の非同期処理**: DBキュー＋常駐ワーカー（再起動耐性あり・追加インフラ不要）
- **認証**: ユーザー別アカウント／ロール／セッション失効（`APP_PASSWORD` から初回 admin を自動作成）

## データのバックアップ

`sales_tool.db` ファイルをコピーするだけでバックアップ完了です。
このファイルを削除すると全データが消えるのでご注意ください。

## 🎙️ AI議事録（v3で統合）

ナビ「AI議事録」タブから、音声/録音/テキスト → 文字起こし → 議事録・要約・決定事項・次アクション・タグを自動生成。話者分離（誰が話したか）と実名割り当て、Markdown出力に対応。**生成した次アクションはワンクリックでタスクに登録**でき、顧客・商談とも連携します。

- エンジン: `ai_services/`（Whisper=文字起こし / Claude=議事録 / AssemblyAI=話者分離）
- 設定: `.env`（`DEMO_MODE=true` でAPIキー不要のお試し動作。本番は `false` + 各APIキー）
- データ: 既存の `meetings` テーブルにAI列を統合（面談=議事録）
