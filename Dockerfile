# ライフメイクセールス 本番用イメージ
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# アプリ本体
COPY . .

# 永続データ(SQLite / アップロード音声)— 実運用では /data に volume をマウント
ENV DATABASE_PATH=/data/sales_tool.db \
    UPLOAD_DIR=/data/uploads
RUN mkdir -p /data/uploads
VOLUME ["/data"]

EXPOSE 8123

# クラウドは PORT 環境変数を注入する。無ければ 8123。
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8123}"]
