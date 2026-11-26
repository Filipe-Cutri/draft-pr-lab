import lab


def test_experiment_dry_run_emits_expected_commands(capsys):
    lab.main(["--dry-run", "experiment", "--pairs", "2", "--seed", "1"])
    out = capsys.readouterr().out
    assert "gh pr create" in out
    assert "--draft" in out                      # draft arm opens PRs as draft
    assert "gh pr ready" in out
    assert "gh pr merge" in out
    assert out.count("gh pr create") == 4        # 2 pairs x 2 arms


def test_scenarios_dry_run_covers_all_scenarios(capsys):
    lab.main(["--dry-run", "scenarios"])
    out = capsys.readouterr().out
    for sid in lab.SCENARIOS:
        assert f"=== {sid}:" in out
    assert "--undo" in out                       # convert-to-draft path exercised


def test_plan_prints_totals(capsys):
    lab.main(["plan", "--pairs", "5"])
    out = capsys.readouterr().out
    assert "Expected totals" in out and "fewer executed runs" in out
