@echo off
chcp 65001 >nul
rem HomeVIS 시연 실행 (Windows)
rem  - 빌드 후 이 PC 안에서만 열리는 미리보기 서버(127.0.0.1:4173)를 띄우고
rem    Chrome(없으면 Edge)을 주소창 없는 앱 창 · 전체 화면으로 연다.
rem  - 시스템 설정은 바꾸지 않는다. 화면 꺼짐은 웹앱이 스스로 막는다(Wake Lock).
rem  - 끄기: 앱 창을 닫고, 작업 표시줄의 "HomeVIS server" 창을 닫는다.
rem 사용: demo.cmd            전체 화면
rem       demo.cmd window     창 모드
setlocal
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
  echo [HomeVIS] Node.js 가 필요합니다. https://nodejs.org 에서 LTS 버전을 설치한 뒤 다시 실행해 주세요.
  pause
  exit /b 1
)

if not exist node_modules (
  echo [HomeVIS] 처음 실행 - 패키지를 설치합니다...
  call npm ci --no-audit --no-fund
  if errorlevel 1 goto :fail
)

echo [HomeVIS] 빌드 중...
call npm run build
if errorlevel 1 goto :fail

rem 이미 4173 포트를 쓰는 서버가 있으면 그대로 쓴다
netstat -ano | findstr /r /c:"127.0.0.1:4173 .*LISTENING" >nul
if errorlevel 1 (
  start "HomeVIS server" /min cmd /c "npm run preview"
  timeout /t 3 /nobreak >nul
)

set "BROWSER="
for %%P in (
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
  "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
) do if not defined BROWSER if exist %%P set "BROWSER=%%~P"

if not defined BROWSER (
  echo [HomeVIS] Chrome/Edge 를 찾지 못했습니다. 브라우저에서 http://127.0.0.1:4173 을 직접 열어 주세요.
  pause
  exit /b 0
)

set "VIEW=--start-fullscreen"
if /i "%~1"=="window" set "VIEW=--window-size=1440,900"

rem 시연 전용 프로필 폴더 - 평소 브라우저의 로그인·기록과 섞이지 않는다
start "" "%BROWSER%" --user-data-dir="%LocalAppData%\homevis-demo-profile" --no-first-run --no-default-browser-check %VIEW% --app=http://127.0.0.1:4173/
echo [HomeVIS] 실행했습니다. 전체 화면 해제: F11 / 확대·축소: Ctrl + 마우스 휠
exit /b 0

:fail
echo [HomeVIS] 실패했습니다. 위 메시지를 확인해 주세요.
pause
exit /b 1
