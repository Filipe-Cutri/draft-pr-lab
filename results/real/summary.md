# draft-pr-lab results

Repository: `Filipe-Cutri/draft-pr-lab` | collected: 2026-11-27T00:45:19Z | price: $0.006/min

## Per-arm metrics (merged PRs only)

| Metric | ctrl (always-run) | draft (draft-gated) |
|---|---:|---:|
| Merged PRs | 12 | 12 |
| Workflow runs | 59 | 78 |
| Executed runs | 59 | 19 |
| Skipped runs | 0 | 59 |
| Skipped share (%) | 0.0 | 75.6 |
| Billable minutes | 162 | 53 |
| Cost (USD) | 0.97 | 0.32 |
| Billable min / merged PR | 13.5 | 4.42 |
| Executed runs / merged PR | 4.92 | 1.58 |
| Mean billable min / executed run | 2.75 | 2.79 |
| Mean wall-clock min / executed run | 2.26 | 2.26 |
| Legacy: mean wall-clock min / run incl. skipped | 2.26 | 0.58 |

## Paired comparison (task pairs merged in both arms)

* Pairs: **12**
* Billable minutes: ctrl 162 vs draft 53
* Reduction: **67.3%** (95% bootstrap CI 59.2 to 72.9)
* Mean saving per task: 9.08 min (95% CI 6.75 to 11.33); median 9.0 min
* Draft arm cheaper or equal in 12/12 pairs
* Sign-flip permutation test, two-sided p = 0.000488

## Validity checks

* Merged PRs without a partner in the other arm: none
* Runs not yet completed: 0
* Executed runs without job timing data: 0
* Runs on unrelated branches (ignored): 14
* Runs deviating from the plan: none
