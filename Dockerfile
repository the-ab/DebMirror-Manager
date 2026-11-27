FROM python:3.13.18-slim-trixie@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50

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
    && apt-get upgrade -y \
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
        iputils-ping \
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
# pip is only needed to install the locked dependencies during the build.
RUN python -m pip install --no-cache-dir --require-hashes -r /app/requirements.lock \
    && python -m pip uninstall --yes pip \
    && rm -f /usr/local/lib/python3.13/ensurepip/_bundled/pip-*.whl

COPY app /app/app
COPY README.md RELEASE_NOTES.md VERSION /app/
COPY app/repository/LICENSE app/repository/THIRD-PARTY-NOTICES.md /app/
COPY app/docs/README.de.md app/docs/RELEASE_NOTES.de.md /app/

RUN mkdir -p /app/data /app/logs /app/keyrings /import-scripts /mirror

EXPOSE 8080
CMD ["gunicorn", "--config", "/app/app/gunicorn.conf.py", "app.main:app"]
