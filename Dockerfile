# Voice TTS server for a headless Linux box: the HTTP API and the web page, no window.
#
#   docker compose up -d --build      # see compose.yaml; token from .env
#
# The model is not baked in: the first start downloads it into the /data/hf
# volume (needs internet once), later starts load it from there. The user's
# lexicon lives in the /data/app volume, so a rebuild keeps it.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/data/hf \
    VOICE_TTS_DATA=/data/app

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py cli.py icon.py lexicon.py respell.py ./
COPY web ./web

# Run unprivileged; the volume mount point must already belong to that user,
# or a fresh named volume comes up root-owned and the download fails.
RUN useradd --create-home --uid 1000 voicetts \
    && mkdir -p /data/hf /data/app \
    && chown -R voicetts:voicetts /data
USER voicetts
VOLUME ["/data/hf", "/data/app"]

EXPOSE 8760

# `status` exits 0 only once the model is ready; it reads VOICE_TTS_TOKEN itself.
# The start period covers the first model download.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15m --retries=3 \
    CMD ["python", "cli.py", "status", "--server", "http://127.0.0.1:8760", "--timeout", "5"]

ENTRYPOINT ["python", "cli.py"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8760"]
