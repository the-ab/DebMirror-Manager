FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

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
COPY app/repository/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock

COPY app /app/app
COPY README.md RELEASE_NOTES.md VERSION /app/
COPY app/repository/LICENSE app/repository/THIRD-PARTY-NOTICES.md /app/
COPY app/docs/README.de.md app/docs/RELEASE_NOTES.de.md /app/

RUN mkdir -p /app/data /app/logs /app/keyrings /import-scripts /mirror

EXPOSE 8080
CMD ["gunicorn", "--config", "/app/app/gunicorn.conf.py", "app.main:app"]
