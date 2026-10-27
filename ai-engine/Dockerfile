# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOMEVIS_DATA_DIR=/data \
    HOME=/data \
    TZ=Asia/Seoul
WORKDIR /app

# Offline WAV generation; backend v0.7 voice playback still belongs to the backend.
RUN apt-get update \
    && apt-get install -y --no-install-recommends espeak-ng libespeak1 libsndfile1 ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 homevis \
    && useradd --uid 10001 --gid homevis --home-dir /data --no-create-home homevis \
    && mkdir /data && chown homevis:homevis /data

COPY requirements-arm64.txt ./
RUN pip install --no-cache-dir -r requirements-arm64.txt
COPY src/ ./src/
COPY config/homevis.toml config/decision_policy.toml ./config/

USER 10001:10001
VOLUME ["/data"]
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-m", "src.integration", "--healthcheck"]
ENTRYPOINT ["python", "-m", "src.integration"]
