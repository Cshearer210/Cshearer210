# Studio — 3-minute demo script

**Audience:** payment processor evaluating you for contract software work.
**Format:** screen capture + voiceover.
**Narration length:** ~350 words / ~2:20 spoken. That is deliberate — narration should
run *under* the video length so shots can breathe. Do not pad it to fill 3:00.

Every figure below is tagged `[VERIFY]`. Your own commit history shows these numbers going
stale twice (`correct three stale figures`, `Drop the processing volumes`). Re-derive each
one the morning you record, not from this file and not from the README.

---

## Beat 1 — Cold open: the failure that looks like success (0:00–0:20)

**Shot:** A terminal scrolling a green PASS. Hold on it. No cuts.

> This is a content quality gate reporting a pass. It graded nothing. Its API budget had
> hit zero, and it defaulted to passing everything. Weeks of output shipped ungraded and
> nothing alarmed — because the failure looked exactly like success.
>
> Everything I'm about to show you was built against that.

**Why this open:** a processor's worst night is a reconciliation that silently stopped
reconciling. Lead with the failure mode they already lose sleep over, not with your stack.

---

## Beat 2 — What the system is (0:20–0:45)

**Shot:** Architecture view or a three-pane terminal, one per host. They should *see* three
machines. If you have no diagram, split-screen three SSH sessions with the hostnames visible.

> This is Studio. Sixty-two agents `[VERIFY]` across three machines — a Windows workstation,
> an Ubuntu GPU box, and a cloud VPS. Roughly ninety-seven thousand lines of Python `[VERIFY]`.
> It has run unattended for months, doing real work for two businesses I own.
>
> One author. Me.

**Note:** "One author. Me." lands harder as a two-beat pause than as a clause. Let it sit.

---

## Beat 3 — Automation depth (0:45–1:20)

**Shot:** Loop dashboard or scheduler output showing staggered next-run times. Then a scraper
run producing structured records. Then `nvidia-smi` or your model router with a local model resident.

> It runs eight autonomous loops `[VERIFY]` on staggered intervals — research, content,
> optimization, backlog burndown. Python scrapers pull sources on schedule and hand structured
> records downstream. Inference runs local, on a single 3090 — text, vision, speech — routed by
> task difficulty so metered APIs stay the exception, under hard daily and monthly spend caps.

**Do not** narrate the scraping targets by name if any are contractual. Show the shape of the
output, not the source list.

---

## Beat 4 — Reliability, the core of the pitch (1:20–2:05)

**Shot:** This is the money shot. Break something on purpose, on camera. Corrupt a column,
run the suite, show the test that *should* have caught it and didn't. Then show it caught after
the fix. If you show one thing in this video, show this.

> Here's the part that matters for you. Two hundred and fifty-three scripts `[VERIFY]` carry
> their own self-test, and no gate is trusted until it has been made to fail on purpose.
>
> A daily harness runs a hundred and eighteen checks `[VERIFY]` against live system state, not
> source code — because code doesn't decay, reality does.
>
> UNKNOWN is its own result, and it never counts as a pass.
>
> And gates block non-compliant output mechanically, before it ships — not by asking a model
> to remember a rule.

---

## Beat 5 — Why that transfers to payments (2:05–2:35)

**Shot:** Audit trail, approval interface, or the human-approval routing step.

> That discipline is the whole job in payments. A reconciliation that silently stops
> reconciling reads exactly like one that balances. A retry that double-charges and a retry
> that correctly no-ops look identical in a log that wasn't built to tell them apart.
>
> I build the log that tells them apart — and then I prove it by breaking it on purpose.

**Honesty guard:** this beat claims a *transferable property*, not a shipped payments feature.
Keep it that way. If they ask "have you built settlement reconciliation," the answer is what it
is. Do not let the script imply otherwise — a processor will check, and being caught inflating
here costs you the contract that the rest of the video just won.

---

## Beat 6 — Close (2:35–3:00)

**Shot:** The two PyPI pages, or `pip install claimproof` running clean.

> Two of these ideas are public — claimproof and deadcanary, both on PyPI. Same question in
> both: a check nobody has ever made fail is not a check.
>
> If you have internal tooling nobody has had time to staff, that's the work I want.
>
> I'm Chris Shearer.

---

## Figures to re-derive before recording

| Claim in script | Source of truth | Confirmed |
|---|---|---|
| 62 agents | agent registry count | ☐ |
| ~97,000 lines of Python | `cloc` / `tokei` over the platform | ☐ |
| 8 autonomous loops | scheduler config | ☐ |
| 253 self-testing scripts | self-test discovery run | ☐ |
| 118 daily checks | regression harness manifest | ☐ |
| "months unattended" | oldest continuous loop uptime | ☐ |

If a number has moved, change the narration — do not round toward the more impressive figure.
