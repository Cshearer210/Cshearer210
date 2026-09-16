# fexlead

A compliance gate, scoring model, and call-sheet exporter for final expense insurance leads.

Built for an individual licensed producer working purchased leads. It does not acquire
leads. It takes leads you already bought, proves each one is legally callable right now,
ranks them by expected value, and writes a call sheet an agent can actually work from.

## What this deliberately does not do

It does not scrape personal data about private individuals, and it will not be adapted to.
Every record it handles originates from a consumer's own opt-in submission or from a
vendor's delivery record. Nothing about a named person is scraped, appended, or inferred.

The scoring model cannot rank anyone by age, health, bereavement, or financial distress.
That is enforced by a test, not by convention: `test_score_is_unchanged_by_the_consumers_age`
asserts that two otherwise-identical leads differing only in stated age produce byte-identical
scores and rationales. The consumer's age rides along on the record for underwriting fit and
never enters the model.

## The finding that shaped the design

Running the published benchmarks through expected value inverts the usual advice:

| Lead type              | Cost | Close | CPA  | EV per lead |
|------------------------|------|-------|------|-------------|
| Aged, 30-60 day        | $6   | ~5%   | $120 | **+$37.75** |
| Exclusive web, <5 min  | $35  | ~10%  | $350 | +$35.00     |
| Live transfer          | $110 | ~20%  | $550 | +$30.00     |
| Exclusive web, 45 min  | $35  | ~3.5% | —    | **-$10.50** |

Two things fall out of this.

The cheapest lead type has the best expected value per dollar. Live transfers have by far
the best close rate and the worst economics, because you pay for that close rate up front.
Aged leads are cheap precisely because working them requires volume and persistence that a
human producer cannot sustain — which is exactly what an automated pipeline is for.

An expensive lead worked slowly is worth less than it cost. The 45-minute row is negative.
Speed to lead is not an optimization here, it is the difference between a margin and a loss.

Both rows are asserted in `test_aged_beats_live_transfer_on_expected_value` and
`test_speed_to_lead_dominates_fresh_lead_value` rather than left as prose.

Dial order and buying decisions are different questions: rank the call sheet by `p_close`
(who is most likely to answer and buy now), but make purchasing decisions on
`expected_value_cents` (what earns most per dollar spent).

## The email channel (no prior consent required)

`email_compliance.py` covers the one outreach path that does not require prior consent.
Cold commercial email to US recipients is legal under CAN-SPAM as long as every message
carries the required disclosures and every opt-out is honored.

`validate_message` is a gate in the same shape as the call-side one. A message is sendable
only if it passes all five checks: an accurate from line, a non-deceptive subject, a clear
advertisement disclosure, a physical postal address, and a working opt-out mechanism. A
`SuppressionList` honors opt-outs immediately and offers an audit that flags any opt-out
older than the 10-business-day legal window. `EmailCampaign.send` validates the message
once and, if it fails, sends to nobody — one non-compliant message must not reach a single
recipient.

Two limits are stated in the module and repeated here. It validates *federal* CAN-SPAM
only; several states are stricter and insurance marketing has its own state content rules,
neither modeled. And legal is not the same as effective: cold email to purchased addresses
has poor deliverability and can burn a sending domain. Compliance is the floor.

The actual transport is a Protocol (`EmailSender`) with a `DryRunSender` for testing. Wire
in SMTP or an ESP the same way the scrub adapters take real providers. Per-violation
penalties run to $53,088 per email, which is why the send guard fails closed.

## The numbers are not yet facts

Every constant in `scoring.py` is a published industry benchmark, and most of them originate
in lead-vendor marketing material, which has an obvious incentive to inflate. They are
labeled `PRIOR_UNVALIDATED` and the label is carried onto the Provenance sheet of every
exported workbook.

They are good enough to rank leads against each other. They are not a revenue forecast.
Feed real close outcomes into `Scorer(measured_close_rates=...)` and the basis flips to
`BACKTESTED`. Until then the workbook says so on its face.

## How the data is verified (the accuracy question)

You cannot guarantee accuracy on data scraped about a stranger. You can verify it when
the person entered it themselves and you then check each field against an authoritative
source. That is the whole reason this pipeline is built on opt-in leads: a scraped record
has nothing to verify against, while an opt-in record carries a phone the person typed, an
email they control, and a consent certificate proving they typed it.

`verification.py` checks each contact field and grades the record:

- **Phone** — `phonenumbers` (Google's libphonenumber) confirms the number is a valid,
  assigned US number and reports its line type and area-code timezone. A malformed or
  unassigned number is BLOCK; a toll-free or premium-rate number is flagged UNKNOWN as
  implausible for a residential prospect.
- **Email** — syntax is checked offline; deliverability (does the domain accept mail) is
  checked over DNS. A DNS outage returns UNKNOWN, never PASS.
- **Address** — completeness only. Real USPS correctness needs a CASS adapter, so a
  complete-looking address is UNKNOWN-verified, not verified.

The grade (A/B/C/F) and `has_verified_channel` answer the practical question: is there a
way to reach this person that we have *verified*, not merely received. What verification
cannot tell you is whether the number still belongs to this person — that is exactly what
the DNC and Reassigned Numbers checks in the gate are for. Accuracy that could not be
confirmed is reported as UNKNOWN, the same rule the rest of the package runs on.

The phone's area-code timezone also feeds `resolve_timezone` as a fallback, so a lead in a
multi-zone state with no ZIP match still gets a calling window from its number rather than
being held as UNKNOWN.

## The compliance gate

Six checks run on every lead: consent, DNC, internal suppression, litigator screening,
calling window, and state frequency caps. A lead is callable only if all six return PASS.

The design rule is that a check which cannot run returns `UNKNOWN`, and `UNKNOWN` is never
a pass. A suppression store that times out, a DNC scrub older than the 31 days the TSR
allows, a certificate whose claim status was never established, a state whose timezone
cannot be resolved from the data present — each of these holds the lead rather than
letting it through. Absent-and-fine and present-and-fine never produce the same output.

`resolve_timezone` returns `None` rather than guessing for states that span multiple zones
and are not modeled. Kentucky resolves to UNKNOWN on purpose. Placing a call outside the
legal window because a state-level guess was wrong is a per-call statutory damages event,
not a rounding error.

Vendors are not trusted about their own leads. A payload asserting `dnc_status: clear` is
recorded as an unmapped field and the lead is marked `NOT_SCRUBBED`; a certificate URL in a
payload never implies the certificate was claimed and retained. Both are pinned by tests.

## The aged-lead certificate trap

TrustedForm certificates are permanently deleted 72 hours after creation unless someone
claims or extends them. This is the thing that can quietly break the aged-lead strategy.

If the originating vendor never claimed the certificate, the URL riding on a 60-day-old
lead is a dead link, and the consent behind it is unprovable the moment anyone asks. The
lead looks fully documented in a spreadsheet and is worth nothing in a defense.

The gate distinguishes three states rather than two. Inside the 72-hour window an
unclaimed certificate is UNKNOWN, because someone can still go claim it. Past the window
it is BLOCK, because it is gone and no amount of asking recovers it. A Jornaya LeadiD is
not subject to this rule and is not treated as if it were.

The purchasing consequence: before buying any aged list, ask the vendor whether they
claimed and retained the certificates, and whether they will transfer them. A vendor who
cannot answer is selling records whose consent cannot be proven.

## What the compliance stack actually costs

Per-seat, for one producer. Current as of September 2026.

| Item | Cost | Notes |
|---|---|---|
| National DNC Registry | free for 5 area codes | $85/area code in FY2027, $23,425 nationwide cap |
| Reassigned Numbers Database | $10/mo for 1,000 queries | FCC safe harbor, but only if you actually query it |
| TrustedForm | $10/mo minimum, ~$0.12-0.15/cert | claim within 72h or it is gone |
| Litigator scrub | bundled with most scrub vendors | |
| Internal suppression list | free | you maintain it, and it is required regardless |

FY2027 fees take effect October 1, 2026.

A producer working a handful of states stays inside the five free area codes and pays
almost nothing for DNC access. The Reassigned Numbers Database is the cheapest real
liability reduction available at $10/month, and its safe harbor only protects callers who
actually queried it, which is why the gate treats an unqueried number as UNKNOWN.

## Every gate is made to fail on purpose

`tests/test_gate_fails_on_purpose.py` ends with a meta-test that records every
`(check, status)` pair observed across the suite and asserts that all six checks were seen
returning PASS, BLOCK, and UNKNOWN at least once.

Verified to bite in both directions: deleting a single failure test fails the meta-test
naming the uncovered status, and adding a new always-passing check to the gate fails it
naming both missing statuses. A check nobody has made fail is not a check.

## Running it

```
pip install openpyxl pytest
PYTHONPATH=src python3 -m fexlead.cli --out call_sheet.xlsx --count 100
PYTHONPATH=src python3 -m pytest tests/ -q
```

`--at 2026-09-16T17:00:00+00:00` evaluates against a chosen instant. Calling-window results
depend on it, and running at 3am correctly produces zero callable leads.

The demo runs on synthetic data from `sample.py`. Phone numbers are drawn from the
NPA-555-01XX range reserved for fiction and emails use example.com. No record corresponds
to a real person. It is a schema exerciser, not a lead source.

## Wiring in real leads

Replace `generate()` in `cli.py` with `intake.from_csv()` or `intake.from_payloads()`.
Nothing downstream changes.

The scrub step lives in `scrub.py`. `ScrubRunner` applies three adapters to a batch of
leads and fills their compliance fields, recording clean and failed counts separately.
Reference in-memory adapters (`InMemoryDNC`, `InMemoryLitigator`, `InMemoryReassigned`)
make the pipeline runnable today; swapping in real providers is a one-line change per
adapter and nothing downstream moves.

The governing rule is at the adapter boundary: a lookup that cannot complete must **raise**,
never return a clean-looking default. `ScrubRunner` catches the raise and leaves the field
unscrubbed, which the gate reads as UNKNOWN. A provider outage degrades to "we do not know",
never to "everyone is clear" — the same failure this package exists to prevent, enforced
where real outages actually happen. `test_dnc_outage_leaves_lead_unscrubbed_not_clear`
pins it.

Real providers to implement against the adapter Protocols:

- **`DNCAdapter`** — Blacklist Alliance, PossibleNOW, or DNC.com. Federal plus state
  registries, re-scrubbed at least every 31 days. Many bundle litigator scrub in the same
  call.
- **`LitigatorAdapter`** — usually the same vendor as DNC. `None` means unscreened, which holds.
- **`ReassignedAdapter`** — the FCC Reassigned Numbers Database via SomosGov ($10/mo for the
  extra-small tier). The safe harbor attaches only to numbers you actually query, which is
  why an unqueried number is UNKNOWN.

Two integration points remain live-lookup rather than batch-scrub, because they must be
checked at call time, not the night before:

- **Suppression store** — implement `SuppressionSource.contains`. It must raise rather than
  return an empty set when unreachable, or you rebuild the bug this whole design is against.
- **Call history** — implement `CallHistorySource.calls_in_last_24h` for the Florida and
  Oklahoma three-calls-per-24-hours caps.

A ZIP-to-timezone dataset would also shrink the `calling_window` UNKNOWN bucket, which is
otherwise the largest source of avoidable holds.

## Output

Four sheets. The second one is the point.

- **Call List** — cleared every check, ranked by close probability, with the local calling
  window and the reasoning behind each score.
- **Held** — everything that did not clear, with the specific failing check. Nothing is
  dropped silently. BLOCK and UNKNOWN are colored differently because they are different
  problems: "is on the federal DNC registry" is a loss, "has not been scrubbed yet" is a
  work item.
- **Hold Summary** — holds grouped by cause with the remedy for each, so the fixable bulk
  is visible at a glance.
- **Provenance** — where the scoring numbers came from and what they are not.

Callable status is point-in-time. Windows close, scrubs go stale at 31 days, consent gets
revoked. Re-run the gate against a live scrub before each calling session.

## Regulatory context

Not legal advice; confirm with counsel and with the carrier's own marketing rules.

- TCPA prior express written consent is required. The FCC's one-to-one consent rule was
  vacated by the Eleventh Circuit in *Insurance Marketing Coalition v. FCC* (Jan 24, 2025)
  and formally removed later that year, so the standard reverted to the pre-2023 form.
  Vendor compliance pages still asserting a one-to-one requirement are out of date.
- Statutory damages run $500 per call, trebled for willful violations.
- The FTC Telemarketing Sales Rule requires re-scrubbing the national registry at least
  every 31 days.
- Florida (FTSA), Oklahoma (OTSA), and Maryland carry mini-TCPA statutes with private
  rights of action, stricter calling windows, and daily per-subject call caps.
- Consent revocation must be honored within 10 business days via any reasonable method.
