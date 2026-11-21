@echo off
REM ─────────────────────────────────────────────────────────────
REM Concurrency pilot — ONE CMD window = ONE person = ONE call
REM Copy this file, edit NAME / PHONE / LANG, run in its own CMD.
REM Open 2–8 CMDs with different phones. Wait ~1s between starts.
REM Prerequisites: call_server.py running, ngrok + SERVER_PUBLIC_URL,
REM   OPEN_DIALER=true, phones can receive Twilio calls.
REM ─────────────────────────────────────────────────────────────

set NAME=Tejas
set PHONE=+3374XXXXXXX
set LANG=en-IN

curl -X POST http://127.0.0.1:8000/call/outbound ^
  -H "Content-Type: application/json" ^
  -d "{\"to_number\":\"%PHONE%\",\"name\":\"%NAME%\",\"language\":\"%LANG%\"}"

echo.
echo Check capacity: curl http://127.0.0.1:8000/health
pause
