# Methodology and threats to validity

## Question

How many CI minutes does a draft-gated pull-request workflow avoid compared with a
workflow that builds on every push, and does the mechanism behave as documented?

## Design

* **Paired, randomised-order design.** Each task has a fixed commit schedule
  (`wip_commits`, then zero to two review rounds of one or two commits). It is
  executed once on a `ctrl/` branch and once on a `draft/` branch. The order of the
  two arms within a pair is shuffled with a fixed seed. The plan is regenerated
  deterministically from `--seed`, so it can be reproduced exactly.
* **One workflow, one build definition.** Only the gating condition differs between arms.
* **Draft arm protocol.** Open as draft, push while draft (skipped), mark *Ready for
  review* (one executed run), and for every review round convert back to draft, push,
  and mark ready again.

## Expected run counts (by construction)

For a task with `P` total pushes and `R` review rounds:

| Arm | Executed runs | Skipped runs |
|---|---:|---:|
| ctrl | `P` | 0 |
| draft | `1 + R` | `P` |

`tools/analyze.py` compares observed counts with these expectations when
`manifest.json` is present and lists every deviation.

## Measurement

* Billable minutes come from the jobs endpoint: `ceil((completed_at - started_at) / 60)`
  per executed job; skipped jobs are 0.
* Only **merged** PRs are included, and only task pairs merged in **both** arms enter the
  paired comparison.
* Per-run averages use **executed** runs. Averaging over all runs (including skipped ones,
  whose duration is about zero) lowers the mean without any build becoming faster; that
  figure is kept in the output as `legacy_*` for transparency.

## Differences from an observational field analysis

| Field analysis (before/after periods) | This package |
|---|---|
| Wall-clock `updatedAt - createdAt` (includes queueing) | Billable job minutes (what GitHub meters) |
| Mean per run includes skipped runs | Mean per executed run; legacy figure reported separately |
| Two time periods, different PR sets | Same tasks in both arms (paired) |
| Selection by keyword in PR title | Selection by branch prefix |
| Point estimates | Bootstrap CI and permutation test |
| Fixed price constant | Price is a parameter (rates changed on 2026-01-01) |

## Threats to validity

* **Synthetic workload.** The expensive step is a `sleep`, so absolute minutes say
  nothing about real build systems. What transfers is the *run-count mechanism* and
  the measurement method.
* **Scripted behaviour.** The saving is largely determined by the plan (pushes per PR,
  review rounds). Real developers may push more or fewer times, forget to open PRs as
  draft, or not convert back to draft after review. The experiment validates the
  mechanism and the pipeline; it does not estimate adoption behaviour.
* **Overlapping runs.** Marking a PR ready right after a push can start overlapping runs
  (scenario S4). A `concurrency` group could cancel them but would change what is measured.
* **Runner variance.** Queue time and runner speed vary; billable minutes are less sensitive
  to queueing than wall-clock time but not immune.
* **Small samples.** With few pairs the permutation test has limited resolution
  (minimum two-sided p = 2 / 2^n for exact tests).
