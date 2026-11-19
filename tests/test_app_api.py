"""Auth, consent, people, billing, delete — the gates before an APK."""

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


def test_summary_requires_sign_in(client):
    r = client.get("/api/user/summary", params={"phone": "+919800000001"})
    assert r.status_code == 401


def test_register_requires_consent(client):
    r = client.post(
        "/api/register",
        json={"role": "user", "name": "Kamla", "phone": "+919800000099", "language": "hi-IN"},
    )
    assert r.status_code == 400
    assert "consent" in r.json()["error"]


def test_subscriber_can_add_person_and_read_summary(client):
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
            "call_time": "10:30",
            "city": "Pune",
            "days_of_week": "1,2,3,4,5",
        },
    )
    assert add.status_code == 200, add.text
    user = add.json()["user"]
    assert user["city"] == "Pune"
    assert user["call_time"] == "10:30"
    assert user["days_of_week"] == "1,2,3,4,5"

    s = client.get("/api/user/summary", params={"phone": "+919800000002"}, headers=headers)
    assert s.status_code == 200, s.text
    assert s.json()["user"]["name"] == "Kamla"

    other = client.get("/api/user/summary", params={"phone": "+919899999999"}, headers=headers)
    assert other.status_code in (403, 404)


def test_cannot_read_someone_elses_people(client):
    headers, _ = _signup(client, phone="+919800000011")
    r = client.get("/api/people", params={"subscriber_phone": "+919800000099"}, headers=headers)
    assert r.status_code == 403


def test_outbound_requires_token(client):
    r = client.post(
        "/call/outbound",
        json={"to_number": "+919800000002", "name": "Kamla", "language": "hi-IN"},
    )
    assert r.status_code == 401


def test_outbound_forbids_random_number(client):
    headers, _ = _signup(client)
    r = client.post(
        "/call/outbound",
        headers=headers,
        json={"to_number": "+919899999999", "name": "Stranger", "language": "hi-IN"},
    )
    assert r.status_code == 403


def test_test_plan_and_delete(client):
    headers, _ = _signup(client)
    bill = client.post("/api/billing/test-activate", headers=headers)
    assert bill.status_code == 200, bill.text
    assert bill.json()["plan_status"] == "test"
    gone = client.post("/api/account/delete", headers=headers)
    assert gone.status_code == 200
    assert gone.json()["deleted"] is True


def test_auth_mode_exposes_test_otp(client):
    r = client.get("/api/auth/mode")
    assert r.status_code == 200
    body = r.json()
    assert body["test_otp_allowed"] is True
    assert body["sms_configured"] is False


def test_subscriber_can_add_calls_only_person(client):
    headers, _ = _signup(client)
    add = client.post(
        "/api/people",
        headers=headers,
        json={
            "subscriber_phone": "+919800000001",
            "subscriber_name": "Aditi",
            "name": "Ratnakar",
            "phone": "+919800000003",
            "language": "mr-IN",
            "has_smartphone": False,
        },
    )
    assert add.status_code == 200, add.text
    user = add.json()["user"]
    assert user["has_smartphone"] is False
    assert user["consent_calls"] is True


def test_save_conversation_skips_empty_message(client):
    from core.database import get_call_detail, save_conversation, upsert_demo_user

    u = upsert_demo_user(name="Empty", phone="+919800000088", language="hi-IN")
    sid = "test-empty-turns"
    save_conversation(u["id"], sid, "sathi", "   ")
    save_conversation(u["id"], sid, "user", "Hello")
    save_conversation(u["id"], sid, "sathi", "Namaste")
    detail = get_call_detail(u["id"], sid)
    assert detail is not None
    assert len(detail["turns"]) == 2
    assert detail["turns"][0]["message"] == "Hello"
    assert detail["turns"][1]["message"] == "Namaste"


def test_health_reports_recordings(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert "recordings" in r.json()
    assert r.json()["recordings"]["dir"]
