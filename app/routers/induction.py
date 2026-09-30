"""
[DEPRECATED] v0.2 API 명세 반영으로 이 라우터는 더 이상 사용되지 않습니다.

기존 기능은 다음으로 이전되었습니다:
- GET  /induction/{device_id}/state        -> GET  /api/v1/devices/{device_id}/telemetry  (app/routers/device.py)
- POST /induction/{device_id}/control      -> POST /api/v1/appliances/{id}/burners/{burnerId}/commands (app/routers/dashboard.py)
- GET  /induction/{device_id}/last-command -> GET  /api/v1/commands/{commandId}            (app/routers/dashboard.py)

main.py에서도 더 이상 이 모듈을 import하지 않습니다. 파일이 남아있는 이유는
이 작업 환경에서 파일 삭제 권한이 없어서입니다 - 안전하게 지워도 되는 파일이니
직접 삭제하셔도 됩니다.
"""
