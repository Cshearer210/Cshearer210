# LA Lighthouse — 3-minute demo script (structure + intake)

**Status: skeleton.** I have no access to this app — it is not in any repo on your
GitHub account and not on this machine. The beat structure, timing, and safety
constraints below are done. The feature content needs the intake at the bottom.

**Hard constraint:** record against the seeded demo tenant only. Run
`demos/tools/preflight.py` first; it refuses production hosts and denylisted terms.

---

## Beat 1 — Frame it as their problem (0:00–0:20)

**Shot:** the app's primary working screen, already loaded, nothing clicked yet.

> `[SLOT: the operational problem this app solves, in one sentence, stated as a
> cost — hours lost, errors caught late, a manual reconciliation someone does by
> hand every Friday.]`
>
> This is the tool I built for it.

Do not open with "this is a dashboard I built." Open with the cost it removes.

---

## Beat 2 — The one workflow that proves it (0:20–1:30)

**Shot:** one task, start to finish, no cuts. Resist showing three features shallowly.

> `[SLOT: narrate the single highest-value workflow end to end. What goes in,
> what the system does, what comes out, and how long it used to take.]`

Say the words "everything on screen is synthetic" once, here, plainly. A payment
processor will respect that you said it before they had to ask.

---

## Beat 3 — Integration surface (1:30–2:15)

**Shot:** the boundary — API calls, imports/exports, whatever it talks to.

> `[SLOT: what it connects to and how. Systems of record, file drops, webhooks,
> auth model. This is the beat a processor cares most about, because it tells them
> whether you can work inside their stack instead of beside it.]`

---

## Beat 4 — How it fails safely (2:15–2:45)

**Shot:** cause a real error on camera. Bad input, dropped connection, whatever
is honest. Show it being caught.

> `[SLOT: what happens when it breaks. What surfaces, what alarms, what never
> silently passes.]`

This is the beat that connects to the Studio video and to your two packages.
Same argument, different app: a check nobody has made fail is not a check.

---

## Beat 5 — Close (2:45–3:00)

> Built solo, in production, running today. If you have something like this
> nobody's had time to staff, that's the work I want.

---

## Intake — what I need to finish this

1. What does the app do, in one sentence, for someone who has never seen it?
2. Who uses it, and what did they do before it existed?
3. The single most impressive workflow, click by click.
4. What it integrates with (APIs, imports, auth).
5. What its most interesting failure mode is, and what catches it.
6. Does the seeded demo tenant exist yet, or does it still need building?
7. Is there anything in your agreement with LA Lighthouse covering the *software*
   itself, not just their data? The synthetic-data plan handles the data cleanly.
   Whether you can show a client's commissioned product to another prospect is a
   separate question, and worth being sure of before this leaves your outbox.
