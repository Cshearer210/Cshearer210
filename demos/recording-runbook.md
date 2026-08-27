# Recording runbook

Two ways to shoot these. The automated path is preferred for anything containing
client data, because it cannot capture a notification, a browser tab title, or an
autocomplete dropdown — it records the page viewport only.

## Path A — automated (preferred)

```bash
pip install playwright imageio-ffmpeg

# 1. Prove the recorder works before you need it
python3 demos/tools/record_demo.py --selftest

# 2. Prove the take is safe. Refuses production hosts and denylisted terms.
python3 demos/tools/preflight.py \
    --shots demos/shots/lighthouse.json \
    --denylist ~/private/real-names.txt \
    --require-host demo.internal

# 3. Record
export DEMO_PASSWORD='...'          # never in the shot list
python3 demos/tools/record_demo.py --shots demos/shots/lighthouse.json \
    --out lighthouse-demo.mp4
```

If Playwright's bundled chromium mismatches the pip package, pin the binary — the
script already does this via `CHROME`. Do not run `playwright install`.

## Path B — manual capture (OBS)

Use only for things a browser cannot drive: desktop apps, terminals, GPU monitors.

- 1920x1080, 30fps, ~8 Mbps, H.264, MP4.
- Capture a **single window**, never full display. Full display is how a Slack
  toast with a real client name ends up in the file.
- Record system audio off. Narrate in a second pass over the silent capture.

### Pre-flight for manual takes — all of it, every time

- [ ] Do Not Disturb on. Slack, Mail, Signal, calendar alerts fully quit.
- [ ] Fresh browser profile. No history, no autocomplete, no saved passwords, no
      extra tabs. Bookmark bar hidden.
- [ ] Signed into the demo tenant only. Sign out of the real one entirely.
- [ ] Desktop wallpaper and visible filenames clean.
- [ ] Second monitor disconnected or mirrored.
- [ ] Trial run of the exact click path, unrecorded, watching for anything real.

### Post-flight, before it leaves your machine

- [ ] Scrub the entire file at 2x, watching for a real name in a tooltip, a
      breadcrumb, a browser tab, a chart label, a URL.
- [ ] Check the URL bar in every frame where it is visible.
- [ ] Confirm the filename and MP4 metadata carry nothing real.
- [ ] Have a second person watch it if one is available.

## Narration

Record narration separately, after the video is locked. Reading while clicking
produces both a worse read and worse clicking.

Do three takes of the whole script and pick per-beat. Leave 0.5s of silence at
each beat boundary so a swap is clean.

## Delivery

- MP4, H.264, under 100 MB. Unlisted link beats an attachment — attachments to a
  payment processor get quarantined by their mail filter.
- Put the one-sentence pitch in the email body. Assume they watch 40 seconds.
