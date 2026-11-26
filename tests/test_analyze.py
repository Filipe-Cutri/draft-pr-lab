import json

import analyze
import make_synthetic_data as synth
import plan as planlib


def _dataset(pairs=12, seed=42):
    return synth.generate(pairs=pairs, seed=seed)


def test_job_billable_minutes_rounds_up_and_ignores_skipped():
    job = {"conclusion": "success", "started_at": "2026-01-01T00:00:00Z",
           "completed_at": "2026-01-01T00:01:01Z"}
    assert analyze.job_billable_minutes(job) == 2
    job["completed_at"] = "2026-01-01T00:02:00Z"
    assert analyze.job_billable_minutes(job) == 2
    assert analyze.job_billable_minutes({"conclusion": "skipped",
                                         "started_at": "2026-01-01T00:00:00Z",
                                         "completed_at": "2026-01-01T00:00:00Z"}) == 0
    assert analyze.job_billable_minutes({"conclusion": None}) == 0


def test_observed_runs_match_plan_and_no_mismatch_reported():
    prs, runs, _, manifest = _dataset()
    res = analyze.analyze(prs, runs, manifest=manifest, resamples=500)
    assert res["checks"]["plan_mismatches"] == []
    items = planlib.make_plan(12, 42)
    assert res["arms"]["ctrl"]["runs_executed"] == sum(i.expected_runs("ctrl")[0] for i in items)
    assert res["arms"]["draft"]["runs_executed"] == sum(i.expected_runs("draft")[0] for i in items)
    assert res["arms"]["draft"]["runs_skipped"] == sum(i.expected_runs("draft")[1] for i in items)


def test_skipped_runs_only_in_draft_arm():
    prs, runs, _, _ = _dataset()
    res = analyze.analyze(prs, runs, resamples=500)
    assert res["arms"]["ctrl"]["runs_skipped"] == 0
    assert res["arms"]["draft"]["runs_skipped"] > 0


def test_draft_arm_is_cheaper_and_paired_stats_are_consistent():
    prs, runs, _, _ = _dataset()
    res = analyze.analyze(prs, runs, resamples=500)
    p = res["paired"]
    assert p["n_pairs"] == 12
    assert p["billable_draft_total"] < p["billable_ctrl_total"]
    assert 0 < p["reduction_pct"] < 100
    assert p["reduction_pct_ci95"][0] <= p["reduction_pct"] <= p["reduction_pct_ci95"][1] + 1e-9
    assert 0 <= p["sign_flip_p_two_sided"] <= 1


def test_legacy_average_is_diluted_by_skipped_runs():
    prs, runs, _, _ = _dataset()
    d = analyze.analyze(prs, runs, resamples=500)["arms"]["draft"]
    assert d["legacy_mean_wall_min_per_run_incl_skipped"] < d["mean_wall_min_per_executed_run"]


def test_unmerged_or_unpaired_prs_are_excluded_from_pairs():
    prs, runs, _, _ = _dataset(pairs=4)
    victim = next(p for p in prs if p["headRefName"].startswith("draft/TASK-002"))
    victim["state"] = "CLOSED"
    res = analyze.analyze(prs, runs, resamples=200)
    assert res["paired"]["n_pairs"] == 3
    assert any("TASK-002" in x for x in res["checks"]["merged_prs_without_partner"])


def test_sign_flip_p_edge_cases():
    assert analyze.sign_flip_p([]) == 1.0
    assert analyze.sign_flip_p([0, 0, 0]) == 1.0
    # all positive differences, n=10 -> the two extreme sign patterns give p = 2/2^10
    assert abs(analyze.sign_flip_p([3] * 10) - 2 / 1024) < 1e-12


def test_cli_writes_outputs(tmp_path):
    prs, runs, meta, manifest = _dataset(pairs=5)
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    for name, obj in (("prs", prs), ("runs", runs), ("meta", meta), ("manifest", manifest)):
        (data / f"{name}.json").write_text(json.dumps(obj))
    analyze.main(["--data", str(data), "--out", str(out), "--bootstrap", "200"])
    for f in ("summary.json", "summary.md", "per_pair.csv"):
        assert (out / f).exists()
    assert "SYNTHETIC DATA" in (out / "summary.md").read_text()
