"""
call_server.py — AI Sathi Phone Bridge (Exotel + FreJun + Twilio)
=================================================================
Run: python call_server.py

Switch provider in .env:
  TELEPHONY_PROVIDER=exotel | frejun | twilio

Exotel endpoints:
  WS   /call/audio
  POST /call/status
  POST /call/outbound

FreJun Teler endpoints:
  POST /frejun/flow
  POST /frejun/webhook
  WS   /frejun/media-stream
  POST /call/outbound

Twilio Media Streams endpoints:
  POST /twilio/voice
  POST /twilio/status
  WS   /twilio/media-stream
  POST /call/outbound

Shared:
  GET  /health
"""

from telephony.app import app
from telephony.config import SERVER_PORT

if __name__ == "__main__":
    import os
    import socket
    import sys

    import uvicorn
    from colorama import Fore, Style

    # Render / cloud inject PORT; prefer it when SERVER_PORT was left at default.
    port = int(os.getenv("PORT") or SERVER_PORT or 8000)

    # Fail fast with a clear message if port is taken (common Windows issue)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError:
        print(
            f"\n{Fore.RED}❌ Port {port} is already in use.\n"
            f"   Close the other app (old call_server / python) then retry.\n"
            f"   Or run:  netstat -ano | findstr :{port}{Style.RESET_ALL}\n"
        )
        sys.exit(1)
    finally:
        sock.close()

    uvicorn.run(
        "call_server:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=10,
    )
