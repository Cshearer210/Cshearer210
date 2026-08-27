# Handoff prompt — paste this into a new session on the laptop

Everything below the line is written as instructions to that session.

---

I'm Chris Shearer. I need two 3-minute screen-recorded demos to send to a payment
processor who approached me about building software for them. A previous session
(running in a cloud container with no access to my machines) wrote the scripts and
tooling but could not reach the source code. You are running where the code actually
lives, so your job is to ground everything in what the code really does and then
help me record.

## Start here

The work so far is on branch `claude/demo-scripts-payment-processor-f0oas5` of
`Cshearer210/Cshearer210`, in the `demos/` directory:

    git fetch origin claude/demo-scripts-payment-processor-f0oas5
    git checkout claude/demo-scripts-payment-processor-f0oas5
    ls demos/

- `lighthouse-demo-script.md` — 5 beats, timed, 3 slots left blank
- `studio-demo-script.md` — 6 beats, complete, 6 figures need re-deriving
- `recording-runbook.md` — capture settings and data-leak checklists
- `tools/record_demo.py` — drives a web app through a JSON shot list, writes MP4
- `tools/preflight.py` — refuses a take that could leak client data
- `tools/find_integrations.py` — scans a codebase and reports every external API
- `shots/*.json` — shot lists; selectors still need filling in

All three tools have `--selftest` and all pass. Run them before trusting them.

## The two apps

**LA Lighthouse** — bookkeeping and POS with a chatbot and automation layer. The
client is a high-risk retail merchant: hemp and CBD, blue lotus, plus conventional
products. Before this system their books were sprawling, disorganized Excel sheets.

What I've told the previous session it does:
- Pulls from live Excel sheets; imports bank feeds; exports CSV/Excel
- Ingests thousands of transactions at once, categorized and propagated everywhere
- Tracks vendor payables, notifies before due dates, pays vendors directly from
  the business's bank account
- Chatbot takes plain-language instructions and actually changes data, not just
  answers questions about it
- Can integrate with Square, Stripe, or other gateways
- Uses sandboxed forced failures to find problems before they occur
- I own the software and source code. The client owns their data.

**Studio** — my production multi-agent platform. 62 agents, ~97,000 lines of Python,
three machines (Windows workstation, Ubuntu GPU server, cloud VPS), 8 autonomous
loops, local inference on a single RTX 3090, 253 self-testing scripts, a daily
harness of 118 checks against live system state.

## What I need you to do, in order

1. **Find both codebases on this machine.** I don't remember the exact paths.
   Search for the POS/bookkeeping app and the agent platform.

2. **Count the APIs in each.** This is the number I most want in the videos —
   there are quite a few in both apps.

       python3 demos/tools/find_integrations.py /path/to/lighthouse
       python3 demos/tools/find_integrations.py /path/to/studio

   It reports distinct SDKs, external hosts contacted, inbound routes, and
   credentials configured as four separate numbers. It prints credential *names*
   only, never values.

3. **Actually read enough of each codebase** to describe, accurately:
   - The single most impressive end-to-end workflow, click by click
   - What the chatbot/automation layer really does when it changes data
   - How vendor payments work mechanically — am I initiating ACH, generating a
     file the bank consumes, or driving a bank portal? A payment processor will
     ask this within a minute and I need the true answer, not a guess.
   - One real forced-failure example and what catches it

4. **Fill the three blank slots in the Lighthouse script** and **re-derive all six
   Studio figures from the live system** — agent count, line count, loop count,
   self-testing script count, daily check count, and longest continuous uptime.
   My own commit history shows these numbers going stale twice. Do not copy them
   from the script; measure them.

5. **Build a seeded demo tenant** for Lighthouse — a copy loaded with fake
   businesses, vendors, and figures — so no real client data is ever on screen.

6. **Then record**, using the runbook. Not before.

## Rules

- **Do not invent features.** If you can't confirm something from the code, ask me
  or leave it out. These videos go to a real prospect who will check.
- **Every number must come from a measurement**, not from the script and not from
  my README, both of which have been wrong before.
- **No real client data in any frame.** Run `preflight.py` before every take.
- **Don't record anything until both scripts are complete.** I want full
  understanding of both apps first.
- If you find that something in the drafted scripts misrepresents what the code
  does, fix the script — the code is the source of truth, not the draft.

## Optional but useful

I have 21 empty private repos on GitHub (all the `nored-*` ones) that were created
for a workspace migration that never ran. If it's useful to have the code reachable
from other sessions, push the two codebases there — but check for secrets first:

    git status --short | grep -iE "\.env|\.pem|\.key|credential|secret|token"
