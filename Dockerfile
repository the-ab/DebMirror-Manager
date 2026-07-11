FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_PORT=8080 \
    APP_TIMEZONE=Europe/Berlin \
    TZ=Europe/Berlin \
    APP_DATA_DIR=/app/data \
    APP_LOG_DIR=/app/logs \
    APP_KEYRING_DIR=/app/keyrings \
    IMPORT_SCRIPT_DIR=/import-scripts \
    MIRROR_BASE=/mirror

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        debmirror \
        gpgv \
        gnupg \
        dirmngr \
        patch \
        ed \
        gzip \
        lftp \
        lz4 \
        rsync \
        openssh-client \
        xz-utils \
        bzip2 \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY README.md RELEASE_NOTES.md VERSION /app/

RUN mkdir -p /app/data /app/logs /app/keyrings /import-scripts /mirror

EXPOSE 8080
CMD ["python", "-m", "app.main"]
