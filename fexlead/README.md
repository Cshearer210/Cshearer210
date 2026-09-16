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

## The numbers are not yet facts

Every constant in `scoring.py` is a published industry benchmark, and most of them originate
in lead-vendor marketing material, which has an obvious incentive to inflate. They are
labeled `PRIOR_UNVALIDATED` and the label is carried onto the Provenance sheet of every
exported workbook.

They are good enough to rank leads against each other. They are not a revenue forecast.
Feed real close outcomes into `Scorer(measured_close_rates=...)` and the basis flips to
`BACKTESTED`. Until then the workbook says so on its face.

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

Four integration points are stubbed and need real providers before this dials anything:

- **DNC scrubbing** — federal plus state registries, re-scrubbed at least every 31 days.
  Set `dnc_status` and `dnc_checked_at` from the scrub, never from the vendor.
- **Litigator screening** — sets `litigator_flag`. `None` means unscreened, which holds.
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
