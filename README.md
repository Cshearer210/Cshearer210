# Christopher Shearer

AI systems engineer. I work at the harness and loop layer, not the prompt layer.

I have published two open source Python packages that ask the same question of different things:
**a check nobody has ever made fail is not a check.**

- **[claimproof](https://github.com/Cshearer210/claimproof)** stops an AI coding agent ending its
  turn on a claim it cannot back. `pip install claimproof`
- **[deadcanary](https://github.com/Cshearer210/claimproof/tree/main/packages/deadcanary)** breaks
  a dbt project's data on purpose to find the data tests that cannot fail. `pip install deadcanary`

Behind them is a production multi-agent platform I built and run, which has operated unattended
for months across three machines: a Windows workstation, an Ubuntu GPU server, and a cloud VPS.
62 agents, roughly 97,000 lines of Python, single author. It researches, produces, verifies, and
schedules real work for two businesses I own.

### What the two packages do

**claimproof reads an agent's reply before its turn can end.** It refuses a completion claim
that has no evidence near it: a test result, an exit code, a file and line, command output.
Honest hedging passes on purpose, because a gate that punishes honesty teaches agents to be
vague instead of accurate. Method and limits, for anyone evaluating it:
[FINDINGS.md](https://github.com/Cshearer210/claimproof/blob/main/FINDINGS.md).

**deadcanary asks the same question of a dbt project's data tests.** A test that has been green
every morning for two years is green for one of two reasons: the data is healthy, or the test
cannot fail, and the sentence reads identically either way. It corrupts a column on purpose,
re-runs the suite, and names the tests that never noticed.

### Reliability and evals

Agents claim work is finished that isn't. Everything I build assumes that.

- **253 scripts carry their own self-test.** A gate is not trusted until it has been made to fail
  on purpose. A check that has never failed proves nothing.
- **A daily regression harness of 118 checks asserts against live system state, not source code.**
  Code does not decay. Reality does. A fix that quietly stopped working gets caught here rather
  than assumed to still hold.
- **UNKNOWN is a distinct result that never counts as a pass.** Absent-and-fine and
  present-and-fine must never produce the same output.
- **Gates mechanically block non-compliant agent output before it ships**, rather than relying
  on the model to remember a rule.

The bug that shaped all of it: a content quality gate defaulted to passing everything once its
API budget hit zero. Weeks of output shipped ungraded and nothing alarmed, because the failure
looked exactly like success. That class of silent degradation is what I build against now.

### Loop and harness engineering

- Eight long-running autonomous loops on staggered wall-clock intervals covering self-diagnosis,
  system optimization, content generation, local model tuning, and backlog burndown.
- A loop health auditor that detects a loop which has silently stopped, because a dead loop and a
  quiet loop look identical from outside.
- Five runtime lifecycle events dispatched through one router. A pre-tool-use hook refuses writes
  that violate architectural invariants before they land. A stop hook blocks the agent from
  claiming work finished without evidence in the same turn.
- A closed self-improvement loop: the system diagnoses itself, diffs each run against the last so
  only new problems surface, authors its own change proposals, and routes them to a human
  approval interface before executing.

### Memory, graph, and context

- A memory architecture over 204 structured records, a 5,500 note knowledge base, and a 484
  document corpus, with a derived index rebuilt every 30 minutes and pre-compaction snapshots that
  persist open work to disk so nothing is lost when context is truncated. Retrieval returns the
  passage, not the filename.
- A code knowledge graph resolving 6,424 dependency edges across 2,779 files, so the blast radius
  of a change is queryable before the change is made.
- Context engineering under measured token budgets: I measured what always-on instructions cost
  per session, then scoped 63 of 73 rule files to load only for the work they govern, which saves
  roughly 155,000 tokens a session.

### Local inference

The full stack runs on a single RTX 3090: text, vision, image, video, and speech. Quantized
variants benchmarked for accuracy against latency and resident memory, keep-alive tuned to
eliminate reload stalls, and routing by task difficulty so metered APIs stay the exception,
enforced by hard daily and monthly spend caps.

### Before software

Extraction chemist, self-taught, same as the software. I was hired to commission a $500,000
cryogenic ethanol and wiped film extraction plant after three previous hires could not run it.
The documentation was in Mandarin and specified an incorrect build. I diagnosed the fault, bought
$5,000 in parts, re-plumbed the line, and brought it into continuous production for the first
time.

Different domain, same job: figure out why the thing does not work when nobody else could, and
make it hold.

### What I am looking for

Remote, US-based, Central time. Agent reliability, evals, or infrastructure at a team small
enough that the work is still unproven. I would rather solve something nobody has solved than
attend meetings about solving it.

Austin, TX · cshearer210@gmail.com
