# -*- coding: utf-8 -*-
"""アカウント管理CLI（横断ログイン / SSO 用）

VPS上での実行例:
    cd /opt/life-make-sales
    .venv/bin/python manage_accounts.py list
    .venv/bin/python manage_accounts.py add --id LMP-ADMIN --role hq   --name "LMP本部"
    .venv/bin/python manage_accounts.py add --id LMP-0001  --role company --name "加盟店A" --company "加盟店A" --email a@example.com
    .venv/bin/python manage_accounts.py add --id emp001    --role member  --name "山田太郎" --company "加盟店A"
    .venv/bin/python manage_accounts.py reset --id LMP-0001
    .venv/bin/python manage_accounts.py disable --id LMP-0005

ロール:
    hq      … LMP本部（全会社・全データ。管理操作可）
    company … 加盟店（自社のみ）
    member  … 社員（自分のデータのみ）

パスワードは指定しなければ強いものを自動生成し、画面に1度だけ表示します（DBにはハッシュのみ保存）。
"""
import argparse
import secrets
import string
import sys

sys.stdout.reconfigure(errors="replace")

import database as db
import auth


def gen_password(n: int = 14) -> str:
    """紛らわしい文字（0/O/1/l/I）を除いた強いパスワードを生成する。"""
    alphabet = "".join(c for c in (string.ascii_letters + string.digits) if c not in "0O1lI")
    return "".join(secrets.choice(alphabet) for _ in range(n)) + secrets.choice("!@#$%&*")


def find_or_create_company(name: str):
    if not name:
        return None
    conn = db.get_conn()
    try:
        r = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()
        if r:
            return r["id"]
        from datetime import datetime
        cur = conn.execute(
            "INSERT INTO companies (name, created_at) VALUES (?,?)",
            (name, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        print(f"  会社を新規作成: {name} (id={cur.lastrowid})")
        return cur.lastrowid
    finally:
        conn.close()


def cmd_list(_args):
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT u.id, u.username, u.display_name, u.role, u.active, u.email, c.name AS company "
            "FROM users u LEFT JOIN companies c ON u.company_id=c.id ORDER BY u.id"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("アカウントは1件もありません。")
        return
    print(f"{'ID':<14}{'ロール':<9}{'状態':<5}{'会社':<16}{'メール':<26}表示名")
    print("-" * 90)
    for r in rows:
        role = {"hq": "本部", "company": "会社", "member": "社員", "admin": "本部(旧)"}.get(r["role"], r["role"])
        print(f"{r['username']:<14}{role:<9}{'有効' if r['active'] else '停止':<5}"
              f"{(r['company'] or '-'):<16}{(r['email'] or '-'):<26}{r['display_name'] or ''}")


def cmd_add(args):
    company_id = find_or_create_company(args.company)
    pw = args.password or gen_password()
    try:
        auth.create_user(args.id, pw, role=args.role, display_name=args.name or args.id,
                         email=args.email or "", company_id=company_id)
    except ValueError as e:
        print(f"エラー: {e}")
        sys.exit(1)
    print("\n=== 作成しました（このパスワードは今しか表示されません）===")
    print(f"  ID       : {args.id}")
    if args.email:
        print(f"  メール   : {args.email}  （ID・メールどちらでもログインできます）")
    print(f"  パスワード: {pw}")
    print(f"  ロール   : {args.role}" + (f" / 会社: {args.company}" if args.company else ""))


def cmd_reset(args):
    u = auth.get_user_by_name(args.id)
    if not u:
        print(f"エラー: {args.id} が見つかりません")
        sys.exit(1)
    pw = args.password or gen_password()
    auth.set_password(u["id"], pw)   # 既存セッションも失効する
    print("\n=== パスワードを再発行しました（今しか表示されません）===")
    print(f"  ID       : {u['username']}")
    print(f"  パスワード: {pw}")
    print("  ※この利用者の既存ログインは全て無効になりました。")


def cmd_companies(_args):
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT c.id, c.name, (SELECT COUNT(*) FROM users u WHERE u.company_id=c.id) AS n "
            "FROM companies c ORDER BY c.id"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("会社は1件もありません。")
        return
    print(f"{'ID':<5}{'利用者数':<9}会社名")
    print("-" * 50)
    for r in rows:
        print(f"{r['id']:<5}{r['n']:<9}{r['name']}")


def cmd_delete(args):
    """アカウントを完全に削除する（IDを再利用できるようにする）。"""
    u = auth.get_user_by_name(args.id)
    if not u:
        print(f"エラー: {args.id} が見つかりません")
        sys.exit(1)
    conn = db.get_conn()
    try:
        others = 0
        if u.get("company_id"):
            others = conn.execute(
                "SELECT COUNT(*) FROM users WHERE company_id=? AND id<>?", (u["company_id"], u["id"])
            ).fetchone()[0]
        conn.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))
        conn.execute("DELETE FROM users WHERE id=?", (u["id"],))
        conn.commit()
        print(f"{args.id} を削除しました。このIDは再度使えます。")
        if u.get("company_id") and others == 0:
            r = conn.execute("SELECT name FROM companies WHERE id=?", (u["company_id"],)).fetchone()
            if r:
                print(f'\n※ 会社「{r["name"]}」に利用者がいなくなりました。')
                print(f'   間違って作った会社なら、次で削除できます:')
                print(f'   .venv/bin/python manage_accounts.py company-delete --name "{r["name"]}"')
    finally:
        conn.close()


def cmd_company_delete(args):
    """会社を削除する。利用者や取引データが残っている場合は中止する（安全側）。"""
    conn = db.get_conn()
    try:
        r = conn.execute("SELECT id FROM companies WHERE name=?", (args.name,)).fetchone()
        if not r:
            print(f"エラー: 会社「{args.name}」が見つかりません")
            sys.exit(1)
        cid = r["id"]
        n = conn.execute("SELECT COUNT(*) FROM users WHERE company_id=?", (cid,)).fetchone()[0]
        if n:
            print(f"中止: この会社には利用者が {n} 人います。先にアカウントを削除してください。")
            sys.exit(1)
        for t in ("contacts", "deals", "meetings"):
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE company_id=?", (cid,)).fetchone()[0]
            except Exception:
                continue
            if cnt:
                print(f"中止: {t} に {cnt} 件の関連データがあります。誤削除を防ぐため中止しました。")
                sys.exit(1)
        conn.execute("DELETE FROM companies WHERE id=?", (cid,))
        conn.commit()
        print(f"会社「{args.name}」を削除しました。")
    finally:
        conn.close()


def cmd_disable(args):
    u = auth.get_user_by_name(args.id)
    if not u:
        print(f"エラー: {args.id} が見つかりません")
        sys.exit(1)
    auth.update_user(u["id"], active=0)
    print(f"{args.id} を停止しました（ログインできなくなります）。")


def main():
    p = argparse.ArgumentParser(description="LMP アカウント管理（横断ログイン用）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="アカウント一覧").set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="アカウント追加")
    a.add_argument("--id", required=True, help="ログインID（例: LMP-0001）")
    a.add_argument("--role", required=True, choices=["hq", "company", "member"])
    a.add_argument("--name", default="", help="表示名")
    a.add_argument("--company", default="", help="所属会社名（無ければ自動作成）")
    a.add_argument("--email", default="", help="メールアドレス（これでもログイン可）")
    a.add_argument("--password", default="", help="未指定なら自動生成（推奨）")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("reset", help="パスワード再発行")
    r.add_argument("--id", required=True)
    r.add_argument("--password", default="")
    r.set_defaults(func=cmd_reset)

    d = sub.add_parser("disable", help="アカウント停止（IDは残る）")
    d.add_argument("--id", required=True)
    d.set_defaults(func=cmd_disable)

    x = sub.add_parser("delete", help="アカウント完全削除（IDを再利用できる）")
    x.add_argument("--id", required=True)
    x.set_defaults(func=cmd_delete)

    sub.add_parser("companies", help="会社一覧").set_defaults(func=cmd_companies)

    cd = sub.add_parser("company-delete", help="会社削除（利用者・取引データが無い場合のみ）")
    cd.add_argument("--name", required=True)
    cd.set_defaults(func=cmd_company_delete)

    args = p.parse_args()
    db.init_db()
    args.func(args)


if __name__ == "__main__":
    main()
