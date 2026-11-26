#!/usr/bin/env python3
"""Analyse a draft-pr-lab dataset (real or synthetic).

Input  (--data DIR):  prs.json, runs.json, meta.json   [manifest.json optional]
Output (--out DIR):   summary.json, summary.md, per_pair.csv, figures/*.png (if matplotlib)

Key differences from a naive wall-clock analysis
------------------------------------------------
* Cost is measured in BILLABLE minutes: each executed job is rounded up to
  whole minutes, skipped jobs cost 0 (this is how GitHub meters Actions).
* Per-run averages are computed over EXECUTED runs only. Averaging over all
  runs lets near-zero-duration skipped runs dilute the mean, which would make
  "average minutes per run" look better without any build getting faster.
  The diluted figure is still reported (as `legacy_*`) for comparison.
* The comparison is PAIRED: both arms executed the same commit schedule, so
  the unit of analysis is the task pair, not the pooled run.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ARMS = ("ctrl", "draft")
BRANCH_RE = re.compile(r"^(ctrl|draft)/(TASK-\d+)(?:-|$)")
DEFAULT_PRICE = 0.006   # USD/min, Linux 2-core standard runner (rate in force since Jan 2026)


# --------------------------------------------------------------------------- #
# Basic helpers
# --------------------------------------------------------------------------- #
def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def job_billable_minutes(job):
    """Whole minutes billed for one job (0 if skipped / unfinished)."""
    if job.get("conclusion") in (None, "", "skipped"):
        return 0
    started, completed = job.get("started_at"), job.get("completed_at")
    if not started or not completed:
        return 0
    seconds = (parse_ts(completed) - parse_ts(started)).total_seconds()
    return math.ceil(seconds / 60) if seconds > 0 else 0


def enrich_run(run):
    m = BRANCH_RE.match(run.get("headBranch", ""))
    if not m:
        return None
    arm, task = m.groups()
    conclusion = run.get("conclusion") or ""
    executed = conclusion not in ("skipped", "")
    created = parse_ts(run["createdAt"])
    updated = parse_ts(run["updatedAt"])
    return {
        "arm": arm, "task": task, "conclusion": conclusion, "executed": executed,
        "status": run.get("status", ""),
        "wall_min": (updated - created).total_seconds() / 60,
        "billable_min": sum(job_billable_minutes(j) for j in run.get("jobs", [])),
        "has_jobs": bool(run.get("jobs")),
    }


def _div(a, b):
    return a / b if b else 0.0


def mean(xs):
    return _div(sum(xs), len(xs))


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


# --------------------------------------------------------------------------- #
# Statistics (stdlib only)
# --------------------------------------------------------------------------- #
def sign_flip_p(diffs, seed=1, mc_resamples=50000):
    """Two-sided sign-flip permutation test on the mean paired difference."""
    n = len(diffs)
    observed = abs(sum(diffs))
    if n == 0 or all(abs(d) < 1e-12 for d in diffs):
        return 1.0
    if n <= 16:
        hits = 0
        for mask in range(1 << n):
            s = 0.0
            for i in range(n):
                s += diffs[i] if (mask >> i) & 1 else -diffs[i]
            if abs(s) >= observed - 1e-9:
                hits += 1
        return hits / (1 << n)
    rng = random.Random(seed)
    hits = 0
    for _ in range(mc_resamples):
        s = sum(d if rng.random() < 0.5 else -d for d in diffs)
        if abs(s) >= observed - 1e-9:
            hits += 1
    return (hits + 1) / (mc_resamples + 1)


def bootstrap_ci(ctrl, draft, seed=1, resamples=10000):
    """Percentile 95% CIs (resampling task pairs) for mean difference and % reduction."""
    n = len(ctrl)
    rng = random.Random(seed)
    mean_diffs, reductions = [], []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        sc = sum(ctrl[i] for i in idx)
        sd = sum(draft[i] for i in idx)
        mean_diffs.append((sc - sd) / n)
        reductions.append(100 * _div(sc - sd, sc))
    lo, hi = int(0.025 * resamples), int(0.975 * resamples) - 1
    mean_diffs.sort()
    reductions.sort()
    return ((mean_diffs[lo], mean_diffs[hi]), (reductions[lo], reductions[hi]))


# --------------------------------------------------------------------------- #
# Core analysis
# --------------------------------------------------------------------------- #
def arm_metrics(runs, n_prs, price):
    executed = [r for r in runs if r["executed"]]
    skipped = [r for r in runs if r["conclusion"] == "skipped"]
    billable = sum(r["billable_min"] for r in runs)
    return {
        "prs_merged": n_prs,
        "runs_total": len(runs),
        "runs_executed": len(executed),
        "runs_skipped": len(skipped),
        "skipped_share_pct": round(100 * _div(len(skipped), len(runs)), 1),
        "conclusions": dict(Counter(r["conclusion"] or "in_progress" for r in runs)),
        "billable_minutes": billable,
        "cost_usd": round(billable * price, 2),
        "billable_min_per_pr": round(_div(billable, n_prs), 2),
        "executed_runs_per_pr": round(_div(len(executed), n_prs), 2),
        "mean_billable_min_per_executed_run": round(mean([r["billable_min"] for r in executed]), 2),
        "mean_wall_min_per_executed_run": round(mean([r["wall_min"] for r in executed]), 2),
        "legacy_mean_wall_min_per_run_incl_skipped": round(mean([r["wall_min"] for r in runs]), 2),
        "executed_without_job_data": sum(1 for r in executed if not r["has_jobs"]),
    }


def paired_stats(pairs, seed=1, resamples=10000):
    n = len(pairs)
    if n == 0:
        return {"n_pairs": 0}
    ctrl = [p["ctrl_billable_min"] for p in pairs]
    draft = [p["draft_billable_min"] for p in pairs]
    diffs = [c - d for c, d in zip(ctrl, draft)]
    (md_lo, md_hi), (red_lo, red_hi) = bootstrap_ci(ctrl, draft, seed, resamples)
    return {
        "n_pairs": n,
        "billable_ctrl_total": sum(ctrl),
        "billable_draft_total": sum(draft),
        "reduction_pct": round(100 * _div(sum(ctrl) - sum(draft), sum(ctrl)), 1),
        "reduction_pct_ci95": [round(red_lo, 1), round(red_hi, 1)],
        "mean_diff_min": round(mean(diffs), 2),
        "mean_diff_min_ci95": [round(md_lo, 2), round(md_hi, 2)],
        "median_diff_min": round(median(diffs), 2),
        "pairs_draft_cheaper_or_equal": sum(1 for d in diffs if d >= 0),
        "sign_flip_p_two_sided": round(sign_flip_p(diffs, seed), 6),
    }


def analyze(prs, runs, price=DEFAULT_PRICE, seed=1, resamples=10000, manifest=None):
    merged = {}
    for pr in prs:
        m = BRANCH_RE.match(pr.get("headRefName", ""))
        if m and pr.get("state") == "MERGED":
            merged[(m.group(1), m.group(2))] = pr

    runs_by = defaultdict(list)
    ignored = 0
    for raw in runs:
        r = enrich_run(raw)
        if r is None:
            ignored += 1
        else:
            runs_by[(r["arm"], r["task"])].append(r)

    arms = {}
    for arm in ARMS:
        keys = [k for k in merged if k[0] == arm]
        arm_runs = [r for k in keys for r in runs_by.get(k, [])]
        arms[arm] = arm_metrics(arm_runs, len(keys), price)

    tasks = sorted({t for a, t in merged if a == "ctrl"} & {t for a, t in merged if a == "draft"})
    pairs = []
    for t in tasks:
        row = {"task": t}
        for arm in ARMS:
            rs = runs_by[(arm, t)]
            row[f"{arm}_billable_min"] = sum(r["billable_min"] for r in rs)
            row[f"{arm}_executed"] = sum(1 for r in rs if r["executed"])
            row[f"{arm}_skipped"] = sum(1 for r in rs if r["conclusion"] == "skipped")
        row["saved_min"] = row["ctrl_billable_min"] - row["draft_billable_min"]
        pairs.append(row)

    checks = {
        "merged_prs_without_partner": sorted(
            f"{a}/{t}" for (a, t) in merged
            if t not in tasks),
        "runs_ignored_other_branches": ignored,
        "runs_not_completed": sum(1 for rs in runs_by.values() for r in rs if r["status"] != "completed"),
        "executed_runs_without_job_data": sum(a["executed_without_job_data"] for a in arms.values()),
        "plan_mismatches": [],
    }
    if manifest:
        for rec in manifest.get("prs", []):
            rs = runs_by.get((rec["arm"], rec["task"]), [])
            obs = (sum(1 for r in rs if r["executed"]), sum(1 for r in rs if r["conclusion"] == "skipped"))
            exp = (rec["expected_executed"], rec["expected_skipped"])
            if obs != exp:
                checks["plan_mismatches"].append(
                    {"branch": rec["branch"], "expected": list(exp), "observed": list(obs)})

    return {"price_per_min_usd": price, "arms": arms, "pairs": pairs,
            "paired": paired_stats(pairs, seed, resamples), "checks": checks}


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def render_markdown(result, meta):
    a, p, chk = result["arms"], result["paired"], result["checks"]
    lines = []
    if meta.get("synthetic"):
        lines += ["> **SYNTHETIC DATA** - generated by `tools/make_synthetic_data.py` to exercise the",
                  "> tooling. These numbers are NOT experimental results.", ""]
    lines += [f"# draft-pr-lab results", "",
              f"Repository: `{meta.get('repo', 'n/a')}` | collected: {meta.get('collected_at', 'n/a')} "
              f"| price: ${result['price_per_min_usd']}/min", "",
              "## Per-arm metrics (merged PRs only)", "",
              "| Metric | ctrl (always-run) | draft (draft-gated) |", "|---|---:|---:|"]
    rows = [
        ("Merged PRs", "prs_merged"), ("Workflow runs", "runs_total"),
        ("Executed runs", "runs_executed"), ("Skipped runs", "runs_skipped"),
        ("Skipped share (%)", "skipped_share_pct"),
        ("Billable minutes", "billable_minutes"), ("Cost (USD)", "cost_usd"),
        ("Billable min / merged PR", "billable_min_per_pr"),
        ("Executed runs / merged PR", "executed_runs_per_pr"),
        ("Mean billable min / executed run", "mean_billable_min_per_executed_run"),
        ("Mean wall-clock min / executed run", "mean_wall_min_per_executed_run"),
        ("Legacy: mean wall-clock min / run incl. skipped", "legacy_mean_wall_min_per_run_incl_skipped"),
    ]
    for label, key in rows:
        lines.append(f"| {label} | {a['ctrl'][key]} | {a['draft'][key]} |")

    lines += ["", "## Paired comparison (task pairs merged in both arms)", ""]
    if p["n_pairs"] == 0:
        lines.append("No complete pairs yet.")
    else:
        lines += [
            f"* Pairs: **{p['n_pairs']}**",
            f"* Billable minutes: ctrl {p['billable_ctrl_total']} vs draft {p['billable_draft_total']}",
            f"* Reduction: **{p['reduction_pct']}%** (95% bootstrap CI {p['reduction_pct_ci95'][0]} to "
            f"{p['reduction_pct_ci95'][1]})",
            f"* Mean saving per task: {p['mean_diff_min']} min (95% CI {p['mean_diff_min_ci95'][0]} to "
            f"{p['mean_diff_min_ci95'][1]}); median {p['median_diff_min']} min",
            f"* Draft arm cheaper or equal in {p['pairs_draft_cheaper_or_equal']}/{p['n_pairs']} pairs",
            f"* Sign-flip permutation test, two-sided p = {p['sign_flip_p_two_sided']}",
        ]
    lines += ["", "## Validity checks", "",
              f"* Merged PRs without a partner in the other arm: {chk['merged_prs_without_partner'] or 'none'}",
              f"* Runs not yet completed: {chk['runs_not_completed']}",
              f"* Executed runs without job timing data: {chk['executed_runs_without_job_data']}",
              f"* Runs on unrelated branches (ignored): {chk['runs_ignored_other_branches']}",
              f"* Runs deviating from the plan: {len(chk['plan_mismatches']) or 'none'}"]
    for mm in chk["plan_mismatches"]:
        lines.append(f"  * `{mm['branch']}` expected (exec, skip) {mm['expected']} observed {mm['observed']}")
    return "\n".join(lines) + "\n"


def write_figures(result, out_dir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping figures (pip install -r requirements-analysis.txt)")
        return []
    fig_dir = Path(out_dir) / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    pairs = result["pairs"]
    written = []

    fig, ax = plt.subplots(figsize=(5, 4))
    totals = [result["arms"][arm]["billable_minutes"] for arm in ARMS]
    ax.bar(["ctrl\n(always-run)", "draft\n(draft-gated)"], totals, color=["#8a8a8a", "#2f7d5b"])
    for i, v in enumerate(totals):
        ax.text(i, v, str(v), ha="center", va="bottom")
    ax.set_ylabel("Billable minutes")
    ax.set_title("Total billable minutes (merged PRs)")
    fig.tight_layout()
    path = fig_dir / "total_billable_minutes.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    if pairs:
        fig, ax = plt.subplots(figsize=(6, 4.5))
        for i, row in enumerate(pairs):
            ax.plot([row["ctrl_billable_min"], row["draft_billable_min"]], [i, i], color="#bbbbbb", zorder=1)
        ax.scatter([r["ctrl_billable_min"] for r in pairs], range(len(pairs)),
                   color="#8a8a8a", label="ctrl", zorder=2)
        ax.scatter([r["draft_billable_min"] for r in pairs], range(len(pairs)),
                   color="#2f7d5b", label="draft", zorder=2)
        ax.set_yticks(range(len(pairs)))
        ax.set_yticklabels([r["task"] for r in pairs], fontsize=7)
        ax.set_xlabel("Billable minutes per task")
        ax.set_title("Paired comparison per task")
        ax.legend()
        fig.tight_layout()
        path = fig_dir / "paired_per_task.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        written.append(path)
    return written


def write_outputs(result, meta, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps({"meta": meta, **result}, indent=2))
    (out / "summary.md").write_text(render_markdown(result, meta))
    with open(out / "per_pair.csv", "w", newline="") as fh:
        fields = ["task", "ctrl_billable_min", "draft_billable_min", "saved_min",
                  "ctrl_executed", "draft_executed", "ctrl_skipped", "draft_skipped"]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in result["pairs"]:
            writer.writerow({k: row[k] for k in fields})
    write_figures(result, out)


def load_dir(data_dir):
    d = Path(data_dir)
    prs = json.loads((d / "prs.json").read_text())
    runs = json.loads((d / "runs.json").read_text())
    meta_file = d / "meta.json"
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
    man_file = d / "manifest.json"
    manifest = json.loads(man_file.read_text()) if man_file.exists() else None
    return prs, runs, meta, manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/real", help="directory with prs.json / runs.json")
    ap.add_argument("--out", default="results/real", help="output directory")
    ap.add_argument("--price-per-min", type=float, default=DEFAULT_PRICE,
                    help=f"USD per billable minute (default {DEFAULT_PRICE}, Linux 2-core since 2026-01-01)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--bootstrap", type=int, default=10000)
    args = ap.parse_args(argv)

    prs, runs, meta, manifest = load_dir(args.data)
    result = analyze(prs, runs, args.price_per_min, args.seed, args.bootstrap, manifest)
    write_outputs(result, meta, args.out)
    print(render_markdown(result, meta))
    print(f"Outputs written to {args.out}/")


if __name__ == "__main__":
    main()
