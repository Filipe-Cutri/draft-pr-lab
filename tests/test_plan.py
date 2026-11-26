import plan as planlib


def test_plan_is_deterministic():
    assert planlib.make_plan(8, seed=7) == planlib.make_plan(8, seed=7)


def test_expected_runs_ctrl_vs_draft():
    item = planlib.PlanItem(1, "TASK-001", "x", wip_commits=4, review_rounds=(2, 1))
    assert item.total_pushes == 7
    assert item.expected_runs("ctrl") == (7, 0)
    # draft: ready after WIP + ready after each of the 2 review rounds
    assert item.expected_runs("draft") == (3, 7)


def test_branch_names_are_arm_prefixed_and_unique():
    items = planlib.make_plan(30, seed=1)
    branches = {it.branch(a) for it in items for a in planlib.ARMS}
    assert len(branches) == 60
    assert all(b.split("/")[0] in planlib.ARMS for b in branches)


def test_arm_order_is_reproducible_and_covers_both_arms():
    assert planlib.arm_order(3, 42) == planlib.arm_order(3, 42)
    assert sorted(planlib.arm_order(3, 42)) == sorted(planlib.ARMS)
