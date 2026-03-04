from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request

import pytest


def _should_run_integration() -> bool:
    return os.environ.get("RUN_INTEGRATION") == "1"


def _normalize_ask_payload(raw: dict) -> dict:
    # Supports the "automation" camelCase payload format while keeping the API contract unchanged.
    default_tenant_id = os.environ.get("DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")

    tenant_id = raw.get("tenant_id", raw.get("tenantId"))
    if tenant_id == "local":
        tenant_id = default_tenant_id

    scope_raw = raw.get("scope", raw.get("policyScope"))
    scope = None
    if isinstance(scope_raw, dict):
        scope = {
            "only_current": scope_raw.get("only_current", scope_raw.get("onlyCurrent", True)),
            "policy_ids": scope_raw.get("policy_ids", scope_raw.get("policyIds")),
            "policy_types": scope_raw.get("policy_types", scope_raw.get("policyTypes")),
        }

    user_raw = raw.get("user")
    user = None
    if isinstance(user_raw, dict):
        user = dict(user_raw)
        # API schema expects user.tenant_id when user is present.
        user.setdefault("tenant_id", tenant_id)

    normalized = {
        "tenant_id": tenant_id,
        "question": raw.get("question"),
        "mode": raw.get("mode"),
        "scope": scope,
        "user": user,
        "as_of": raw.get("as_of", raw.get("asOf")),
        "correlation_id": raw.get("correlation_id", raw.get("correlationId")),
    }

    # Remove Nones so we don't accidentally send invalid explicit nulls.
    return {k: v for k, v in normalized.items() if v is not None}


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = int(getattr(resp, "status", 200))
            data = resp.read().decode("utf-8")
            return status, json.loads(data) if data else {}
    except urllib.error.HTTPError as e:
        data = e.read().decode("utf-8") if e.fp else ""
        try:
            return int(e.code), json.loads(data) if data else {}
        except Exception:
            return int(e.code), {"raw": data}


@pytest.mark.integration
def test_ask_fixtures_hit_running_api() -> None:
    if not _should_run_integration():
        pytest.skip("RUN_INTEGRATION!=1")

    base_url = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
    ask_url = f"{base_url}/v1/ask"

    fixtures_dir = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "endpoints" / "ask"
    fixture_files = sorted(fixtures_dir.glob("*.json"))
    assert fixture_files, f"No JSON fixtures found in {fixtures_dir}"

    for fixture_path in fixture_files:
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        payload = _normalize_ask_payload(raw)

        try:
            status, resp = _post_json(ask_url, payload)
        except OSError as e:
            pytest.skip(f"API not reachable at {base_url}: {e}")

        assert status == 200, {"fixture": str(fixture_path), "status": status, "response": resp}
        assert isinstance(resp, dict)
        assert "answer" in resp
        assert "created_at" in resp
