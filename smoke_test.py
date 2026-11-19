"""Code-level smoke tests — no Exotel/FreJun/Twilio credentials required."""
import ast
import asyncio
import importlib
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from core.console_utf8 import configure_console_utf8
configure_console_utf8()

errors = []
passed = []


def ok(name):
    passed.append(name)
    print(f"  PASS  {name}")


def fail(name, exc):
    errors.append((name, str(exc)))
    print(f"  FAIL  {name}: {exc}")


print("=== 1) Syntax parse all Python files ===")
for path in sorted(ROOT.rglob("*.py")):
    if any(p in path.parts for p in (".git", "venv", ".venv", "__pycache__")):
        continue
    if path.name.startswith("_check") or path.name.startswith("_verify") or path.name.startswith("_cmp"):
        continue
    rel = path.relative_to(ROOT)
    try:
        ast.parse(path.read_text(encoding="utf-8"))
        ok(f"syntax:{rel}")
    except Exception as e:
        fail(f"syntax:{rel}", e)

print("\n=== 2) Core module imports ===")
modules = [
    "core.database",
    "core.stt_service",
    "core.tts_service",
    "core.llm_service",
    "core.extractor",
    "core.alert_engine",
    "core.audio",
    "core.call_recorder",
    "services.session_manager",
    "services.conversation_engine",
    "lang_services.marathi",
    "lang_services.hindi",
    "lang_services.english",
]
for m in modules:
    try:
        importlib.import_module(m)
        ok(f"import:{m}")
    except Exception as e:
        fail(f"import:{m}", e)

print("\n=== 3) call_server / scheduler imports ===")
for m in ("call_server", "scheduler"):
    try:
        if m in sys.modules:
            del sys.modules[m]
        importlib.import_module(m)
        ok(f"import:{m}")
    except Exception as e:
        fail(f"import:{m}", e)

print("\n=== 4) Database setup + helpers ===")
try:
    from core.database import (
        setup_database, seed_test_user, sync_user_from_env,
        get_default_user, get_all_active_users, get_user_by_phone,
    )
    setup_database()
    seed_test_user()
    sync_user_from_env()
    user = get_default_user()
    assert user and user.get("id"), "no default user"
    users = get_all_active_users()
    assert isinstance(users, list)
    # phone lookup should not crash (may return None)
    get_user_by_phone("+910000000000")
    ok(f"db:user={user.get('name')}|lang={user.get('language')}|n={len(users)}")
except Exception as e:
    fail("db", e)
    traceback.print_exc()

print("\n=== 5) Language service API surface ===")
try:
    import lang_services.hindi as hi
    import lang_services.marathi as mr
    for svc, label in ((hi, "hi"), (mr, "mr")):
        assert hasattr(svc, "GREETING")
        assert hasattr(svc, "CLOSING")
        assert hasattr(svc, "EXIT_WORDS")
        assert hasattr(svc, "TTS_CONFIG")
        assert hasattr(svc, "build_prompt")
        assert hasattr(svc, "prepare_for_tts")
        g = svc.GREETING.format(name="Test")
        ctx = {
            "turn_number": 1,
            "last_user_message": "hello",
            "last_sathi_message": "",
            "history_summary": {},
            "extracted_so_far": {},
            "should_steer": False,
            "steer_topic": None,
        }
        prompt = svc.build_prompt("Test", ctx)
        assert isinstance(prompt, str) and len(prompt) > 20
        prompt2 = svc.build_prompt("Test", {**ctx, "history_summary": ""})
        assert isinstance(prompt2, str)
        tts = svc.prepare_for_tts("hello world")
        assert isinstance(tts, str)
        ok(f"lang:{label}:{svc.NAME}:speaker={svc.TTS_CONFIG.get('speaker')}")
except Exception as e:
    fail("lang_api", e)
    traceback.print_exc()

print("\n=== 6) SessionManager + phone audio helpers ===")
try:
    from services.session_manager import SessionManager
    import lang_services.english as en
    user = get_default_user()
    sm = SessionManager(user, en)
    sm.start_turn()
    sm.record_user_turn("I slept poorly")
    sm.record_sathi_turn("Sorry to hear that.")
    ctx = sm.build_llm_context()
    assert "turn_number" in ctx
    ok("session_manager")
except Exception as e:
    fail("session_manager", e)
    traceback.print_exc()

try:
    import call_server as cs
    # PCM silence chunk
    silence = b"\x00\x00" * 160  # 20ms @ 8kHz mono 16-bit
    assert cs.is_silence(silence) is True
    wav = cs.pcm_8k_to_wav_16k(silence * 10)
    assert wav[:4] == b"RIFF"
    pcm_back = cs.wav_bytes_to_pcm_8k(wav)
    assert isinstance(pcm_back, (bytes, bytearray))
    flow = cs.frejun_stream_flow_payload("wss://example.com/frejun/media-stream")
    assert isinstance(flow, dict)
    ok(f"phone_audio+flow_keys={list(flow.keys())[:5]}")
except Exception as e:
    fail("phone_audio", e)
    traceback.print_exc()

print("\n=== 7) FastAPI routes registered ===")
try:
    import call_server as cs
    paths = {getattr(r, "path", None) for r in cs.app.routes}
    needed = {
        "/health",
        "/call/outbound",
        "/call/audio",
        "/call/status",
        "/frejun/flow",
        "/frejun/webhook",
        "/frejun/media-stream",
        "/twilio/voice",
        "/twilio/status",
        "/twilio/media-stream",
    }
    missing = needed - paths
    if missing:
        fail("routes", f"missing {missing}")
    else:
        ok(f"routes:{sorted(needed)}")
except Exception as e:
    fail("routes", e)
    traceback.print_exc()

print("\n=== 8) Outbound without credentials (expect False, no crash) ===")
try:
    import call_server as cs
    old_sid = cs.EXOTEL_SID
    old_key = cs.FREJUN_API_KEY
    old_twilio = cs.TWILIO_ACCOUNT_SID
    cs.EXOTEL_SID = ""
    assert cs.make_exotel_outbound_call("+919999999999", "wss://x/call/audio") is False
    cs.FREJUN_API_KEY = ""
    assert asyncio.run(cs.make_frejun_outbound_call("+919999999999")) is False
    cs.TWILIO_ACCOUNT_SID = ""
    assert cs.make_twilio_outbound_call("+15555550100") is False
    cs.EXOTEL_SID = old_sid
    cs.FREJUN_API_KEY = old_key
    cs.TWILIO_ACCOUNT_SID = old_twilio
    ok("outbound_no_creds_safe")
except Exception as e:
    fail("outbound_no_creds", e)
    traceback.print_exc()

print("\n=== 9) HTTP TestClient health + frejun flow ===")
try:
    from fastapi.testclient import TestClient
    import call_server as cs
    client = TestClient(cs.app)
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "ok"
    assert "telephony_provider" in body

    r2 = client.post("/frejun/flow", json={
        "call_id": "test-call-1",
        "from_number": "+911111111111",
        "to_number": "+912222222222",
    })
    assert r2.status_code == 200, r2.text
    flow = r2.json()
    assert isinstance(flow, dict)

    r3 = client.post("/frejun/webhook", json={"call_id": "test-call-1", "status": "completed"})
    assert r3.status_code == 200

    r4 = client.post("/call/outbound", json={"to_number": "+919999999999"})
    assert r4.status_code in (200, 500)

    r5 = client.post("/call/outbound", json={})
    assert r5.status_code == 400

    # Twilio voice needs form body; without SERVER_PUBLIC_URL returns Say TwiML
    r6 = client.post("/twilio/voice", data={
        "Direction": "outbound-api",
        "From": "+15555550100",
        "To": "+15555550199",
    })
    assert r6.status_code == 200
    assert "application/xml" in r6.headers.get("content-type", "")
    assert "Response" in r6.text

    r7 = client.post("/twilio/status", data={"CallStatus": "completed", "CallSid": "CAtest"})
    assert r7.status_code == 200

    ok(f"http:health={body} flow_ok status={r4.status_code} twilio_ok")
except Exception as e:
    fail("http_testclient", e)
    traceback.print_exc()

print("\n=== SUMMARY ===")
print(f"Passed: {len(passed)}")
print(f"Failed: {len(errors)}")
for name, msg in errors:
    print(f"  - {name}: {msg}")

sys.exit(1 if errors else 0)
