# HomeVIS 백엔드 이미지
# - 공식 python 이미지가 amd64/arm64를 모두 지원하므로 노트북(x86), 라즈베리파이 4·5, M 시리즈 맥에서 같은 Dockerfile로 빌드됩니다.
# - .env(비밀값)는 이미지에 넣지 않습니다. 실행할 때 docker compose가 env_file로 넣어줍니다.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/homevis

# 패키지 설치를 코드 복사보다 먼저 해서, 코드만 바뀌었을 때는 이 단계를 캐시로 건너뜁니다.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
# 가짜 인덕션(시뮬레이터)도 같은 이미지로 실행할 수 있게 함께 넣습니다.
COPY tests/simulate_device.py tests/simulate_home_devices.py ./tests/

# root가 아닌 계정으로 실행
RUN useradd --create-home --uid 10001 homevis
USER homevis

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
