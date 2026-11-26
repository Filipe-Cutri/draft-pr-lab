# draft-pr-lab

Replication package for a study of how **GitHub Draft Pull Requests** change the
CI/CD build-minute consumption of a repository.

The repository contains a small sample project, a CI workflow that implements
both behaviours under comparison, a driver that creates real pull requests in a
**paired design**, and an analysis pipeline that measures billable minutes.

> All names in this repository are generic. Field observations that motivated
> the study come from an industrial setting and are anonymised in the paper.

## The two arms

| Arm | Branch prefix | PR opened as | Build runs when |
|---|---|---|---|
| `ctrl` (always-run) | `ctrl/` | ready for review | every `opened` / `reopened` / `synchronize` |
| `draft` (draft-gated) | `draft/` | **draft** | only while the PR is *not* a draft (`ready_for_review`, or pushes after it) |

Both arms execute the **same commit schedule** (same number of pushes and review
rounds per task), so each task yields one comparable pair. The gating lives in
one workflow, [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

```yaml
on:
  pull_request:
    types: [opened, reopened, synchronize, ready_for_review]
jobs:
  build:
    if: >-
      github.event_name == 'workflow_dispatch' ||
      startsWith(github.head_ref, 'ctrl/') ||
      github.event.pull_request.draft == false
```

A run whose job `if` is false is recorded by GitHub with conclusion `skipped`
and is not billed.

## Quick start

Requirements: Python >= 3.10, `git`, and the [GitHub CLI](https://cli.github.com/)
(`gh auth login` done).

1. **Create an empty *public* repository** on GitHub (public repositories get
   standard GitHub-hosted runner minutes for free; on a private repository the
   experiment consumes your plan's included minutes) and push this folder to
   `main`.
2. In *Settings > General > Pull Requests*, keep **squash merging** enabled.
3. *(Optional)* In *Settings > Secrets and variables > Actions > Variables*, set
   `SIMULATED_BUILD_SECONDS` (default `120`) and `SIMULATED_JITTER_SECONDS`
   (default `30`) to change how long each simulated build takes.
4. Clone it, `cd` into the clone (clean working tree, git identity configured), then:

```bash
pip install -r requirements-dev.txt -r requirements-analysis.txt

# 0. offline sanity check: unit tests + demo on synthetic data (costs nothing)
python -m pytest -q
python tools/analyze.py --data data/synthetic --out results/synthetic

# 1. see what will be created, and the expected run counts
python tools/lab.py plan --pairs 12 --seed 42

# 2. functional validation of the trigger rules (scenarios S1..S5)
python tools/lab.py scenarios
python tools/lab.py verify-scenarios          # waits for runs, PASS/FAIL per scenario

# 3. paired benchmark (about 1 h for 12 pairs with the default 20 s pause)
python tools/lab.py experiment --pairs 12 --seed 42

# 4. once all runs finished: download data and analyse
python tools/lab.py collect --out data/real
python tools/analyze.py --data data/real --out results/real
```

Add `--dry-run` before the sub-command (e.g. `python tools/lab.py --dry-run experiment`)
to print every git/gh command without executing anything.

## Scenarios (functional test plan)

| ID | Sequence | Expected (executed / skipped) |
|---|---|---|
| S1 | open normal PR, push | 2 / 0 |
| S2 | open draft PR, push | 0 / 2 |
| S3 | open draft, push, mark ready, push | 2 / 2 |
| S4 | normal PR, push, convert to draft, mark ready immediately | 3 / 0 *(observational: overlapping runs)* |
| S5 | normal PR, convert to draft, push, mark ready | 2 / 1 |

S4 reproduces the case where `synchronize` and `ready_for_review` can overlap;
its outcome is reported but not asserted.

## Metrics

* **Billable minutes**: for each executed job, `ceil(duration / 60)`; skipped
  jobs count 0. Obtained from the Actions *jobs* API.
* **Cost**: billable minutes x `--price-per-min` (default `0.006` USD, the
  standard Linux 2-core rate since 2026-01-01; earlier data used `0.008`).
* **Paired comparison**: per-task difference in billable minutes, percentile
  bootstrap 95% CI over task pairs, and an exact sign-flip permutation test.
* **Validity checks**: unpaired PRs, unfinished runs, missing job data, and any
  PR whose observed run counts deviate from the plan.

See [docs/METHODOLOGY.md](docs/METHODOLOGY.md) for design details and threats to validity.

## Layout

```
.github/workflows/ci.yml     workflow implementing both arms
src/invoice_calc/            tiny sample project (gives CI real tests to run)
tests/                       unit tests (sample app, plan, analysis, driver dry-run)
tools/plan.py                deterministic paired plan + expected run counts
tools/lab.py                 plan | scenarios | verify-scenarios | experiment | collect
tools/analyze.py             metrics, paired statistics, report, figures
tools/make_synthetic_data.py offline demo dataset (clearly marked synthetic)
data/synthetic/              SYNTHETIC demo data - not results
data/real/                   your collected data goes here
results/                     analysis outputs
```

## Important

* `data/synthetic/` and `results/synthetic/` exist only to exercise the tooling.
  Their numbers follow from the generator's assumptions and are **not** results.
* The commit schedule is scripted, so the *size* of the saving depends on the plan
  (pushes per PR, review rounds); see the methodology note.

## Citation

TODO: add the arXiv reference once available.

## License

MIT
