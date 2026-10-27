# 지우님 재실 + 행동추론 서버 (HomeVIS-AI_Wifi/server) 보드용 이미지
# 빌드 (ai-wifi-sensing 폴더에서): docker build --platform linux/arm64 -f board/Dockerfile -t homevis-sensing:arm64 .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Seoul
WORKDIR /app

# 모델(.pkl)을 만든 scikit-learn 1.9.0과 같은 버전을 씁니다 (RUN_GUIDE 2장)
RUN pip install paho-mqtt numpy scipy pandas scikit-learn==1.9.0 tzdata

COPY server/ /app/
# 결과를 백엔드 명세대로 1초에 1건 보내는 버전으로 덮어씀 (대시보드·AI 판정 엔진이 최신 1건을 집 전체 위치로 읽음)
COPY board/result_adapter.py /app/result_adapter.py

# 브로커는 보드의 mosquitto (host 네트워크라 127.0.0.1)
CMD ["python", "occupancy_server.py", "--broker", "127.0.0.1", \
     "--combined-topic", "home/edge/combined", "--result-topic", "home/edge/result", \
     "--log-dir", "/app/logs"]
