FROM python:3.12-slim-bookworm

WORKDIR /usr/src/app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .

# ARG после COPY: индекс PyPI только на этапе pip (без ENV — меньше путаницы со сборщиками)
# Сборка: docker compose build --build-arg PIP_INDEX_URL=https://...
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --retries 15 --timeout 180 \
    -i "$PIP_INDEX_URL" \
    -r requirements.txt

COPY . .