"""Invite share + accept flow for subscriber → elder."""

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


def test_add_person_returns_invite_link(client):
    headers, _ = _signup(client)
    add = client.post(
        "/api/people",
        headers=headers,
        json={
            "subscriber_phone": "+919800000001",
            "subscriber_name": "Aditi",
            "name": "Kamla",
            "phone": "+919800000002",
            "language": "hi-IN",
            "call_time": "09:00",
        },
    )
    assert add.status_code == 200, add.text
    user = add.json()["user"]
    assert user["invite_code"]
    assert "invite=" in (user["invite_url"] or "")
    assert user["invite_accepted"] is False

    prev = client.get("/api/invite/" + user["invite_code"])
    assert prev.status_code == 200
    assert prev.json()["name"] == "Kamla"
    assert prev.json()["phone"] == "+919800000002"


def test_elder_accepts_invite_with_matching_phone(client):
    headers, _ = _signup(client)
    add = client.post(
        "/api/people",
        headers=headers,
        json={
            "subscriber_phone": "+919800000001",
            "subscriber_name": "Aditi",
            "name": "Kamla",
            "phone": "+919800000002",
            "language": "hi-IN",
        },
    )
    code = add.json()["user"]["invite_code"]

    elder_headers, _ = _signup(
        client, phone="+919800000002", role="user", name="Kamla"
    )
    ok = client.post(
        "/api/invite/accept",
        headers=elder_headers,
        json={"invite_code": code, "phone": "+919800000002", **CONSENT},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["user"]["invite_accepted"] is True
    assert ok.json()["role"] == "user"


def test_wrong_phone_cannot_accept_invite(client):
    headers, _ = _signup(client)
    add = client.post(
        "/api/people",
        headers=headers,
        json={
            "subscriber_phone": "+919800000001",
            "subscriber_name": "Aditi",
            "name": "Kamla",
            "phone": "+919800000002",
            "language": "hi-IN",
        },
    )
    code = add.json()["user"]["invite_code"]
    other, _ = _signup(client, phone="+919800000099", role="user", name="Other")
    bad = client.post(
        "/api/invite/accept",
        headers=other,
        json={"invite_code": code, "phone": "+919800000099", **CONSENT},
    )
    assert bad.status_code == 403


def test_refresh_invite_rotates_code(client):
    headers, _ = _signup(client)
    add = client.post(
        "/api/people",
        headers=headers,
        json={
            "subscriber_phone": "+919800000001",
            "subscriber_name": "Aditi",
            "name": "Kamla",
            "phone": "+919800000002",
            "language": "hi-IN",
        },
    )
    old = add.json()["user"]["invite_code"]
    refreshed = client.post(
        "/api/invite/refresh",
        headers=headers,
        json={"phone": "+919800000002"},
    )
    assert refreshed.status_code == 200, refreshed.text
    new = refreshed.json()["user"]["invite_code"]
    assert new and new != old
    assert client.get("/api/invite/" + old).status_code == 404
    assert client.get("/api/invite/" + new).status_code == 200
