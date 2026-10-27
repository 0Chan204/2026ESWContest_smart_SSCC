# 보드 배포 (재실 + 행동추론 서버)

라즈베리파이 5 보드(LG ATLAS OS)에 `server/occupancy_server.py`를 Docker로 올리는 파일입니다.

| 파일 | 내용 |
| --- | --- |
| `Dockerfile` | `server/`를 담은 arm64 이미지. 모델(.pkl)과 같은 scikit-learn 1.9.0 사용 |
| `result_adapter.py` | 결과를 **1초에 1건**(백엔드 명세: 사람이 있는 방 하나, 없으면 room=null)으로 보내는 버전. 이미지에서 `server/result_adapter.py`를 덮어씀 |
| `compose.board.yaml` | 보드 실행 설정. 브로커 127.0.0.1, `--min-rate-ratio 0.5` |

```bash
# 맥 (ai-wifi-sensing 폴더에서)
docker build --platform linux/arm64 -f board/Dockerfile -t homevis-sensing:arm64 .
docker save homevis-sensing:arm64 | gzip | ssh root@<보드IP> 'gunzip | docker load'
ssh root@<보드IP> 'mkdir -p /mnt/rawopt/homevis-sensing && cat > /mnt/rawopt/homevis-sensing/compose.board.yaml' < board/compose.board.yaml

# 보드
cd /mnt/rawopt/homevis-sensing && docker compose -f compose.board.yaml up -d
```
