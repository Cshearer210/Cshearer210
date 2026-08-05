# Christopher Shearer

AI systems engineer. I work at the harness and loop layer, not the prompt layer.

I built and run a production multi-agent platform that has operated unattended for months across
three machines: a Windows workstation, an Ubuntu GPU server, and a cloud VPS. 62 agents, roughly
97,000 lines of Python, single author. It researches, produces, verifies, and schedules real work
for two businesses I own.

The part I care most about is the layer most agent systems never get.

### Reliability and evals

Agents claim work is finished that isn't. Everything I build assumes that.

- **118 scripts carry their own selftest.** A gate is not trusted until it has been made to fail
  on purpose. A check that has never failed proves nothing.
- **A daily regression harness of 18 checks asserts against live system state, not source code.**
  Code does not decay. Reality does. A fix that quietly stopped working gets caught here rather
  than assumed to still hold.
- **UNKNOWN is a distinct result that never counts as a pass.** Absent-and-fine and
  present-and-fine must never produce the same output.
- **58 gates mechanically block non-compliant agent output before it ships**, rather than relying
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

- A memory architecture over structured records, a 5,500 note knowledge base, and a 484 document
  corpus, with a derived index rebuilt every 30 minutes and pre-compaction snapshots that persist
  open work to disk so nothing is lost when context is truncated. Retrieval returns the passage,
  not the filename.
- A code knowledge graph resolving 6,424 dependency edges across 2,779 files, so the blast radius
  of a change is queryable before the change is made.
- Context engineering under measured token budgets: I measured what always-on instructions cost
  per session, then scoped most of them to load only for the work they govern.

### Local inference

The full stack runs on a single RTX 3090: text, vision, image, video, and speech. Quantized
variants benchmarked for accuracy against latency and resident memory, keep-alive tuned to
eliminate reload stalls, and routing by task difficulty so metered APIs stay the exception,
enforced by hard daily and monthly spend caps.

### Before software

Extraction chemist, self-taught, same as the software. I was hired to commission a $500,000
cryogenic ethanol and wiped film extraction plant after three previous hires could not run it.
The documentation was in Mandarin and specified an incorrect build. I diagnosed the fault, bought
$5,000 in parts, re-plumbed the line, and took it from 200 pounds of biomass processed in two
years to 2,000 pounds per week.

Different domain, same job: figure out why the thing does not work when nobody else could, and
make it hold.

### What I am looking for

Remote, US-based, Central time. Agent reliability, evals, or infrastructure at a team small
enough that the work is still unproven. I would rather solve something nobody has solved than
attend meetings about solving it.

Austin, TX · cshearer210@gmail.com
