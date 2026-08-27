# LA Lighthouse — 3-minute demo script

Bookkeeping and POS with a chatbot and automation layer, built for a **high-risk retail
merchant** — hemp/CBD, blue lotus, and conventional products — that was previously running
its books out of Excel.

**Why this matters for this pitch:** a high-risk merchant category is very likely the
reason this processor is talking to you at all. You have built the accounting and
payments backbone for exactly the kind of merchant they underwrite. That belongs in the
first twenty seconds, not buried at 2:10.

**Ownership:** you own the software and source; the client owns their data. The only
constraint on this video is that no real figures, vendors, or transactions appear.

**Hard rule:** record against the seeded demo tenant. Run `demos/tools/preflight.py`
first — it refuses a production host and fails on any denylisted term.

---

## Beat 1 — The merchant, and the mess (0:00–0:25)

**Shot:** A deliberately messy spreadsheet. Fabricated but real in shape: merged cells,
hand-typed totals, three tabs that disagree with each other.

> This is a retail business selling hemp products, botanicals, and conventional goods —
> the kind of merchant most software quietly refuses to serve. Their entire books lived
> in spreadsheets like this. Sales in one file, vendors in another, and a person
> reconciling by hand, finding mistakes weeks later if at all.

Do not name the client. "A retail business" costs you nothing and protects them.

---

## Beat 2 — Thousands of transactions, in one motion (0:25–1:10)

**Shot:** The hero shot. Drop a large file in. Let it run. Then cut to the places it
landed — ledger, categories, vendor records — without touching anything in between.

> I can drop in thousands of transactions at once.
>
> `[SLOT: say the actual number and where the file comes from — a bank export, a
> processor settlement file, a year of spreadsheet history.]`
>
> They come in categorized, reconciled, and already propagated everywhere they need to
> be. It pulls from their live spreadsheets, imports the bank feed, and exports back out
> for whoever needs a file. Nobody re-keys anything.

Show the *count* landing, not a progress bar. Volume is the argument here.

---

## Beat 3 — It knows what's owed, and pays it (1:10–1:55)

**Shot:** A vendor payment due notification, then the payment going out. Then type a
plain-language instruction and show it applied.

> It also tracks what's owed. It knows when each vendor is due, it raises that before
> the date rather than after, and it pays them directly from the business's bank account.
>
> And it takes instructions in plain language —
>
> `[SLOT: the request you'll actually type. Pick one that changes two places at once so
> the payoff is visible on screen.]`
>
> That isn't a chatbot answering questions about the data. It changes the data, applies
> the update everywhere it lands, and leaves a record of what it did.

If there's an audit entry, show it. "Who changed what, and can you prove it" is the
whole ballgame for this audience.

---

## Beat 4 — How I know it works (1:55–2:35)

**Shot:** Fault injection. Break it on purpose, on camera, and show something catch it.

> Here's what I'd want to know if I were you. I don't wait for a system holding a
> business's money to fail in production to learn how it fails. I force the failure in a
> sandbox and confirm something actually catches it.
>
> `[SLOT: one forced failure and what caught it — a malformed import, a partial payment,
> a sync that dies halfway through.]`
>
> A check nobody has ever made fail is not a check. Same idea as the two packages I've
> published, applied here to real money.

---

## Beat 5 — Close (2:35–3:00)

> Point of sale, bookkeeping, payables, and the automation between them. It's built to
> sit on top of whichever processor the merchant uses, so the gateway is a choice rather
> than a rewrite.
>
> Built solo. Running in production today. Everything you just saw was synthetic — the
> software is mine, the numbers are not.
>
> I'm Chris Shearer.

Say the synthetic-data line yourself, unprompted. It shows a processor how you treat a
client's data when nobody is watching, which is a thing they cannot easily test for.

---

## Be ready for these three questions

They will come within a minute of the video ending. Have the answer before you send it.

1. **"How do you hold the bank credentials for vendor payments?"** Anything touching ACH
   origination gets scrutiny. Know whether you're initiating transfers, generating a
   payment file the bank consumes, or driving a bank portal — the three have very
   different risk profiles and they will know the difference.
2. **"How do you handle a merchant in a restricted category?"** You have real answers
   here from actually operating it. Have them ready rather than improvising.
3. **"What happens on a partial or failed import?"** This is Beat 4 and you already have
   it. Make sure the specific example you show is one you can talk about in depth.

---

## Fill the integration list without relying on memory

Run this on the machine holding the source and paste the output back:

```bash
python3 demos/tools/find_integrations.py /path/to/lighthouse
```

It reports payment SDKs, banking and ACH libraries, accounting integrations,
spreadsheet handling, hosts contacted, and exposed webhook routes. It prints credential
**names** only, never values — the self-test plants a fake secret and asserts the value
never reaches the output, so the report is safe to paste into a chat.
