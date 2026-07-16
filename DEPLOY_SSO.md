# 横断ログイン(SSO) 本番反映手順

ポータルの平文パスワードを廃止し、**1回のログインで全ツールに入れる**ようにするための反映手順です。

---

## ⚠️ 順序を必ず守ってください

**サーバー → アカウント作成 → ポータル** の順です。

> ポータル(lmp.html)を先に上げると、**サーバーにアカウントがまだ無いため、全員ログインできなくなります。**

```
① サーバー反映  →  ② アカウント作成  →  ③ 動作確認  →  ④ ポータル差し替え
```

---

## ① サーバー反映（VPSにSSHログインして実行）

```bash
cd /opt/life-make-sales
sudo git pull --ff-only            # 認証基盤のコードを取得
```

`.env` に次の2行を追記します（`sudo nano .env`）。

```ini
# 横断ログイン(SSO)
SSO_COOKIE_DOMAIN=.lifemakepartners.net
SSO_ALLOWED_ORIGINS=https://lifemakepartners.net,https://www.lifemakepartners.net
```

| 設定 | 意味 |
|---|---|
| `SSO_COOKIE_DOMAIN` | Cookieを全サブドメイン共通で発行する（**これがSSOの肝**）。未設定なら従来どおりSALES単独 |
| `SSO_ALLOWED_ORIGINS` | ログインAPIを呼べるオリジン（ポータル）。ここに無いサイトからは拒否 |

反映:

```bash
sudo systemctl restart lms
systemctl status lms               # active (running) を確認
```

> `SSO_COOKIE_DOMAIN` を設定すると Cookie は自動的に `Secure` になります（https必須）。
> sales.lifemakepartners.net は https なので問題ありません。

---

## ② アカウント作成（旧パスワードは全て公開済みのため、必ず再発行）

```bash
cd /opt/life-make-sales

# 本部
.venv/bin/python manage_accounts.py add --id LMP-ADMIN --role hq --name "LMP本部" --email hq@n-realize.co.jp

# 加盟店（会社ごと。--company は無ければ自動作成される）
.venv/bin/python manage_accounts.py add --id LMP-0001 --role company --name "加盟店A" --company "加盟店A" --email a@example.com

# 社員
.venv/bin/python manage_accounts.py add --id emp001 --role member --name "山田太郎" --company "加盟店A"

# 確認
.venv/bin/python manage_accounts.py list
```

- パスワードは**自動生成され、実行直後に1度だけ表示**されます。控えて配布してください（DBにはハッシュのみ保存）。
- **ID・メールアドレスのどちらでもログインできます。**
- 再発行: `manage_accounts.py reset --id LMP-0001` / 停止: `disable --id LMP-0005`

### ロール

| ロール | 範囲 |
|---|---|
| `hq` | LMP本部。全会社・全データ、管理操作可 |
| `company` | 加盟店。自社のみ |
| `member` | 社員。自分のデータのみ |

※既存の `admin` は `hq` と同等に扱われるため、そのまま使えます。

---

## ③ 動作確認（ポータル差し替え前に必ず）

```bash
# ログインできるか（成功なら {"ok":true,...} が返る）
curl -i -X POST https://sales.lifemakepartners.net/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"LMP-0001","password":"<発行されたパスワード>"}'
```

確認ポイント:
- `HTTP/1.1 200` が返る
- `Set-Cookie: lms_session=...; Domain=.lifemakepartners.net; Secure; HttpOnly` が含まれる ← **これが出ればSSOの土台は成功**

```bash
# ポータルからのCORSが許可されているか
curl -i -X OPTIONS https://sales.lifemakepartners.net/api/auth/login \
  -H 'Origin: https://lifemakepartners.net' -H 'Access-Control-Request-Method: POST'
```
→ `Access-Control-Allow-Origin: https://lifemakepartners.net` が返ればOK。

---

## ④ ポータル差し替え

`lmp_portal_light/lmp.html` を Xserver の `public_html/` に上書きアップロード。
アップロード後、**シークレットウィンドウ**で `https://lifemakepartners.net/lmp.html` を開き、
発行したID(またはメール)+パスワードでログインできることを確認します。

---

## 切り戻し（うまくいかない場合）

| 状況 | 対処 |
|---|---|
| ポータルにログインできない | Xserverに**旧 lmp.html**（`lmp.html.bak_20260716`）を戻す |
| SALESが不調 | `.env` の SSO 2行を削除 → `sudo systemctl restart lms`（従来動作に戻る） |
| コードを戻したい | `sudo git reset --hard <前のコミット>` → `sudo systemctl restart lms` |

---

## 残っている課題（この手順では解決しません）

1. **会計系6つ（Vercel）は別ドメイン**のため、まだSSOの対象外。
   `juchu.lifemakepartners.net` 等の独自ドメイン割当が必要。
2. **各ツールのログイン画面はまだ残っています。**
   各ツールに `GET /api/auth/me` の検証を組み込む改修が1本ずつ必要。
3. ポータル(lmp.html)は静的ファイルのため、**ページ自体の閲覧は誰でも可能**。
   ログインで守られるのは「各ツール」です。ページ自体も塞ぐならPHP等のゲートが別途必要。
