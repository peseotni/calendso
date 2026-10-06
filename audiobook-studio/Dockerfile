# syntax=docker/dockerfile:1
#
# Audiobook Studio – self-hosted audiobook creation suite
#
#   docker build -t audiobook-studio .
#   docker run -d -p 8000:8000 -v ./data:/data -v ./audiobooks:/audiobooks audiobook-studio
#
# Build arguments:
#   OCR_LANGS  space separated Tesseract language packs for scanned PDFs
#              (e.g. "eng deu fra"), empty to skip OCR support entirely.

# ---------------------------------------------------------------- web UI build
FROM node:22-bookworm-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- runtime
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG OCR_LANGS="eng"

RUN set -eux; \
    ocr_packages=""; \
    for lang in ${OCR_LANGS}; do ocr_packages="$ocr_packages tesseract-ocr-$lang"; done; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        python3 python3-venv ca-certificates tini ffmpeg espeak-ng \
        $( [ -n "${OCR_LANGS}" ] && echo "tesseract-ocr $ocr_packages" ); \
    rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY backend/requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv && pip install -r /app/requirements.txt

COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/audiobook_studio /app/audiobook_studio
COPY --from=frontend /src/dist /app/audiobook_studio/static
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && python -m compileall -q /app/audiobook_studio

WORKDIR /app
ENV STUDIO_DATA_DIR=/data \
    STUDIO_LIBRARY_DIR=/audiobooks \
    STUDIO_HOST=0.0.0.0 \
    STUDIO_PORT=8000

EXPOSE 8000
VOLUME ["/data", "/audiobooks"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"STUDIO_PORT\", \"8000\")}/api/health', timeout=4)" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "audiobook_studio"]
