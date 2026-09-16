"""Example webhook handler: landing-page POST -> sellable lead -> pipeline.

Minimal WSGI handler with no framework dependency, to show the wiring. In
production use Flask/FastAPI, add CSRF/rate limiting, and claim the TrustedForm
certificate server-side before storing (that is what sets cert_claimed=True).

Run: python -m capture.example_handler   (serves on :8000, prints captured leads)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fexlead.capture import lead_from_capture  # noqa: E402
from fexlead.verification import verify_lead  # noqa: E402

COMPANY = "[YOUR AGENCY NAME]"


def handle_submission(form: dict[str, str]) -> dict:
    now = datetime.now(timezone.utc)
    result = lead_from_capture(
        form,
        company=COMPANY,
        consent_language_shown=form.get("consent_language_shown", ""),
        trustedform_token=form.get("xxTrustedFormCertUrl") or None,
        jornaya_token=form.get("leadid_token") or None,
        ip_address=form.get("_ip"),
        now=now,
        # In production: call the TrustedForm claim API here, then pass True.
        cert_claimed=None,
    )
    quality = verify_lead(result.lead, check_deliverability=True) if result.lead else None
    return {
        "sellable": result.sellable,
        "reasons": result.reasons,
        "lead_id": result.lead.lead_id if result.lead else None,
        "data_quality": quality.grade() if quality else None,
    }


def app(environ, start_response):
    if environ.get("REQUEST_METHOD") != "POST":
        start_response("405 Method Not Allowed", [("Content-Type", "text/plain")])
        return [b"POST only"]
    size = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(size).decode("utf-8")
    form = {k: v[0] for k, v in parse_qs(body).items()}
    form["_ip"] = environ.get("REMOTE_ADDR")
    out = handle_submission(form)
    print("captured:", json.dumps(out))
    start_response("200 OK", [("Content-Type", "application/json")])
    return [json.dumps(out).encode("utf-8")]


if __name__ == "__main__":
    print("Lead capture handler on http://127.0.0.1:8000  (Ctrl-C to stop)")
    make_server("127.0.0.1", 8000, app).serve_forever()
