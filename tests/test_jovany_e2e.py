"""
E2E test for the Jovany genesis pipeline.
Migrated from root-level test_jovany.py (orphan script).

Requires a running Titan API server on localhost:8080.
Mark: e2e (requires live API + device).
"""
import json
import os
import time

import pytest
import requests

API_BASE = os.environ.get("TITAN_API_URL", "http://127.0.0.1:8080")
API_TOKEN = os.environ.get("TITAN_API_SECRET", "")


def _headers():
    return {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.mark.e2e
def test_jovany_pipeline():
    """Run the Jovany genesis pipeline end-to-end and assert success."""
    assert API_TOKEN, "TITAN_API_SECRET env var must be set"

    url = f"{API_BASE}/api/devices"

    # Get or create a device
    resp = requests.get(url, headers=_headers())
    resp.raise_for_status()
    devices = resp.json().get("devices", [])

    if not devices:
        body = {
            "model": "samsung_s24_ultra",
            "country": "US",
            "carrier": "tmobile_us",
            "android_version": "14",
        }
        resp = requests.post(url, headers=_headers(), json=body)
        resp.raise_for_status()
        dev_id = resp.json()["device_id"]
    else:
        dev_id = devices[0].get("id") or devices[0].get("device_id")

    assert dev_id, "No device ID available"

    # Start pipeline
    pipe_url = f"{API_BASE}/api/genesis/pipeline/{dev_id}"
    pipe_body = {
        "target_archetype": "student",
        "persona_name": "Jovany Owens",
        "persona_email": "jovany.owens@gmail.com",
        "cc_number": "4111222233334444",
        "cc_exp_month": 12,
        "cc_exp_year": 28,
        "cc_cardholder": "Jovany Owens",
        "zero_auth": True,
    }
    resp = requests.post(pipe_url, headers=_headers(), json=pipe_body)
    resp.raise_for_status()
    job_id = resp.json().get("job_id")
    assert job_id, "Pipeline did not return a job_id"

    # Poll until completion (max 10 minutes)
    status_url = f"{API_BASE}/api/genesis/pipeline-status/{job_id}"
    deadline = time.time() + 600
    final_status = None

    while time.time() < deadline:
        st = requests.get(status_url, headers=_headers()).json()
        final_status = st.get("status")
        if final_status in ("success", "failed", "completed"):
            break
        time.sleep(3)

    assert final_status in ("success", "completed"), (
        f"Pipeline ended with status={final_status}"
    )
