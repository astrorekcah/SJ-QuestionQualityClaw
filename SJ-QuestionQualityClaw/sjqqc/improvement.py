"""Continuous improvement engine — track verdicts, revisions, and trends.

Three feedback loops that make the system smarter over time:

1. Verdict tracking — was the system's judgment correct?
   Record human agreement/disagreement with each validation verdict.
   Compute accuracy rate and confidence calibration.

2. Revision acceptance — were the improvements useful?
   Track whether revised questions were accepted, rejected, or modified.
   Identify which strategies produce accepted revisions.

3. Trend analysis — is the question bank getting better?
   Track dimension scores over time across all questions.
   Detect systemic issues and measure improvement velocity.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. Verdict tracking
# ---------------------------------------------------------------------------

class VerdictOutcome(BaseModel):
    """Record of whether a verdict was correct."""

    feedback_id: str
    question_path: str
    system_verdict: str  # valid, partially_valid, invalid, unclear
    system_confidence: float
    human_agrees: bool
    human_notes: str = ""
    timestamp: float = Field(default_factory=time.time)


class VerdictTracker:
    """Track verdict accuracy over time."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path("data/verdicts")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._outcomes: list[VerdictOutcome] = []
        self._load()

    def _load(self) -> None:
        path = self.data_dir / "outcomes.jsonl"
        if path.exists():
            for line in path.read_text().strip().split("\n"):
                if line:
                    self._outcomes.append(
                        VerdictOutcome(**json.loads(line))
                    )

    def _save(self) -> None:
        path = self.data_dir / "outcomes.jsonl"
        with open(path, "w") as f:
            for o in self._outcomes:
                f.write(o.model_dump_json() + "\n")

    def record(self, outcome: VerdictOutcome) -> None:
        """Record whether the human agreed with a verdict."""
        self._outcomes.append(outcome)
        self._save()
        logger.info(
            "Verdict outcome: {} {} (system={}, confidence={:.0%})",
            "AGREED" if outcome.human_agrees else "DISAGREED",
            outcome.question_path,
            outcome.system_verdict,
            outcome.system_confidence,
        )

    @property
    def accuracy(self) -> float:
        """Overall accuracy: % of verdicts the human agreed with."""
        if not self._outcomes:
            return 0.0
        return sum(1 for o in self._outcomes if o.human_agrees) / len(
            self._outcomes
        )

    @property
    def calibration(self) -> dict[str, float]:
        """Confidence calibration by bucket.

        Groups verdicts by confidence range (0.5-0.6, 0.6-0.7, etc.)
        and reports actual accuracy in each bucket.
        """
        buckets: dict[str, list[bool]] = {}
        for o in self._outcomes:
            bucket = f"{int(o.system_confidence * 10) / 10:.1f}"
            buckets.setdefault(bucket, []).append(o.human_agrees)
        return {
            bucket: sum(vals) / len(vals)
            for bucket, vals in sorted(buckets.items())
        }

    @property
    def verdict_breakdown(self) -> dict[str, dict[str, int]]:
        """Accuracy by verdict type."""
        breakdown: dict[str, dict[str, int]] = {}
        for o in self._outcomes:
            v = o.system_verdict
            if v not in breakdown:
                breakdown[v] = {"total": 0, "agreed": 0}
            breakdown[v]["total"] += 1
            if o.human_agrees:
                breakdown[v]["agreed"] += 1
        return breakdown

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Verdict Accuracy: {self.accuracy:.0%} "
            f"({len(self._outcomes)} verdicts)",
        ]
        for v, stats in self.verdict_breakdown.items():
            acc = stats["agreed"] / stats["total"] if stats["total"] else 0
            lines.append(
                f"  {v}: {acc:.0%} ({stats['agreed']}/{stats['total']})"
            )
        cal = self.calibration
        if cal:
            lines.append("Confidence calibration:")
            for bucket, actual in cal.items():
                lines.append(f"  {bucket}: actual={actual:.0%}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. Revision acceptance tracking
# ---------------------------------------------------------------------------

class RevisionOutcome(BaseModel):
    """Record of whether a revision was accepted."""

    revision_id: str
    question_path: str
    strategies_used: list[str]
    fields_changed: int
    accepted: bool  # True=uploaded, False=rejected
    modified: bool = False  # True=accepted with manual edits
    rejection_reason: str = ""
    timestamp: float = Field(default_factory=time.time)


class RevisionTracker:
    """Track which revisions are accepted vs rejected."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path("data/revisions")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._outcomes: list[RevisionOutcome] = []
        self._load()

    def _load(self) -> None:
        path = self.data_dir / "outcomes.jsonl"
        if path.exists():
            for line in path.read_text().strip().split("\n"):
                if line:
                    self._outcomes.append(
                        RevisionOutcome(**json.loads(line))
                    )

    def _save(self) -> None:
        path = self.data_dir / "outcomes.jsonl"
        with open(path, "w") as f:
            for o in self._outcomes:
                f.write(o.model_dump_json() + "\n")

    def record(self, outcome: RevisionOutcome) -> None:
        """Record whether a revision was accepted."""
        self._outcomes.append(outcome)
        self._save()

    @property
    def acceptance_rate(self) -> float:
        if not self._outcomes:
            return 0.0
        return sum(1 for o in self._outcomes if o.accepted) / len(
            self._outcomes
        )

    @property
    def strategy_acceptance(self) -> dict[str, dict[str, int]]:
        """Acceptance rate per strategy."""
        stats: dict[str, dict[str, int]] = {}
        for o in self._outcomes:
            for s in o.strategies_used:
                if s not in stats:
                    stats[s] = {"total": 0, "accepted": 0}
                stats[s]["total"] += 1
                if o.accepted:
                    stats[s]["accepted"] += 1
        return stats

    def summary(self) -> str:
        lines = [
            f"Revision Acceptance: {self.acceptance_rate:.0%} "
            f"({len(self._outcomes)} revisions)",
        ]
        for s, st in self.strategy_acceptance.items():
            acc = st["accepted"] / st["total"] if st["total"] else 0
            lines.append(f"  {s}: {acc:.0%} ({st['accepted']}/{st['total']})")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Trend analysis
# ---------------------------------------------------------------------------

class QualitySnapshot(BaseModel):
    """Quality state of the bank at a point in time."""

    timestamp: float = Field(default_factory=time.time)
    total_questions: int = 0
    passing_questions: int = 0
    average_score: float = 0.0
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    weakest_dimension: str = ""


class TrendTracker:
    """Track quality trends over time."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path("data/trends")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots: list[QualitySnapshot] = []
        self._load()

    def _load(self) -> None:
        path = self.data_dir / "snapshots.jsonl"
        if path.exists():
            for line in path.read_text().strip().split("\n"):
                if line:
                    self._snapshots.append(
                        QualitySnapshot(**json.loads(line))
                    )

    def _save(self) -> None:
        path = self.data_dir / "snapshots.jsonl"
        with open(path, "w") as f:
            for s in self._snapshots:
                f.write(s.model_dump_json() + "\n")

    def record_snapshot(self, snapshot: QualitySnapshot) -> None:
        """Record a quality snapshot."""
        self._snapshots.append(snapshot)
        self._save()

    def record_from_bank_report(self, report: Any) -> None:
        """Create and record a snapshot from a BankReport."""
        snapshot = QualitySnapshot(
            total_questions=report.total_questions,
            passing_questions=report.passing_questions,
            average_score=report.average_score,
            dimension_scores=report.dimension_pass_rates,
            weakest_dimension=(
                report.weakest_dimensions[0][0]
                if report.weakest_dimensions
                else ""
            ),
        )
        self.record_snapshot(snapshot)

    @property
    def improvement_velocity(self) -> float | None:
        """Score change per snapshot (positive = improving)."""
        if len(self._snapshots) < 2:
            return None
        first = self._snapshots[0].average_score
        last = self._snapshots[-1].average_score
        return last - first

    @property
    def dimension_trends(self) -> dict[str, list[float]]:
        """Per-dimension pass rates over time."""
        trends: dict[str, list[float]] = {}
        for s in self._snapshots:
            for dim, rate in s.dimension_scores.items():
                trends.setdefault(dim, []).append(rate)
        return trends

    @property
    def systemic_issues(self) -> list[str]:
        """Dimensions that consistently fail across snapshots."""
        issues = []
        for dim, rates in self.dimension_trends.items():
            if len(rates) >= 2 and all(r < 0.8 for r in rates[-3:]):
                issues.append(dim)
        return issues

    def summary(self) -> str:
        lines = [f"Quality Snapshots: {len(self._snapshots)}"]
        if self._snapshots:
            latest = self._snapshots[-1]
            lines.append(
                f"  Latest: {latest.passing_questions}/"
                f"{latest.total_questions} passing, "
                f"avg {latest.average_score:.1f}/10"
            )
        vel = self.improvement_velocity
        if vel is not None:
            direction = "improving" if vel > 0 else "declining"
            lines.append(f"  Velocity: {vel:+.1f} ({direction})")
        issues = self.systemic_issues
        if issues:
            lines.append(f"  Systemic issues: {', '.join(issues)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Combined dashboard
# ---------------------------------------------------------------------------

def improvement_dashboard(
    data_dir: Path | None = None,
) -> str:
    """Generate a combined improvement dashboard."""
    d = data_dir or Path("data")
    vt = VerdictTracker(d / "verdicts")
    rt = RevisionTracker(d / "revisions")
    tt = TrendTracker(d / "trends")

    lines = [
        "═══ Continuous Improvement Dashboard ═══",
        "",
        vt.summary(),
        "",
        rt.summary(),
        "",
        tt.summary(),
    ]
    return "\n".join(lines)
