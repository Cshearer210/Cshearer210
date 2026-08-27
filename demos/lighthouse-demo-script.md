# LA Lighthouse — 3-minute demo script

Bookkeeping and POS system with a chatbot and automation layer, built for a retail
business that was previously running its books in sprawling, disorganized Excel sheets.

**Ownership:** Chris owns the software and source. The client owns their data. So the
only constraint on this video is that no real figures, customer names, or transactions
appear — the software itself is his to show.

**Hard rule:** record against the seeded demo tenant. Run `demos/tools/preflight.py`
first; it refuses a production host and fails on any denylisted term.

---

## Beat 1 — The before (0:00–0:20)

**Shot:** Open on a deliberately messy spreadsheet. Fabricated, but real in shape —
merged cells, a column of hand-typed totals, three tabs that disagree.

> Every number this business ran on lived in spreadsheets like this. Sales in one file,
> inventory in another, and a person reconciling them by hand — finding the mistakes
> weeks later, if at all.

Do not name the client. "A retail business" is enough, and it costs you nothing.

---

## Beat 2 — One sale, all the way through (0:20–1:20)

**Shot:** The core loop, uncut. Ring up a sale at the POS. Then cut straight to the
books updating from it. No dissolve, no jump — the point is that nothing happened in
between, because nothing needs to.

> This is the same business now. A sale goes through the register —
>
> `[SLOT: say what the operator actually does — scan, select, tender, done]`
>
> — and the books are already correct. Inventory decremented, revenue posted, the
> ledger balanced. Nobody re-keys anything into a spreadsheet at the end of the week,
> because there is no spreadsheet at the end of the week.

This is the beat that earns the video. One transaction, followed all the way to the
ledger, does more than any feature tour.

---

## Beat 3 — The chatbot and the automation layer (1:20–2:05)

**Shot:** Type a request in plain language. Let the system make the change. Show the
result on the affected screen.

> It also takes instructions in plain language.
>
> `[SLOT: the actual request you'll type — e.g. "mark the 500mg tincture as discontinued
> and move remaining stock to clearance." Pick one that touches two places at once, so
> the payoff is visible.]`
>
> That is not a chatbot answering questions about the data. It changes the data, applies
> the update everywhere it needs to land, and leaves a record of what it did.

If it writes an audit entry, show it. A payment processor reads "who changed what, and
can you prove it" as the whole ballgame.

---

## Beat 4 — Why you can trust it (2:05–2:40)

**Shot:** The fault injection. Break something on purpose, on camera, and show it caught.

> Here's the part I'd want to know about if I were you. I don't wait for this system to
> fail in production to find out how it fails. I break it on purpose, in a sandbox —
> force the error, and confirm something actually catches it.
>
> `[SLOT: name one forced failure and what caught it — a bad import, a partial payment,
> a sync that drops halfway.]`
>
> A check nobody has ever made fail isn't a check. That's the same idea as the two
> packages I've published, applied to a business's actual money.

---

## Beat 5 — Close (2:40–3:00)

> Bookkeeping, point of sale, and the automation between them. Built solo, running in
> production for a real business today.
>
> Everything you just saw was synthetic data — the system is mine, the numbers are not.
>
> I'm Chris Shearer.

Saying the synthetic-data line yourself, unprompted, does more for you than staying
quiet about it. It shows a processor how you handle a client's data when nobody is
checking.

---

## Still open

**Integrations (Beat 3 or a card at 2:05).** What it connects to is the thing a
processor most wants to know, because it tells them whether you can work inside their
stack. Recognition is easier than recall — answer from the checklist in chat rather
than trying to remember cold.

**Worth considering:** if the client sells tinctures and gummies, they may sit in a
high-risk merchant category — which is plausibly why this processor is talking to you
at all. If so, "I built the POS and books for a high-risk retailer" is the single most
relevant sentence in the whole video, and belongs in Beat 1. Confirm before leaning on it.
