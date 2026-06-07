@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ============================================
echo   ライフメイクセールス (Life Make Sales) を起動します
echo ============================================
echo.

REM 仮想環境がなければ作成
if not exist ".venv\" (
    echo [初回セットアップ] Python仮想環境を作成中...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo [初回セットアップ] 必要なライブラリをインストール中...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

echo.
echo ブラウザで http://127.0.0.1:8123 を開いてください
echo （終了するにはこのウィンドウで Ctrl+C を押します）
echo.

REM 既定ブラウザを自動で開く
start "" http://127.0.0.1:8123

python -m uvicorn main:app --host 127.0.0.1 --port 8123

pause
