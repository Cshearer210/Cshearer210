#!/usr/bin/env python3
"""Refuse to record if the take could leak real data.

The legal constraint on the LA Lighthouse demo is that none of their data
appears in the video. That constraint is worth exactly as much as the check
that enforces it, so this fails loudly and defaults to UNSAFE.

    python3 preflight.py --shots ../shots/lighthouse.json \
        --denylist ~/private/real-names.txt --require-host demo.internal

    python3 preflight.py --selftest

The denylist file is one term per line (real client names, real domains, real
account numbers). Keep it OUTSIDE this repo - it is itself sensitive.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

# Hosts that must never appear as a recording target.
PROD_MARKERS = ("prod", "production", "live", "app.", "www.")


def load_denylist(path: Path) -> list[str]:
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        term = line.strip()
        if term and not term.startswith("#"):
            terms.append(term)
    return terms


def check(shots_path: Path, denylist: list[str], require_host: str | None) -> list[tuple[str, bool, str]]:
    raw = shots_path.read_text(encoding="utf-8")
    shots = json.loads(raw)
    results: list[tuple[str, bool, str]] = []

    base = shots.get("base_url", "")

    # 1. Target must be the demo tenant, not production.
    if require_host:
        ok = require_host in base
        results.append(("target host is the demo tenant", ok,
                        f"base_url={base!r} must contain {require_host!r}"))
    hit = [m for m in PROD_MARKERS if m in base.lower()]
    results.append(("target does not look like production", not hit,
                    f"base_url contains {hit}" if hit else "clean"))

    # 2. Placeholders must be filled in.
    leftovers = re.findall(r"SELECTOR_[A-Z_0-9]+|DEMO-TENANT-HOST|localhost:PORT", raw)
    results.append(("no unfilled placeholders", not leftovers,
                    f"{len(leftovers)} left: {sorted(set(leftovers))[:4]}" if leftovers else "clean"))

    # 3. No denylisted real-world term anywhere in the shot list.
    found = sorted({t for t in denylist if t.lower() in raw.lower()})
    results.append(("no denylisted terms in shot list", not found,
                    f"found {found}" if found else f"checked {len(denylist)} terms"))

    # 4. Credentials must come from env, never be literals.
    literals = []
    for step in shots.get("steps", []):
        sel = str(step.get("selector", "")).lower()
        if any(k in sel for k in ("pass", "secret", "token", "apikey", "api_key")):
            if "env" not in step:
                literals.append(step.get("selector"))
    results.append(("no hardcoded credentials", not literals,
                    f"literal value on {literals}" if literals else "clean"))

    return results


def report(results: list[tuple[str, bool, str]]) -> int:
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  -- {detail}")
    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print(f"\nDO NOT RECORD. {len(failed)} check(s) failed: {', '.join(failed)}")
        return 1
    print("\nPRE-FLIGHT CLEAR - safe to record")
    return 0


def selftest() -> int:
    """Prove each gate can actually fail. A gate never made to fail is not a gate."""
    tmp = Path(tempfile.mkdtemp(prefix="preflight-selftest-"))
    deny = tmp / "deny.txt"
    deny.write_text("Acme Health\nrealclient.org\n")
    terms = load_denylist(deny)

    clean = tmp / "clean.json"
    clean.write_text(json.dumps({
        "base_url": "https://demo.internal",
        "steps": [{"do": "goto", "url": "/"},
                  {"do": "fill", "selector": "#password", "env": "DEMO_PASSWORD"}],
    }))

    dirty = tmp / "dirty.json"
    dirty.write_text(json.dumps({
        "base_url": "https://app.production.example.com",
        "steps": [{"do": "goto", "url": "/SELECTOR_THING"},
                  {"do": "fill", "selector": "#password", "value": "hunter2"},
                  {"do": "caption", "text": "Acme Health onboarding"}],
    }))

    cases = []
    good = check(clean, terms, require_host="demo.internal")
    cases.append(("clean shot list passes every gate", all(ok for _, ok, _ in good)))

    bad = check(dirty, terms, require_host="demo.internal")
    failed_names = {n for n, ok, _ in bad if not ok}
    for gate in ("target host is the demo tenant",
                 "target does not look like production",
                 "no unfilled placeholders",
                 "no denylisted terms in shot list",
                 "no hardcoded credentials"):
        cases.append((f"gate fires: {gate}", gate in failed_names))

    for name, ok in cases:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    bad_cases = [n for n, ok in cases if not ok]
    if bad_cases:
        print(f"\nSELFTEST FAILED: {', '.join(bad_cases)}")
        return 1
    print("\nSELFTEST PASSED - every gate was made to fail on purpose")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", type=Path)
    ap.add_argument("--denylist", type=Path)
    ap.add_argument("--require-host", type=str, default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.shots or not args.denylist:
        ap.error("--shots and --denylist are required (or use --selftest)")
    return report(check(args.shots, load_denylist(args.denylist), args.require_host))


if __name__ == "__main__":
    sys.exit(main())
