"""Local dummy-call mode (no Twilio)."""

from unittest.mock import AsyncMock, patch

CONSENT = {
    "consent_calls": True,
    "consent_recording": True,
    "consent_health": True,
}


def _signup(client, phone="+919800000001", role="subscriber", name="Aditi"):
    r = client.post("/api/auth/request-otp", json={"phone": phone})
    assert r.status_code == 200, r.text
    otp = r.json().get("dev_otp") or "123456"
    v = client.post(
        "/api/auth/verify",
        json={"phone": phone, "otp": otp, "role": role, "name": name},
    )
    assert v.status_code == 200, v.text
    token = v.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    reg = client.post(
        "/api/register",
        json={"role": role, "name": name, "phone": phone, "language": "hi-IN", **CONSENT},
        headers=headers,
    )
    assert reg.status_code == 200, reg.text
    return headers, token


def test_local_outbound_returns_pc_url(client, monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "local")
    import telephony.config as cfg
    monkeypatch.setattr(cfg, "TELEPHONY_PROVIDER", "local")
    import telephony.routes.common as common
    monkeypatch.setattr(common, "TELEPHONY_PROVIDER", "local")

    headers, _ = _signup(client)
    client.post(
        "/api/people",
        headers=headers,
        json={
            "subscriber_phone": "+919800000001",
            "subscriber_name": "Aditi",
            "name": "Kamla",
            "phone": "+919800000002",
            "language": "hi-IN",
            "has_smartphone": False,
        },
    )
    out = client.post(
        "/call/outbound",
        headers=headers,
        json={"to_number": "+919800000002", "name": "Kamla", "language": "hi-IN"},
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["provider"] == "local"
    assert body["session_id"]
    assert "/local-call/" in body["local_call_url"]
    sid = body["session_id"]

    page = client.get("/local-call/" + sid)
    assert page.status_code == 200
    assert "Local dummy call" in page.text

    st = client.get("/api/local-call/" + sid)
    assert st.status_code == 200
    assert st.json()["greeting"]
    assert st.json()["status"] == "active"


def test_local_turn_and_end(client, monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "local")
    import telephony.config as cfg
    monkeypatch.setattr(cfg, "TELEPHONY_PROVIDER", "local")
    import telephony.routes.common as common
    monkeypatch.setattr(common, "TELEPHONY_PROVIDER", "local")

    headers, _ = _signup(client, phone="+919800000011")
    client.post(
        "/api/people",
        headers=headers,
        json={
            "subscriber_phone": "+919800000011",
            "subscriber_name": "Aditi",
            "name": "Ramesh",
            "phone": "+919800000012",
            "language": "en-IN",
        },
    )
    out = client.post(
        "/call/outbound",
        headers=headers,
        json={"to_number": "+919800000012", "name": "Ramesh", "language": "en-IN"},
    )
    sid = out.json()["session_id"]

    fake = {
        "continue": True,
        "user_text": "I am fine today",
        "sathi_text": "That is good to hear.",
        "tts_chars": 10,
        "call_done": False,
        "audio_b64": None,
        "elapsed_s": 0.1,
    }
    with patch("telephony.local_calls.run_text_turn", new=AsyncMock(return_value=fake)):
        turn = client.post(
            "/api/local-call/" + sid + "/turn",
            json={"text": "I am fine today", "speak": False},
        )
    assert turn.status_code == 200, turn.text
    assert turn.json()["sathi_text"] == "That is good to hear."

    with patch("telephony.local_calls.deep_extract", new=AsyncMock(return_value={"mood": "good"})):
        with patch("telephony.local_calls.analyse", return_value=("green", "ok")):
            ended = client.post("/api/local-call/" + sid + "/end")
    assert ended.status_code == 200, ended.text
    assert ended.json()["status"] == "ended"

    summary = client.get(
        "/api/user/summary",
        params={"phone": "+919800000012"},
        headers=headers,
    )
    assert summary.status_code == 200
    last = summary.json().get("last_call")
    assert last
    roles = [t["role"] for t in last.get("turns") or []]
    assert "sathi" in roles


def test_health_reports_local_when_provider_local(client, monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "local")
    import telephony.routes.common as common
    monkeypatch.setattr(common, "TELEPHONY_PROVIDER", "local")
    r = client.get("/health")
    assert r.status_code == 200
    assert "local_calls_active" in r.json()
