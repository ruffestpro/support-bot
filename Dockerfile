FROM python:3.12-slim-bookworm

WORKDIR /usr/src/app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .

# Длинный таймаут и повторы — при медленном/нестабильном канале до pypi.org
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt

COPY . .