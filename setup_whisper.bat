@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ============================================
echo   ローカル文字起こし環境(whisper_venv)を作成します
echo   ※無料・キー不要でPC内文字起こしを使うための任意セットアップ
echo ============================================
echo.

if exist "whisper_venv\" (
    echo whisper_venv は既に存在します。再作成する場合は手動で削除してください。
    pause
    exit /b
)

REM Python 3.9〜3.12 を探す（faster-whisper は 3.14 では動かないため）
set "PYEXE="
for %%V in (3.12 3.11 3.10 3.9) do (
    if not defined PYEXE (
        py -%%V --version >nul 2>&1 && set "PYEXE=py -%%V"
    )
)
if not defined PYEXE (
    echo [エラー] Python 3.9〜3.12 が見つかりませんでした。
    echo          python.org から 3.12 などを入れてから再実行してください。
    pause
    exit /b
)

echo 使用するPython: %PYEXE%
%PYEXE% -m venv whisper_venv
call whisper_venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-whisper.txt

echo.
echo 完了しました。.env で LOCAL_WHISPER=true にすると有効になります。
pause
