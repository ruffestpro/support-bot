FROM python:3.12-slim-bookworm

WORKDIR /usr/src/app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# На проде с плохим маршрутом до pypi.org: docker compose build --build-arg PIP_INDEX_URL=https://...
ARG PIP_INDEX_URL=https://pypi.org/simple
# Для зеркала по HTTP добавьте --trusted-host вручную или используйте HTTPS-зеркало
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

COPY requirements.txt .

RUN pip install --no-cache-dir --retries 15 --timeout 180 \
    -i "${PIP_INDEX_URL}" \
    -r requirements.txt

COPY . .