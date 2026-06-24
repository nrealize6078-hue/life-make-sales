@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ============================================================
echo   ライフメイクセールス を インターネット公開します
echo ============================================================
echo.
call .venv\Scripts\activate.bat

REM アプリ本体を別ウィンドウで起動
start "ライフメイクセールス(サーバー)" cmd /c "python -m uvicorn main:app --host 127.0.0.1 --port 8123"
echo サーバーを起動中...
timeout /t 4 > /dev/null

echo.
echo ============================================================
echo   ↓↓↓ この下に出る https://〇〇.trycloudflare.com が
echo        あなたの「公開URL」です（毎回変わります）
echo   ログインパスワードは .env の APP_PASSWORD です
echo   （公開をやめる時は、このウィンドウを閉じてください）
echo ============================================================
echo.
cloudflared.exe tunnel --url http://127.0.0.1:8123 --no-autoupdate
pause
