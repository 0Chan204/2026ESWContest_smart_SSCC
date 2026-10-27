#!/usr/bin/env bash
# HomeVIS 대회장 시연 — 맥북 + 외장 13.3" 터치 모니터
#
#   ./demo.sh            기본: 확대 67%, 창을 본체 화면에 띄움 (드래그 → ⌃⌘F)
#   ./demo.sh 0.75       확대율 지정 (숫자가 클수록 글씨가 큼)
#   ./demo.sh auto       외장 모니터에 맞춰 확대율 자동 계산 (CSS 가로 1280 기준)
#   ./demo.sh 0.67 ext   창을 외장 모니터로 바로 보냄 (외장이 본체 왼쪽에 있다고 가정)
set -euo pipefail
cd "$(dirname "$0")"

SCALE_ARG="${1:-0.67}"     # 숫자 | auto
WHERE="${2:-main}"         # main(본체에 띄우고 드래그) | ext(외장으로 바로)
URL="http://127.0.0.1:4173/home"
PROFILE="$HOME/.homevis-demo-profile"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

[[ -x "$CHROME" ]] || { echo "Chrome 을 찾을 수 없습니다: $CHROME"; exit 1; }

cleanup() {
  echo ""
  echo "시연 종료 — 서버와 절전 방지를 내립니다."
  [[ -n "${PREVIEW_PID:-}" ]] && kill "$PREVIEW_PID" 2>/dev/null || true
  [[ -n "${CAFFEINE_PID:-}" ]] && kill "$CAFFEINE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "1/5  빌드"
npm run build >/dev/null

echo "2/5  로컬 서버 기동 (127.0.0.1:4173)"
npm run preview >/tmp/homevis-demo.log 2>&1 &
PREVIEW_PID=$!
for _ in {1..40}; do curl -sf -o /dev/null "$URL" && break; sleep 0.25; done
curl -sf -o /dev/null "$URL" || { echo "서버 기동 실패 — /tmp/homevis-demo.log 확인"; exit 1; }

echo "3/5  화면 절전 방지"
caffeinate -d & CAFFEINE_PID=$!

echo -n "4/5  인터넷 연결 확인 (음성 인식에 필요) ... "
if curl -sf -o /dev/null --max-time 4 https://www.google.com/generate_204; then
  echo "연결됨 — 실제 음성 인식 가능"
else
  echo "끊김 ⚠  실제 음성 인식 불가 → 설정에서 음성을 끄고 데모 모드로 진행하세요"
fi

# ── 외장 모니터 감지 ──────────────────────────────────────────────────────
# macOS 가 외장을 HiDPI 로 잡으면 '논리 해상도'가 실제보다 작다. 창 크기는 논리값 기준.
read -r EXT_W EXT_H < <(python3 <<'PYEOF'
import json, re, subprocess
# system_profiler 만 사용한다. Finder/AppleScript 를 쓰지 않으므로 권한 요청이 없다.
ext = None
try:
    d = json.loads(subprocess.run(["system_profiler","-json","SPDisplaysDataType"],
                                  capture_output=True, text=True, timeout=20).stdout)
    for gpu in d.get("SPDisplaysDataType", []):
        for m in gpu.get("spdisplays_ndrvs", []):
            if m.get("spdisplays_main") == "spdisplays_yes":
                continue
            r = m.get("_spdisplays_resolution") or m.get("spdisplays_resolution") or ""
            n = re.findall(r"(\d+)\s*x\s*(\d+)", r)
            if n:
                ext = (int(n[0][0]), int(n[0][1]))
except Exception:
    pass
print(ext[0] if ext else 0, ext[1] if ext else 0)
PYEOF
)

if [[ "${EXT_W:-0}" -gt 0 ]]; then
  if [[ "$SCALE_ARG" == "auto" ]]; then
    SCALE=$(python3 -c "print(round($EXT_W/1280, 4))")
  else
    SCALE="$SCALE_ARG"
  fi
  if [[ "$WHERE" == "ext" ]]; then
    GEOM="--window-position=-${EXT_W},0 --window-size=${EXT_W},${EXT_H}"
    PLACE="외장 모니터"
  else
    GEOM="--window-position=40,40 --window-size=${EXT_W},${EXT_H}"
    PLACE="본체 화면 (드래그해서 옮기세요)"
  fi
  echo "     외장 감지: 논리 ${EXT_W}x${EXT_H} · 확대 ${SCALE} → CSS $(python3 -c "print(int($EXT_W/$SCALE), 'x', int($EXT_H/$SCALE))") · 창 위치: ${PLACE}"
else
  SCALE=$([[ "$SCALE_ARG" == "auto" ]] && echo 1.0 || echo "$SCALE_ARG")
  GEOM="--window-size=1280,760 --window-position=60,60"
  echo "     외장 모니터 미감지 — 본체 화면에 창 모드로 엽니다"
fi

# 페이지 확대율을 프로필에 미리 기록 (Chrome 이 꺼져 있는 지금만 가능)
# 강제 배율(--force-device-scale-factor)은 글자를 뭉개므로 쓰지 않는다.
python3 - "$PROFILE" "$SCALE" <<'PYEOF'
import json, math, os, sys
profile, scale = sys.argv[1], float(sys.argv[2])
pref = os.path.join(profile, "Default", "Preferences")
if not os.path.exists(pref):
    sys.exit(0)
level = math.log(scale) / math.log(1.2)
try:
    d = json.load(open(pref, encoding="utf8"))
    hosts = {h: {"zoom_level": level} for h in ("127.0.0.1", "localhost")}
    part = d.setdefault("partition", {}).setdefault("per_host_zoom_levels", {})
    for key in set(part) | {"0"}:
        part[key] = hosts
    json.dump(d, open(pref, "w", encoding="utf8"))
    print(f"     페이지 확대율 {round(scale*100)}% 기록 완료")
except Exception as e:
    print("     확대율 자동 설정 실패 — Chrome 에서 ⌘- 로 맞추세요:", e)
PYEOF

echo "5/5  Chrome 시연 창 열기"
"$CHROME" \
  --user-data-dir="$PROFILE" \
  --app="$URL" \
  $GEOM \
  --no-first-run --no-default-browser-check --no-service-autorun \
  --disable-features=Translate,AutofillServerCommunication \
  --disable-session-crashed-bubble --disable-infobars \
  --lang=ko-KR >/dev/null 2>&1 &

cat <<'TIP'

──────────────────────────────────────────────────────────
  창을 왼쪽 외장 모니터로 드래그 → ⌃⌘F 전체화면
  확대 조정  ⌘+ / ⌘-        시연 도구  좌측 하단 '시연'
  종료       이 터미널에서 Ctrl+C
──────────────────────────────────────────────────────────
TIP

wait $PREVIEW_PID
