"""
dashboard.py — CLI dashboard to view all saved data
Run: python -m core.dashboard   OR   python core/dashboard.py

Shows:
- All conversations
- Health records with trends
- API costs
- Alert history
"""

import os
import sys

from colorama import Fore, Style, init
from dotenv import load_dotenv
from sqlalchemy import select
from tabulate import tabulate

# Allow `python core/dashboard.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import (
    check_alert_needed,
    get_default_user,
    get_recent_records,
    get_session_factory,
    get_total_cost_summary,
)
from core.models import Alert, Conversation

load_dotenv()
init(autoreset=True)


def _as_dict(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


def show_recent_conversations(user_id, limit=20):
    with get_session_factory()() as s:
        rows = list(s.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(limit)
        ).all())

    if not rows:
        print(f"  {Fore.YELLOW}No conversations yet.{Style.RESET_ALL}")
        return

    print(f"\n  {Fore.CYAN}Last {limit} conversation turns:{Style.RESET_ALL}\n")
    for r in reversed(rows):
        time_str = r.created_at.strftime("%d %b %H:%M") if r.created_at else "?"
        role_str = (f"{Fore.GREEN}🤖 Sathi" if r.role == "sathi"
                    else f"{Fore.BLUE}👤 User ")
        msg = r.message[:80] + "..." if len(r.message) > 80 else r.message
        print(f"  {time_str}  {role_str}:{Style.RESET_ALL} {msg}")


def show_health_records(user_id, days=14):
    records = get_recent_records(user_id, days)
    if not records:
        print(f"  {Fore.YELLOW}No health records yet.{Style.RESET_ALL}")
        return

    print(f"\n  {Fore.CYAN}Health Records — Last {days} days:{Style.RESET_ALL}\n")
    rows = []
    for r in records:
        bp = (f"{r['bp_systolic']}/{r['bp_diastolic']}"
              if r.get("bp_systolic") else "—")
        recorded = r["recorded_at"]
        time_str = recorded.strftime("%d %b %H:%M") if recorded else "?"
        rows.append([
            time_str,
            bp,
            r.get("sugar_fasting") or "—",
            r.get("sleep_quality") or "—",
            r.get("food_intake") or "—",
            r.get("mood") or "—",
            "⚠️" if r.get("dizziness") else "✅",
            "⚠️" if r.get("chest_discomfort") else "✅",
        ])
    headers = ["Date/Time", "BP", "Sugar", "Sleep", "Food", "Mood", "Dizzy", "Chest"]
    print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))


def show_vitals_trend(user_id):
    records = get_recent_records(user_id, days=14)
    bp_records = [r for r in records if r.get("bp_systolic")]
    sg_records = [r for r in records if r.get("sugar_fasting")]

    if bp_records:
        print(f"\n  {Fore.CYAN}BP Trend (Systolic):{Style.RESET_ALL}")
        values = [r["bp_systolic"] for r in reversed(bp_records)]
        trend = " → ".join(str(v) for v in values)
        direction = ("⬆️ Rising" if values[-1] > values[0]
                     else "⬇️ Falling" if values[-1] < values[0]
                     else "➡️ Stable")
        print(f"  {trend}  {direction}")

    if sg_records:
        print(f"\n  {Fore.CYAN}Sugar Trend (Fasting):{Style.RESET_ALL}")
        values = [r["sugar_fasting"] for r in reversed(sg_records)]
        trend = " → ".join(str(v) for v in values)
        direction = ("⬆️ Rising" if values[-1] > values[0]
                     else "⬇️ Falling" if values[-1] < values[0]
                     else "➡️ Stable")
        print(f"  {trend}  {direction}")


def show_cost_summary():
    try:
        totals = get_total_cost_summary()
        print(f"\n  {Fore.CYAN}API Cost Summary (All Time):{Style.RESET_ALL}\n")
        rows = [
            ["Total Sessions", totals.get("total_sessions", 0)],
            ["STT Audio", f"{totals.get('total_stt_seconds', 0):.1f} seconds"],
            ["STT Cost", f"₹{totals.get('total_stt_cost', 0):.4f}"],
            ["TTS Characters", f"{totals.get('total_tts_chars', 0)}"],
            ["TTS Cost", f"₹{totals.get('total_tts_cost', 0):.4f}"],
            ["LLM (Ollama)", "₹0.0000 FREE"],
            ["─────────────────", "──────────────"],
            ["GRAND TOTAL", f"₹{totals.get('grand_total', 0):.4f}"],
        ]
        print(tabulate(rows, tablefmt="plain"))
    except Exception as e:
        print(f"  {Fore.RED}Could not load costs: {e}{Style.RESET_ALL}")


def show_alerts(user_id):
    try:
        with get_session_factory()() as s:
            alerts = list(s.scalars(
                select(Alert)
                .where(Alert.user_id == user_id)
                .order_by(Alert.sent_at.desc())
                .limit(10)
            ).all())

        if not alerts:
            print(f"  {Fore.GREEN}No alerts triggered yet.{Style.RESET_ALL}")
            return

        rows = [[
            a.sent_at.strftime("%d %b %H:%M") if a.sent_at else "?",
            (a.alert_level or "").upper(),
            a.trigger_reason or "—",
        ] for a in alerts]
        print(tabulate(rows, headers=["Time", "Level", "Reason"],
                       tablefmt="rounded_outline"))
    except Exception as e:
        print(f"  {Fore.YELLOW}No alert history: {e}{Style.RESET_ALL}")


def main():
    print(f"\n{Fore.BLUE}{'═'*60}")
    print(f"  📊 AI SATHI — Data Dashboard")
    print(f"{'═'*60}{Style.RESET_ALL}")

    user = get_default_user()
    if not user:
        print(f"{Fore.RED}No users in database. Run: python core/database.py{Style.RESET_ALL}")
        return

    print(f"\n  👤 User: {Fore.GREEN}{user['name']}{Style.RESET_ALL} "
          f"| Age: {user.get('age', '?')} "
          f"| Language: {user.get('language', '?')}\n")

    level, reason = check_alert_needed(user["id"])
    if level:
        colors = {"green": Fore.GREEN, "yellow": Fore.YELLOW,
                  "orange": Fore.YELLOW, "red": Fore.RED,
                  "emergency": Fore.RED + Style.BRIGHT}
        emojis = {"green": "🟢", "yellow": "🟡", "orange": "🟠",
                  "red": "🔴", "emergency": "🚨"}
        c = colors.get(level, Fore.WHITE)
        e = emojis.get(level, "•")
        print(f"  {c}{e} Current Alert Level: {level.upper()}")
        if reason and reason != "All good":
            print(f"  Reason: {reason}{Style.RESET_ALL}")

    print(f"\n{Fore.BLUE}{'─'*60}{Style.RESET_ALL}")
    show_recent_conversations(user["id"])

    print(f"\n{Fore.BLUE}{'─'*60}{Style.RESET_ALL}")
    show_health_records(user["id"])

    print(f"\n{Fore.BLUE}{'─'*60}{Style.RESET_ALL}")
    show_vitals_trend(user["id"])

    print(f"\n{Fore.BLUE}{'─'*60}{Style.RESET_ALL}")
    show_cost_summary()

    print(f"\n{Fore.BLUE}{'─'*60}{Style.RESET_ALL}")
    print(f"\n  {Fore.CYAN}Alert History:{Style.RESET_ALL}")
    show_alerts(user["id"])

    print(f"\n{Fore.BLUE}{'═'*60}{Style.RESET_ALL}\n")


if __name__ == "__main__":
    main()
