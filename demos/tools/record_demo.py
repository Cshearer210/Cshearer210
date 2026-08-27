#!/usr/bin/env python3
"""Drive a web app through a scripted shot list and record it to MP4.

Playwright records the page viewport (no OS chrome, no notifications, no stray
tabs) which removes the most common way a demo take leaks something it should
not. ffmpeg transcodes the raw webm to MP4 for sending.

Usage:
    python3 record_demo.py --shots shots/studio.json --out studio-demo.mp4
    python3 record_demo.py --selftest

Shot list format (JSON):
    {
      "base_url": "https://demo.example.com",
      "viewport": {"width": 1920, "height": 1080},
      "steps": [
        {"do": "goto",    "url": "/login"},
        {"do": "fill",    "selector": "#email", "value": "demo@example.com"},
        {"do": "caption", "text": "118 checks, run against live state", "seconds": 3},
        {"do": "click",   "selector": "text=Run harness"},
        {"do": "wait",    "seconds": 2}
      ]
    }

Credentials are read from the environment, never from the shot list, so a shot
list is safe to commit:  {"do": "fill", "selector": "#pw", "env": "DEMO_PASSWORD"}
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Pin to the browser already in the image. Do not run `playwright install`:
# the pip package and the preinstalled build drift, and the pinned path is
# the one that is actually present.
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
# Playwright's bundled ffmpeg is a stripped VP8-only build. MP4/H.264 is what
# survives being emailed to someone on Windows, so prefer a full build.
_PW_FFMPEG = "/opt/pw-browsers/ffmpeg-1011/ffmpeg-linux"


def find_ffmpeg() -> str | None:
    """Return an ffmpeg that can encode H.264, else any ffmpeg, else None."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return shutil.which("ffmpeg") or (_PW_FFMPEG if Path(_PW_FFMPEG).exists() else None)

CAPTION_JS = """
(payload) => {
  let el = document.getElementById('__demo_caption__');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_caption__';
    el.style.cssText = [
      'position:fixed', 'left:50%', 'bottom:6%', 'transform:translateX(-50%)',
      'z-index:2147483647', 'padding:16px 28px', 'border-radius:10px',
      'background:rgba(12,12,14,0.92)', 'color:#fff', 'font-size:30px',
      'font-family:-apple-system,Segoe UI,Roboto,sans-serif', 'font-weight:600',
      'letter-spacing:-0.01em', 'max-width:80vw', 'text-align:center',
      'box-shadow:0 8px 32px rgba(0,0,0,0.45)', 'pointer-events:none',
      'transition:opacity 220ms ease',
    ].join(';');
    document.body.appendChild(el);
  }
  el.textContent = payload;
  el.style.opacity = payload ? '1' : '0';
}
"""


def _resolve(step: dict) -> str:
    """Pull a step's value from the environment when it names one."""
    if "env" in step:
        name = step["env"]
        value = os.environ.get(name)
        if value is None:
            raise SystemExit(f"shot list needs env var {name!r}, which is not set")
        return value
    return step.get("value", "")


def run_shots(shots: dict, out_path: Path, headed: bool = False) -> Path:
    from playwright.sync_api import sync_playwright

    viewport = shots.get("viewport", {"width": 1920, "height": 1080})
    base_url = shots.get("base_url", "")
    raw_dir = Path(tempfile.mkdtemp(prefix="demo-raw-"))

    with sync_playwright() as p:
        launch: dict = {"headless": not headed}
        if Path(CHROME).exists():
            launch["executable_path"] = CHROME
        browser = p.chromium.launch(**launch)
        context = browser.new_context(
            viewport=viewport,
            record_video_dir=str(raw_dir),
            record_video_size=viewport,
            # A clean, empty profile: no history, no autofill, no saved sessions
            # that could surface a real client name in a dropdown mid-take.
            storage_state=None,
        )
        page = context.new_page()

        for i, step in enumerate(shots.get("steps", []), 1):
            action = step.get("do")
            try:
                if action == "goto":
                    url = step["url"]
                    page.goto(url if url.startswith(("http", "file")) else base_url + url,
                              wait_until=step.get("until", "load"))
                elif action == "click":
                    page.click(step["selector"], timeout=step.get("timeout_ms", 15000))
                elif action == "fill":
                    page.fill(step["selector"], _resolve(step))
                elif action == "press":
                    page.keyboard.press(step["key"])
                elif action == "hover":
                    page.hover(step["selector"])
                elif action == "scroll":
                    page.mouse.wheel(0, step.get("pixels", 600))
                elif action == "caption":
                    page.evaluate(CAPTION_JS, step.get("text", ""))
                    page.wait_for_timeout(int(step.get("seconds", 3) * 1000))
                    if step.get("clear", True):
                        page.evaluate(CAPTION_JS, "")
                elif action == "wait":
                    page.wait_for_timeout(int(step.get("seconds", 1) * 1000))
                else:
                    raise SystemExit(f"step {i}: unknown action {action!r}")
            except Exception as exc:
                raise SystemExit(f"step {i} ({action}) failed: {exc}") from exc

        video = page.video
        context.close()
        browser.close()
        raw = Path(video.path()) if video else None

    if raw is None or not raw.exists():
        raise SystemExit("playwright produced no video file")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        fallback = out_path.with_suffix(".webm")
        shutil.copy(raw, fallback)
        print(f"ffmpeg not found; kept raw webm at {fallback}")
        return fallback

    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(raw),
         "-c:v", "libx264", "-preset", "slow", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)],
        check=True,
    )
    shutil.rmtree(raw.parent, ignore_errors=True)
    return out_path


def selftest() -> int:
    """Prove the capture pipeline end to end, and prove it can fail.

    A recorder that has never been made to produce a bad file is not a
    recorder you can trust the morning you actually need it.
    """
    tmp = Path(tempfile.mkdtemp(prefix="demo-selftest-"))
    card = tmp / "card.html"
    card.write_text(
        "<body style='margin:0;background:#0b0b0f;color:#fff;"
        "font:600 64px -apple-system,Segoe UI,sans-serif;display:flex;"
        "align-items:center;justify-content:center;height:100vh'>"
        "capture pipeline test</body>"
    )
    shots = {
        "viewport": {"width": 1280, "height": 720},
        "steps": [
            {"do": "goto", "url": card.resolve().as_uri()},
            {"do": "caption", "text": "caption overlay works", "seconds": 2},
            {"do": "wait", "seconds": 1},
        ],
    }
    out = tmp / "selftest.mp4"
    produced = run_shots(shots, out)

    checks: list[tuple[str, bool]] = []
    checks.append(("file exists", produced.exists()))
    size = produced.stat().st_size if produced.exists() else 0
    checks.append(("file is non-trivial (>10KB)", size > 10_000))

    duration = 0.0
    ffmpeg = find_ffmpeg()
    if ffmpeg and produced.exists():
        res = subprocess.run([ffmpeg, "-i", str(produced)],
                             capture_output=True, text=True)
        for token in res.stderr.split():
            if token.startswith("Duration:"):
                continue
        for line in res.stderr.splitlines():
            if "Duration:" in line:
                hh, mm, ss = line.split("Duration:")[1].split(",")[0].strip().split(":")
                duration = int(hh) * 3600 + int(mm) * 60 + float(ss)
                break
        checks.append(("duration > 1s", duration > 1.0))

    # Negative control: a bad selector must fail loudly, not record silence.
    bad = {"viewport": {"width": 640, "height": 480},
           "steps": [{"do": "goto", "url": card.resolve().as_uri()},
                     {"do": "click", "selector": "#does-not-exist", "timeout_ms": 1500}]}
    try:
        run_shots(bad, tmp / "bad.mp4")
        checks.append(("bad selector fails loudly", False))
    except SystemExit:
        checks.append(("bad selector fails loudly", True))

    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\n  artifact: {produced}  ({size:,} bytes, {duration:.1f}s)")

    failed = [n for n, ok in checks if not ok]
    if failed:
        print(f"\nSELFTEST FAILED: {', '.join(failed)}")
        return 1
    print("\nSELFTEST PASSED")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", type=Path, help="path to a shot list JSON file")
    ap.add_argument("--out", type=Path, default=Path("demo.mp4"))
    ap.add_argument("--headed", action="store_true", help="show the browser while recording")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.shots:
        ap.error("--shots is required (or use --selftest)")

    shots = json.loads(args.shots.read_text())
    produced = run_shots(shots, args.out, headed=args.headed)
    print(f"wrote {produced} ({produced.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
