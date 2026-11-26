"""Deterministic experiment plan.

Shared by the driver (lab.py), the synthetic-data generator and the tests, so
that "what we planned" and "what we expect GitHub to have run" come from a
single source of truth.

Paired design: every plan item is executed twice, once per arm, with the
SAME commit schedule:

    ctrl   -> PR opened ready for review; every push triggers a build.
    draft  -> PR opened as draft; pushes while draft are skipped; the build
              runs only when the PR is marked "Ready for review". Every
              review round converts the PR back to draft first.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Tuple

ARMS = ("ctrl", "draft")

_SLUGS = [
    "rounding", "discount-rules", "tax-table", "line-validation",
    "currency-format", "export-csv", "rate-lookup", "negative-qty",
    "audit-log", "refactor-totals", "locale-fix", "batch-import",
]


@dataclass(frozen=True)
class PlanItem:
    pair_id: int
    task: str                       # e.g. "TASK-001"
    slug: str
    wip_commits: int                # commits pushed before the first "ready"
    review_rounds: Tuple[int, ...]  # commits pushed in each review round

    @property
    def total_pushes(self) -> int:
        return self.wip_commits + sum(self.review_rounds)

    def branch(self, arm: str) -> str:
        return f"{arm}/{self.task}-{self.slug}"

    def title(self) -> str:
        return f"{self.task} {self.slug.replace('-', ' ')}"

    def expected_runs(self, arm: str) -> Tuple[int, int]:
        """(executed, skipped) workflow runs GitHub should record for this PR."""
        if arm == "ctrl":
            return self.total_pushes, 0
        if arm == "draft":
            return 1 + len(self.review_rounds), self.total_pushes
        raise ValueError(f"unknown arm: {arm}")


def make_plan(n_pairs: int, seed: int = 42, wip_range=(2, 6)) -> list:
    rng = random.Random(seed)
    items = []
    for i in range(1, n_pairs + 1):
        wip = rng.randint(*wip_range)
        rounds = rng.choices([0, 1, 2], weights=[2, 5, 3])[0]
        review = tuple(rng.randint(1, 2) for _ in range(rounds))
        items.append(PlanItem(i, f"TASK-{i:03d}", _SLUGS[(i - 1) % len(_SLUGS)], wip, review))
    return items


def arm_order(pair_id: int, seed: int) -> list:
    """Randomised (but reproducible) order in which the two arms of a pair run."""
    rng = random.Random(f"{seed}-{pair_id}")
    order = list(ARMS)
    rng.shuffle(order)
    return order
