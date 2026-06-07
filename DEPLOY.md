# 🚀 ライフメイクセールス クラウドデプロイ手順

ネット上のどこからでも(スマホ含む)アクセスできるようにする手順です。
**Docker 1コンテナ**で動き、データ(SQLite + 音声)は永続ディスク `/data` に保存します。

> ⚠️ **公開前に必ず `APP_PASSWORD` を設定**してください。未設定だと誰でも顧客・商談データを閲覧できてしまいます。
> 認証は実装済みで、`APP_PASSWORD` を入れるとログイン必須になります。

## 必要な環境変数(クラウドのダッシュボードで設定)

| 変数 | 用途 | 必須 |
|------|------|------|
| `APP_PASSWORD` | ログインパスワード | **必須(公開時)** |
| `DEMO_MODE` | `true`=AIはサンプル動作 / `false`=本物のAI(要キー) | 任意(既定true) |
| `ANTHROPIC_API_KEY` | AI議事録の生成(Claude) | AIを本番で使うなら |
| `OPENAI_API_KEY` | 文字起こし(Whisper) | 同上 |
| `ASSEMBLYAI_API_KEY` | 話者分離 | 任意 |
| `DATABASE_PATH` | `/data/sales_tool.db`(永続ディスク) | 設定済み(render.yaml) |
| `UPLOAD_DIR` | `/data/uploads` | 設定済み |

---

## いちばん簡単:Render.com（GUI・無料枠あり）

### 事前準備
1. **GitHub アカウント**を作る（無料）
2. `sales_tool` フォルダを GitHub リポジトリに push（やり方が分からなければ私が手順を出します）
3. **Render アカウント**を作る（無料・GitHub連携でログイン）

### デプロイ
1. Render で **New → Blueprint** をクリック
2. さきほどの GitHub リポジトリを選択（`render.yaml` を自動認識）
3. 環境変数の入力を求められるので **`APP_PASSWORD`**（好きなパスワード）を入力
   - 本物のAIを使うなら `DEMO_MODE=false` にして `ANTHROPIC_API_KEY` 等も入力
4. **Apply / Deploy** を押す → 数分で `https://life-make-sales-xxxx.onrender.com` が発行される
5. そのURLを開く → ログイン画面が出る → 設定したパスワードで入る

これで**スマホでも、社外からでも**アクセスできます。

---

## 他の選択肢
- **Railway**：`Procfile` を認識。GitHub連携 → 環境変数設定 → デプロイ（※永続ディスクは別途設定）
- **Fly.io**：`flyctl launch` → `flyctl volumes create data --size 1` → `flyctl secrets set APP_PASSWORD=...` → `flyctl deploy`
- **自社サーバー/VPS（Docker）**：`docker build -t lms . && docker run -d -p 8123:8123 -e APP_PASSWORD=xxx -v lmsdata:/data lms`

## 運用の注意
- **データ永続化**：`/data` を必ず永続ディスクに割り当てる（SQLiteと音声が消えないように）
- **バックアップ**：`/data/sales_tool.db` を定期的に控える
- **大量アクセス**：将来は SQLite → PostgreSQL へ（`database.py` の差し替えで対応可能）
- **HTTPS**：Render / Fly / Railway は自動で付きます
