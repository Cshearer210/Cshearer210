# Demo kit — payment processor

Two 3-minute demos: Studio, and LA Lighthouse. Screen capture with voiceover.

| File | What it is | Status |
|---|---|---|
| `studio-demo-script.md` | Full narration + shot list, timed | Ready — verify the figures |
| `lighthouse-demo-script.md` | Beat structure + intake questions | Needs feature content |
| `recording-runbook.md` | Capture settings, leak checklists | Ready |
| `tools/record_demo.py` | Drives a web app, records MP4 | Self-test passing |
| `tools/preflight.py` | Refuses unsafe takes | Self-test passing |
| `shots/*.json` | Shot lists for the recorder | Templates — need selectors |

Both tools carry `--selftest`, and both self-tests include a negative control:
the recorder proves a bad selector fails loudly rather than recording silence,
and the pre-flight proves every one of its five gates can actually fire. A gate
nobody has made fail is not a gate.

## What is not done, and why

The videos themselves are not recorded. Neither app is reachable from the
environment this kit was built in: no SSH client, no credentials, no host, and
neither app in any repo on the account. The recording pipeline is built and
verified against a test page, so pointing it at a real URL is the only remaining
step.

## Data safety

LA Lighthouse's data must not appear. The approach is a seeded demo tenant —
synthetic orgs and amounts — rather than blurring in post, so there is nothing
real on screen to miss. `preflight.py` enforces it mechanically before each take.
