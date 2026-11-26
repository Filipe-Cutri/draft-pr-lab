#!/usr/bin/env python3
"""Driver for the draft-pr-lab experiments (uses git + the GitHub CLI).

Sub-commands
------------
plan                Print the deterministic experiment plan and expected run counts.
scenarios           Run the functional trigger scenarios (S1..S5).
verify-scenarios    Compare what GitHub actually ran against the scenario expectations.
experiment          Run the paired benchmark (ctrl arm vs draft arm).
collect             Download PRs, workflow runs and per-job timings as JSON.

Run from inside a local clone of the lab repository, authenticated with
`gh auth login`. Add --dry-run (before the sub-command) to print every command
without executing anything.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import plan as planlib

WORKFLOW_FILE = "ci.yml"
LAB_PREFIX = "[LAB]"
BRANCH_FILTER = re.compile(r"^(ctrl|draft|scn)/")


# --------------------------------------------------------------------------- #
# Shell helpers
# --------------------------------------------------------------------------- #
class Ctx:
    def __init__(self, repo, dry_run, pause, base, workdir):
        self.repo = repo
        self.dry = dry_run
        self.pause = pause
        self.base = base
        self.workdir = workdir
        self._fake_pr = 0

    def sh(self, *cmd, capture=False, check=True):
        cmd = [str(c) for c in cmd]
        shown = " ".join(shlex.quote(c) for c in cmd)
        if self.dry:
            print(f"[dry-run] {shown}")
            if cmd[:3] == ["gh", "pr", "create"]:
                self._fake_pr += 1
                return f"https://github.com/{self.repo}/pull/{self._fake_pr}"
            return ""
        print(f"$ {shown}")
        res = subprocess.run(cmd, cwd=self.workdir, text=True, capture_output=capture)
        if res.returncode != 0 and check:
            if capture and res.stderr:
                print(res.stderr, file=sys.stderr)
            raise subprocess.CalledProcessError(res.returncode, cmd, res.stdout, res.stderr)
        return (res.stdout or "").strip() if capture else ""

    def sleep(self, seconds):
        if seconds <= 0:
            return
        print(f"  ... waiting {seconds:g}s")
        if not self.dry:
            time.sleep(seconds)


def detect_repo(workdir):
    out = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        cwd=workdir, text=True, capture_output=True, check=True)
    return out.stdout.strip()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Git / PR primitives
# --------------------------------------------------------------------------- #
def start_branch(ctx, branch):
    ctx.sh("git", "fetch", "origin", ctx.base)
    ctx.sh("git", "checkout", "-B", branch, f"origin/{ctx.base}")


def commit_change(ctx, task, tag, n):
    rel = Path("work") / task / f"{tag}.txt"
    if not ctx.dry:
        path = Path(ctx.workdir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} change {n}\n")
    ctx.sh("git", "add", "--", str(rel))
    ctx.sh("git", "commit", "-m", f"{task}: change {n}")


def push(ctx, branch):
    ctx.sh("git", "push", "-u", "origin", branch)


def open_pr(ctx, title, branch, draft):
    args = ["gh", "pr", "create", "--repo", ctx.repo, "--base", ctx.base, "--head", branch,
            "--title", f"{LAB_PREFIX} {title}",
            "--body", "Automated pull request created by draft-pr-lab."]
    if draft:
        args.append("--draft")
    url = ctx.sh(*args, capture=True)
    return int(url.strip().splitlines()[-1].rstrip("/").split("/")[-1])


def mark_ready(ctx, number):
    ctx.sh("gh", "pr", "ready", number, "--repo", ctx.repo)


def convert_to_draft(ctx, number):
    ctx.sh("gh", "pr", "ready", number, "--repo", ctx.repo, "--undo")


def delete_remote_branch(ctx, branch):
    ctx.sh("git", "push", "origin", "--delete", branch, check=False)


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #
def cmd_plan(args):
    items = planlib.make_plan(args.pairs, args.seed)
    tot = {a: [0, 0] for a in planlib.ARMS}
    print(f"{'pair':<9}{'wip':>4}{'rounds':>8}{'pushes':>8}   ctrl exec/skip   draft exec/skip")
    for it in items:
        c, d = it.expected_runs("ctrl"), it.expected_runs("draft")
        for arm, (e, s) in (("ctrl", c), ("draft", d)):
            tot[arm][0] += e
            tot[arm][1] += s
        print(f"{it.task:<9}{it.wip_commits:>4}{len(it.review_rounds):>8}{it.total_pushes:>8}"
              f"   {c[0]:>6}/{c[1]:<8} {d[0]:>8}/{d[1]:<6}")
    print("\nExpected totals (executed / skipped runs):")
    for arm in planlib.ARMS:
        e, s = tot[arm]
        print(f"  {arm:<6} {e:>4} executed, {s:>4} skipped  "
              f"(~{e * args.minutes_per_run} billable min at {args.minutes_per_run} min/run)")
    saved = tot["ctrl"][0] - tot["draft"][0]
    print(f"  => {saved} fewer executed runs in the draft arm "
          f"({100 * saved / max(1, tot['ctrl'][0]):.1f}% by construction of the plan)")


# --------------------------------------------------------------------------- #
# experiment
# --------------------------------------------------------------------------- #
def run_pr(ctx, item, arm, wait_ci):
    branch = item.branch(arm)
    draft = arm == "draft"
    n = 1
    print(f"\n=== {item.task} / arm={arm} / branch={branch} ===")

    start_branch(ctx, branch)
    commit_change(ctx, item.task, arm, n)
    push(ctx, branch)
    number = open_pr(ctx, item.title(), branch, draft=draft)
    ctx.sleep(ctx.pause)

    for _ in range(item.wip_commits - 1):               # work in progress
        n += 1
        commit_change(ctx, item.task, arm, n)
        push(ctx, branch)
        ctx.sleep(ctx.pause)

    if draft:                                           # first "Ready for review"
        mark_ready(ctx, number)
        ctx.sleep(ctx.pause)

    for commits in item.review_rounds:                  # review / rework rounds
        if draft:
            convert_to_draft(ctx, number)
            ctx.sleep(ctx.pause)
        for _ in range(commits):
            n += 1
            commit_change(ctx, item.task, arm, n)
            push(ctx, branch)
            ctx.sleep(ctx.pause)
        if draft:
            mark_ready(ctx, number)
            ctx.sleep(ctx.pause)

    if wait_ci:
        ctx.sh("gh", "pr", "checks", number, "--repo", ctx.repo, "--watch", check=False)
    ctx.sh("gh", "pr", "merge", number, "--repo", ctx.repo, "--squash")
    delete_remote_branch(ctx, branch)

    executed, skipped = item.expected_runs(arm)
    return {"pair_id": item.pair_id, "task": item.task, "arm": arm, "branch": branch,
            "pr_number": number, "pushes": item.total_pushes,
            "expected_executed": executed, "expected_skipped": skipped}


def cmd_experiment(ctx, args):
    items = planlib.make_plan(args.pairs, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"seed": args.seed, "pairs": args.pairs, "repo": ctx.repo,
                "started_at": now_iso(), "prs": []}
    for item in items:
        for arm in planlib.arm_order(item.pair_id, args.seed):
            manifest["prs"].append(run_pr(ctx, item, arm, args.wait_ci))
            if not ctx.dry:
                (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    manifest["finished_at"] = now_iso()
    if not ctx.dry:
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nExperiment finished. Wait for the last runs to complete, then:\n"
          f"  python tools/lab.py collect --out {args.out}\n"
          f"  python tools/analyze.py --data {args.out} --out results/real")


# --------------------------------------------------------------------------- #
# scenarios (functional validation of the trigger rules)
# --------------------------------------------------------------------------- #
# steps run after the PR is opened; a trailing "!" means "do not wait afterwards"
SCENARIOS = {
    "S1": {"title": "Normal PR: open, then push",
           "draft": False, "steps": ["push"], "expect": (2, 0), "strict": True},
    "S2": {"title": "Draft PR: open, then push",
           "draft": True, "steps": ["push"], "expect": (0, 2), "strict": True},
    "S3": {"title": "Draft -> Ready for review -> push",
           "draft": True, "steps": ["push", "ready", "push"], "expect": (2, 2), "strict": True},
    "S4": {"title": "Ready -> Draft -> Ready in quick succession (overlap case)",
           "draft": False, "steps": ["push", "to_draft!", "ready"], "expect": (3, 0), "strict": False},
    "S5": {"title": "Converting to draft never triggers; push while draft is skipped",
           "draft": False, "steps": ["to_draft", "push", "ready"], "expect": (2, 1), "strict": True},
}


def cmd_scenarios(ctx, args):
    chosen = args.only or list(SCENARIOS)
    tag = datetime.now(timezone.utc).strftime("%m%d%H%M")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"repo": ctx.repo, "created_at": now_iso(), "scenarios": []}
    for sid in chosen:
        sc = SCENARIOS[sid]
        branch = f"scn/{sid}-{tag}"
        print(f"\n=== {sid}: {sc['title']} ===")
        n = 1
        start_branch(ctx, branch)
        commit_change(ctx, sid, tag, n)
        push(ctx, branch)
        number = open_pr(ctx, f"scenario {sid}", branch, draft=sc["draft"])
        ctx.sleep(ctx.pause)
        for step in sc["steps"]:
            fast = step.endswith("!")
            action = step.rstrip("!")
            if action == "push":
                n += 1
                commit_change(ctx, sid, tag, n)
                push(ctx, branch)
            elif action == "ready":
                mark_ready(ctx, number)
            elif action == "to_draft":
                convert_to_draft(ctx, number)
            ctx.sleep(0 if fast else ctx.pause)
        ctx.sh("gh", "pr", "close", number, "--repo", ctx.repo)
        delete_remote_branch(ctx, branch)
        manifest["scenarios"].append({
            "id": sid, "title": sc["title"], "branch": branch, "pr_number": number,
            "expect_executed": sc["expect"][0], "expect_skipped": sc["expect"][1],
            "strict": sc["strict"]})
    if not ctx.dry:
        (out / "scenarios_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nScenarios submitted. When the runs finish:\n"
          f"  python tools/lab.py verify-scenarios --manifest {out / 'scenarios_manifest.json'}")


def _gh_json(ctx, *args):
    raw = ctx.sh("gh", *args, capture=True)
    return json.loads(raw) if raw else []


def cmd_verify_scenarios(ctx, args):
    manifest = json.loads(Path(args.manifest).read_text())
    deadline = time.time() + args.timeout
    results = {}
    while True:
        pending = 0
        for sc in manifest["scenarios"]:
            runs = _gh_json(ctx, "run", "list", "--repo", ctx.repo, "--workflow", WORKFLOW_FILE,
                            "--branch", sc["branch"], "--limit", "100",
                            "--json", "databaseId,status,conclusion,event")
            pending += sum(1 for r in runs if r["status"] != "completed")
            results[sc["id"]] = runs
        if pending == 0 or time.time() > deadline:
            break
        print(f"{pending} run(s) still in progress; checking again in 20s ...")
        time.sleep(20)

    failed = 0
    print(f"\n{'id':<4}{'expected (exec/skip)':<24}{'observed (exec/skip)':<24}result")
    for sc in manifest["scenarios"]:
        runs = results[sc["id"]]
        skipped = sum(1 for r in runs if r["conclusion"] == "skipped")
        executed = sum(1 for r in runs if r["status"] == "completed" and r["conclusion"] != "skipped")
        ok = (executed, skipped) == (sc["expect_executed"], sc["expect_skipped"])
        if ok:
            verdict = "PASS"
        elif sc["strict"]:
            verdict = "FAIL"
            failed += 1
        else:
            verdict = "DIFFERS (observational scenario, not asserted)"
        print(f"{sc['id']:<4}{str((sc['expect_executed'], sc['expect_skipped'])):<24}"
              f"{str((executed, skipped)):<24}{verdict}")
    if pending:
        print("\nWARNING: some runs were still in progress when the timeout expired.")
        failed += 1
    sys.exit(1 if failed else 0)


# --------------------------------------------------------------------------- #
# collect
# --------------------------------------------------------------------------- #
def _fetch_jobs(ctx, run_id):
    raw = ctx.sh("gh", "api", "--paginate", f"repos/{ctx.repo}/actions/runs/{run_id}/jobs",
                 "--jq", ".jobs[] | {name, conclusion, started_at, completed_at}", capture=True)
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def cmd_collect(ctx, args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    prs = _gh_json(ctx, "pr", "list", "--repo", ctx.repo, "--state", "all", "--limit", "1000",
                   "--json", "number,title,headRefName,isDraft,state,createdAt,mergedAt,closedAt")
    prs = [p for p in prs if BRANCH_FILTER.match(p["headRefName"])]

    runs = _gh_json(ctx, "run", "list", "--repo", ctx.repo, "--workflow", WORKFLOW_FILE,
                    "--limit", "1000", "--json",
                    "databaseId,headBranch,headSha,status,conclusion,createdAt,startedAt,"
                    "updatedAt,event,attempt")
    runs = [r for r in runs if BRANCH_FILTER.match(r["headBranch"])]

    for i, run in enumerate(runs, 1):
        if run["conclusion"] == "skipped":
            run["jobs"] = []        # skipped runs are not billed
        else:
            run["jobs"] = _fetch_jobs(ctx, run["databaseId"])
        if i % 10 == 0:
            print(f"  fetched job timings for {i}/{len(runs)} runs")

    (out / "prs.json").write_text(json.dumps(prs, indent=2))
    (out / "runs.json").write_text(json.dumps(runs, indent=2))
    meta = {"repo": ctx.repo, "collected_at": now_iso(), "synthetic": False,
            "workflow": WORKFLOW_FILE,
            "gh_version": ctx.sh("gh", "--version", capture=True).splitlines()[0]}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"Saved {len(prs)} PRs and {len(runs)} runs to {out}/")


# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", help="owner/name (default: detected with `gh repo view`)")
    p.add_argument("--dry-run", action="store_true", help="print commands without running them")
    p.add_argument("--pause", type=float, default=20.0,
                   help="seconds to wait between pushes / state changes (default 20)")
    p.add_argument("--base", default="main", help="base branch (default main)")
    p.add_argument("--workdir", default=".", help="local clone to operate in (default .)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", help="print the experiment plan")
    sp.add_argument("--pairs", type=int, default=12)
    sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("--minutes-per-run", type=int, default=3)

    sp = sub.add_parser("experiment", help="run the paired benchmark")
    sp.add_argument("--pairs", type=int, default=12)
    sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("--out", default="data/real")
    sp.add_argument("--wait-ci", action="store_true", help="wait for checks before merging")

    sp = sub.add_parser("scenarios", help="run functional trigger scenarios")
    sp.add_argument("--only", nargs="+", choices=sorted(SCENARIOS))
    sp.add_argument("--out", default="data/real")

    sp = sub.add_parser("verify-scenarios", help="check scenario outcomes")
    sp.add_argument("--manifest", default="data/real/scenarios_manifest.json")
    sp.add_argument("--timeout", type=int, default=1800)

    sp = sub.add_parser("collect", help="download PRs, runs and job timings")
    sp.add_argument("--out", default="data/real")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "plan":
        return cmd_plan(args)
    repo = args.repo or ("OWNER/REPO" if args.dry_run else detect_repo(args.workdir))
    ctx = Ctx(repo, args.dry_run, args.pause, args.base, args.workdir)
    return {"experiment": cmd_experiment, "scenarios": cmd_scenarios,
            "verify-scenarios": cmd_verify_scenarios, "collect": cmd_collect}[args.cmd](ctx, args)


if __name__ == "__main__":
    main()
