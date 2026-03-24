FROM python:3.12-slim-bookworm

WORKDIR /usr/src/app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .

# Индекс: в compose по умолчанию зеркало (см. docker-compose), иначе часто таймауты до files.pythonhosted.org
ARG PIP_INDEX_URL=https://pypi.org/simple
# setuptools нужен для pkg_resources в APScheduler 3.10; отдельный pip + проверка — гарантия в slim-образе
RUN pip install --no-cache-dir --retries 25 --timeout 600 \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    --trusted-host mirrors.aliyun.com \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    -i "${PIP_INDEX_URL}" \
    -r requirements.txt && \
    pip install --no-cache-dir --force-reinstall --retries 10 --timeout 600 \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    --trusted-host mirrors.aliyun.com \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    -i "${PIP_INDEX_URL}" \
    "setuptools>=69.0.0,<81.0.0" && \
    python -c "import pkg_resources; print('pkg_resources: ok')"

COPY . .