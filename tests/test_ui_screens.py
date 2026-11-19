"""Screen inventory, IDs, nav, and app.js wiring — no browser required."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "mobile" / "www" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "mobile" / "www" / "js" / "app.js").read_text(encoding="utf-8")
API_JS = (ROOT / "mobile" / "www" / "js" / "api.js").read_text(encoding="utf-8")


def _ids(html: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', html))


def test_all_screens_exist():
    for sid in (
        "screen-setup",
        "screen-companion",
        "screen-family",
        "screen-detail",
        "screen-schedule",
        "screen-profile",
        "screen-history",
        "screen-recordings",
    ):
        assert f'id="{sid}"' in INDEX, sid


def test_bottom_nav_tabs_map_to_screens():
    tabs = set(re.findall(r'data-tab="([^"]+)"', INDEX))
    assert tabs == {"home", "schedule", "profile"}
    assert "function setFamilyTab" in APP_JS
    assert 'showScreen("screen-schedule")' in APP_JS
    assert 'showScreen("screen-profile")' in APP_JS


def test_role_pills_and_consent_boxes():
    assert 'data-role="family"' in INDEX
    assert 'data-role="companion"' in INDEX
    for cid in ("f-consent-calls", "f-consent-rec", "f-consent-health"):
        assert cid in _ids(INDEX)


def test_primary_actions_present():
    for eid in (
        "btn-call-companion",
        "btn-share-invite",
        "btn-refresh-invite",
        "invite-block",
        "calls-only-note",
        "add-phone-hint",
        "btn-call-detail",
        "btn-sos",
        "btn-add-person",
        "btn-test-plan",
        "btn-cancel-plan",
        "btn-delete-account",
        "save-settings",
        "btn-reset",
        "add-save",
        "add-cancel",
        "sos-yes",
        "sos-cancel",
        "sos-108",
        "back-detail",
    ):
        assert eid in _ids(INDEX), eid


def test_legal_pages_exist():
    www = ROOT / "mobile" / "www"
    assert (www / "privacy.html").is_file()
    assert (www / "terms.html").is_file()
    assert "privacy.html" in INDEX
    assert "terms.html" in INDEX


def test_js_getelementbyid_targets_exist():
    ids = _ids(INDEX)
    # Dynamic sheet IDs created in JS are allowed to be missing in the first paint.
    dynamic = {"week-", "close-call-modal"}
    missing = []
    for eid in re.findall(r'getElementById\("([^"]+)"\)', APP_JS):
        if any(eid.startswith(p) for p in dynamic):
            continue
        if eid not in ids:
            missing.append(eid)
    assert missing == [], f"JS references missing HTML ids: {missing}"


def test_api_sends_bearer_token():
    assert "Authorization" in API_JS
    assert "saathi_token" in API_JS
    assert "consent_calls" in API_JS


def test_modals_have_cancel_and_confirm():
    assert 'id="addModal"' in INDEX
    assert 'id="sosModal"' in INDEX
    assert 'id="add-cancel"' in INDEX
    assert 'id="add-save"' in INDEX
    assert 'id="sos-cancel"' in INDEX
    assert 'id="sos-yes"' in INDEX


def test_schedule_controls_in_renderer():
    assert "data-time-id" in APP_JS
    assert "data-enabled-id" in APP_JS
    assert "day-chip" in APP_JS
    assert "Skip today" in APP_JS
    assert "Asia/Kolkata" in APP_JS
    assert "updateInviteSection" in APP_JS
    assert "hasPhone === false" in APP_JS
