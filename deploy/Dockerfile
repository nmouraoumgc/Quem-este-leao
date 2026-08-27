FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 fonts-liberation \
        tesseract-ocr tesseract-ocr-por tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt pyproject.toml README.md LICENSE schema.sql ./
COPY src ./src
COPY data ./data
COPY assets ./assets
COPY deploy ./deploy

RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -e .

ENV QEEL_TIMEZONE=Europe/Lisbon \
    QEEL_DRY_RUN=true \
    QEEL_DATABASE_PATH=/app/var/quem-e-este-leao.sqlite3 \
    QEEL_OUTPUT_DIR=/app/var/output \
    QEEL_PREVIEW_DIR=/app/examples \
    PYTHONUNBUFFERED=1

RUN mkdir -p /app/var /app/examples
VOLUME ["/app/var", "/app/examples"]

ENTRYPOINT ["quem-e-este-leao"]
CMD ["serve-scheduler"]
