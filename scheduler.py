"""
scheduler.py — Daily Outbound Call Scheduler for AI Sathi v9
=============================================================
Run alongside call_server.py:

    Terminal 1: python call_server.py
    Terminal 2: python scheduler.py

Uses TELEPHONY_PROVIDER from .env (exotel | frejun | twilio) via
call_server's shared /call/outbound endpoint.
"""

import os
import time
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
from colorama import Fore, Style, init

from core.console_utf8 import configure_console_utf8

load_dotenv()
configure_console_utf8()
init(autoreset=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("sathi_scheduler.log"),
    ],
)
log = logging.getLogger("sathi.scheduler")

SERVER_URL = os.getenv("SERVER_PUBLIC_URL", "http://localhost:8000")
TELEPHONY_PROVIDER = (os.getenv("TELEPHONY_PROVIDER") or "exotel").strip().lower()
CALL_INTERVAL_SEC = 30


def get_users_to_call(current_time_str: str) -> list:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core.database import get_all_active_users

    users = get_all_active_users()
    to_call = []
    try:
        from telephony.daily_calls import user_is_due
        for user in users:
            if user_is_due(user):
                to_call.append(user)
        return to_call
    except Exception:
        pass
    for user in users:
        call_time = user.get("call_time", "09:00")
        if call_time == current_time_str and user.get("phone"):
            to_call.append(user)
    return to_call


def trigger_call(user: dict) -> bool:
    name = user.get("name", "User")
    phone = user.get("phone", "")
    uid = user.get("id")

    if not phone:
        log.warning(f"No phone for user {name} (id={uid}) — skipping")
        return False

    try:
        resp = requests.post(
            f"{SERVER_URL.rstrip('/')}/call/outbound",
            json={"to_number": phone, "user_id": uid},
            timeout=15,
        )
        if resp.status_code == 200:
            log.info(f"✅ Call triggered via {TELEPHONY_PROVIDER} → {name} ({phone})")
            return True
        log.error(f"❌ Call failed for {name}: {resp.status_code} — {resp.text}")
        return False
    except requests.exceptions.ConnectionError:
        log.error(f"❌ Cannot reach call_server at {SERVER_URL}")
        log.error("   Make sure call_server.py is running first")
        return False
    except Exception as e:
        log.error(f"❌ Error triggering call for {name}: {e}")
        return False


def check_server_health() -> bool:
    try:
        resp = requests.get(f"{SERVER_URL.rstrip('/')}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def run_scheduler():
    print(f"\n{Fore.BLUE}{'═'*55}")
    print(f"  ⏰  AI Sathi Scheduler v9")
    print(f"  Provider: {TELEPHONY_PROVIDER}")
    print(f"  Call server: {SERVER_URL}")
    print(f"{'═'*55}{Style.RESET_ALL}\n")

    print(f"{Fore.YELLOW}Waiting for call_server to start...{Style.RESET_ALL}")
    for i in range(30):
        if check_server_health():
            print(f"{Fore.GREEN}✅ Call server is running{Style.RESET_ALL}\n")
            break
        time.sleep(2)
        if i % 5 == 4:
            print(f"  Still waiting... ({(i+1)*2}s)")
    else:
        print(f"{Fore.RED}❌ Call server not reachable at {SERVER_URL}")
        print(f"   Start it first: python call_server.py{Style.RESET_ALL}")
        return

    last_checked_minute = ""
    print(f"{Fore.CYAN}Scheduler running. Ctrl+C to stop.{Style.RESET_ALL}\n")

    while True:
        now = datetime.now()
        minute_str = now.strftime("%H:%M")

        if minute_str != last_checked_minute:
            last_checked_minute = minute_str
            log.info(f"Checking for calls at {minute_str}...")

            users_to_call = get_users_to_call(minute_str)
            if users_to_call:
                log.info(f"Found {len(users_to_call)} user(s) to call at {minute_str}")
                for user in users_to_call:
                    trigger_call(user)
                    time.sleep(CALL_INTERVAL_SEC)
            else:
                log.debug(f"No calls scheduled at {minute_str}")

        time.sleep(15)


if __name__ == "__main__":
    try:
        run_scheduler()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Scheduler stopped.{Style.RESET_ALL}\n")
