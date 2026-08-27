#!/usr/bin/env python3
"""Scan a codebase and report every external system it talks to.

Written so Chris does not have to remember the integration list from memory.
Point it at the LA Lighthouse (or Studio) source tree, paste the report back.

    python3 find_integrations.py /path/to/lighthouse
    python3 find_integrations.py /path/to/lighthouse --json
    python3 find_integrations.py --selftest

SAFETY: this prints the NAMES of credentials it finds, never their VALUES, so
the output is safe to paste into a chat. The self-test proves that by planting
a fake secret and asserting the value never appears in the report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "env",
             "dist", "build", ".next", ".mypy_cache", ".pytest_cache", "site-packages"}
SCAN_EXT = {".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".toml", ".yaml", ".yml",
            ".cfg", ".ini", ".env", ".txt", ".md", ".sql", ".sh", ".ps1"}
MAX_BYTES = 2_000_000

# Known third-party systems, grouped the way a buyer thinks about them.
SDKS: dict[str, list[str]] = {
    "Payments / POS": ["stripe", "squareup", "square", "clover", "helcim", "authorizenet",
                       "authorize_net", "braintree", "paypal", "adyen", "nmi", "payjunction",
                       "cardconnect", "usaepay", "dejavoo"],
    "Banking / ACH": ["plaid", "dwolla", "modernbanking", "teller", "yodlee", "finicity",
                      "nacha", "ach", "moov"],
    "Accounting": ["quickbooks", "intuit", "qbo", "xero", "freshbooks", "wave", "sage",
                   "netsuite"],
    "Spreadsheets / files": ["openpyxl", "xlrd", "xlsxwriter", "pandas", "gspread",
                             "csv", "pyexcel", "tabula"],
    "Messaging / alerts": ["twilio", "sendgrid", "mailgun", "smtplib", "slack_sdk",
                           "discord", "pushover", "resend"],
    "Storage / infra": ["boto3", "s3", "azure", "google.cloud", "dropbox", "supabase",
                        "firebase"],
    "Databases": ["psycopg", "sqlite3", "sqlalchemy", "pymysql", "mongodb", "pymongo",
                  "redis", "duckdb"],
    "AI / LLM": ["anthropic", "openai", "ollama", "llama_cpp", "transformers",
                 "sentence_transformers", "langchain", "litellm"],
    "Scraping": ["requests", "httpx", "aiohttp", "beautifulsoup", "bs4", "selenium",
                 "playwright", "scrapy", "lxml"],
}

CRED_NAME = re.compile(
    r"\b([A-Z][A-Z0-9_]{2,}(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|"
    r"CLIENT_ID|CLIENT_SECRET|API|AUTH|AUTHORIZATION|AUTH_TOKEN|AUTH_KEY|WEBHOOK))\b"
)
URL = re.compile(r"https?://([a-zA-Z0-9][a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})")
ROUTE = re.compile(r"""@(?:app|router|bp|blueprint)\.(get|post|put|patch|delete|route)\(\s*['"]([^'"]+)""")

# Hosts that are documentation or package infrastructure, not integrations.
NOISE_HOSTS = {"github.com", "www.github.com", "raw.githubusercontent.com", "pypi.org",
               "files.pythonhosted.org", "npmjs.com", "registry.npmjs.org", "localhost",
               "example.com", "www.w3.org", "schema.org", "json-schema.org",
               "docs.python.org", "stackoverflow.com", "opensource.org", "127.0.0.1"}


def iter_files(root: Path):
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in SCAN_EXT or path.name.startswith(".env"):
            try:
                if path.stat().st_size <= MAX_BYTES:
                    yield path
            except OSError:
                continue


def scan(root: Path) -> dict:
    sdk_hits: dict[str, dict[str, set]] = {g: defaultdict(set) for g in SDKS}
    creds: set[str] = set()
    hosts: dict[str, set] = defaultdict(set)
    routes: set[tuple[str, str]] = set()
    files_scanned = 0

    lowered = {g: {name: re.compile(rf"\b{re.escape(name)}\b", re.I) for name in names}
               for g, names in SDKS.items()}

    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files_scanned += 1
        rel = str(path.relative_to(root))

        for group, pats in lowered.items():
            for name, pat in pats.items():
                if pat.search(text):
                    sdk_hits[group][name].add(rel)

        creds.update(CRED_NAME.findall(text))          # names only, never values
        for host in URL.findall(text):
            if host.lower() not in NOISE_HOSTS:
                hosts[host.lower()].add(rel)
        for verb, route in ROUTE.findall(text):
            routes.add((verb.upper(), route))

    return {
        "root": str(root),
        "files_scanned": files_scanned,
        "sdks": {g: {n: sorted(f)[:3] for n, f in sorted(d.items())}
                 for g, d in sdk_hits.items() if d},
        "credential_names": sorted(creds),
        "external_hosts": {h: sorted(f)[:2] for h, f in sorted(hosts.items())},
        "routes": sorted(routes),
    }


def render(report: dict) -> str:
    out = [f"Scanned {report['files_scanned']} files under {report['root']}", ""]

    if report["sdks"]:
        out.append("EXTERNAL SYSTEMS")
        for group, hits in report["sdks"].items():
            out.append(f"\n  {group}")
            for name, files in hits.items():
                out.append(f"    - {name:<24} {', '.join(files)}")
    else:
        out.append("EXTERNAL SYSTEMS: none matched. Widen SDKS if this looks wrong.")

    if report["external_hosts"]:
        out.append("\nHOSTS CONTACTED")
        for host, files in list(report["external_hosts"].items())[:40]:
            out.append(f"    - {host:<40} {', '.join(files)}")

    if report["routes"]:
        out.append("\nROUTES EXPOSED")
        for verb, route in report["routes"][:40]:
            out.append(f"    - {verb:<7} {route}")

    if report["credential_names"]:
        out.append("\nCREDENTIALS REFERENCED (names only, no values)")
        out.append("    " + ", ".join(report["credential_names"][:60]))

    return "\n".join(out)


def selftest() -> int:
    """Prove it finds integrations, and prove it never leaks a secret value."""
    tmp = Path(tempfile.mkdtemp(prefix="findint-selftest-"))
    (tmp / "app.py").write_text(
        "import stripe\n"
        "import openpyxl\n"
        "from plaid import Client\n"
        "STRIPE_API_KEY = 'sk_live_SUPERSECRETVALUE_1234'\n"
        "resp = requests.get('https://connect.squareup.com/v2/payments')\n"
        "@app.post('/webhooks/square')\n"
        "def hook(): ...\n"
    )
    (tmp / "notes.md").write_text("we also read https://github.com/foo for docs\n")
    (tmp / "node_modules").mkdir()
    (tmp / "node_modules" / "junk.js").write_text("import stripe from 'stripe'\n")

    report = scan(tmp)
    text = render(report)
    checks = [
        ("finds payment SDK", "stripe" in report["sdks"].get("Payments / POS", {})),
        ("finds banking SDK", "plaid" in report["sdks"].get("Banking / ACH", {})),
        ("finds spreadsheet lib", "openpyxl" in report["sdks"].get("Spreadsheets / files", {})),
        ("finds external host", "connect.squareup.com" in report["external_hosts"]),
        ("finds webhook route", ("POST", "/webhooks/square") in report["routes"]),
        ("reports credential NAME", "STRIPE_API_KEY" in report["credential_names"]),
        ("never prints secret VALUE", "SUPERSECRETVALUE" not in text),
        ("filters doc-site noise", "github.com" not in report["external_hosts"]),
        ("skips node_modules", report["files_scanned"] == 2),
    ]
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    failed = [n for n, ok in checks if not ok]
    if failed:
        print(f"\nSELFTEST FAILED: {', '.join(failed)}")
        return 1
    print("\nSELFTEST PASSED")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.root:
        ap.error("give a directory to scan (or use --selftest)")
    if not args.root.is_dir():
        ap.error(f"{args.root} is not a directory")

    report = scan(args.root.resolve())
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
