# 🖥️ Xserver VPS に設置して「固定URL・24時間公開」する手順

このアプリ（Python製）を **Xserver VPS** に置き、いつも同じURLで・PCを切っても使える状態にします。
GitHubから自動でセットアップするスクリプトを用意しているので、**VPS上でコマンドを1つ実行するだけ**です。

---

## 事前準備（1回だけ）

### ① Xserver VPS の「パケットフィルター」でポートを開ける
Xserver VPS は初期状態で外部からの通信を絞っています。管理パネルで以下を許可してください。
- **Xserver VPSパネル** → 対象サーバー → **パケットフィルター設定**
- **「Web」**（80番・443番）を許可（または手動で TCP 80, 443 を追加）
- SSHを使う場合は **22番** も許可

---

## セットアップ（VPSにSSHログインして実行）

VPSのコンソール（またはSSHクライアント）でログインし、次の**1行**を貼り付けて実行します。

```bash
curl -fsSL https://raw.githubusercontent.com/nrealize6078-hue/life-make-sales/master/deploy_vps.sh -o deploy_vps.sh && sudo bash deploy_vps.sh
```

- 途中で「ログインパスワードを決めて入力してください」と聞かれるので、好きなパスワードを入力 → Enter。
- これだけで「依存導入 → アプリ取得 → 24時間常駐サービス化 → Web公開」まで自動で完了します。

完了すると最後に **`http://<あなたのVPSのIP>/`** が表示されます。
ブラウザでそのURLを開き、**ID: `admin` ／ パスワード: 先ほど決めたもの** でログインしてください。

---

## 使い方・運用

| やりたいこと | コマンド / 操作 |
|---|---|
| アクセスURL | `http://<VPSのIP>/`（IPは固定なので**ずっと同じURL**） |
| 最新コードに更新 | 同じ1行コマンドを再実行（`git pull`して自動再起動） |
| 起動状態の確認 | `systemctl status lms` |
| ログを見る | `journalctl -u lms -f` |
| 再起動 | `sudo systemctl restart lms` |
| 本物のAIを使う | `/opt/life-make-sales/.env` を編集（`DEMO_MODE=false`＋APIキー）→ `sudo systemctl restart lms` |

データ（`sales_tool.db`・音声）は VPS 内に保存され、更新（git pull）しても消えません。

---

## （任意）独自ドメイン＋HTTPS（鍵マーク付きURL）にする

「`http://IP`」ではなく「`https://app.あなたの会社.com`」のようにしたい場合：

1. **ドメインのDNS**で、使いたいサブドメイン（例 `app`）の **Aレコードを VPSのIPアドレス** に向ける
2. DNSが反映されたら、VPSで以下を実行（Ubuntuの例）：
   ```bash
   sudo apt-get install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d app.あなたの会社.com
   ```
   メール入力と規約同意 → 自動でHTTPS化（証明書は自動更新）。
3. 以後 **`https://app.あなたの会社.com`** が固定URLになります。

> ※エックスサーバーで取得したドメインのDNS（Aレコード）は、Xserverアカウントパネルの「DNS設定」から変更できます。

---

## こまったとき

- **URLが開けない** → Xserver VPSの「パケットフィルター」で80番が許可されているか確認
- **502エラー** → `systemctl status lms` でアプリが動いているか確認（`sudo systemctl restart lms`）
- **取得できない** → リポジトリが公開（public）になっているか確認

困ったら、表示されたエラーメッセージをそのまま伝えてください。一緒に解決します。
