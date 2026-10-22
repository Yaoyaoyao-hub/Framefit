FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    YOLO_CACHE_DIR=/data/models \
    LOCAL_STORAGE_DIR=/data/assets \
    DATABASE_URL=sqlite:////data/framefit.db

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app

RUN mkdir -p /data/assets /data/models
VOLUME ["/data"]

EXPOSE 8000

# One process. Multiple workers would load the model twice and fight over SQLite.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
