"""Deterministic score and ship gate. Judgement is made by the models; this is arithmetic only."""
from __future__ import annotations

from . import config
from .schemas import Report


def recompute(report: Report) -> Report:
    open_ = [f for f in report.findings if f.status == "open"]
    crit = sum(1 for f in open_ if f.severity == "critical")
    warn = sum(1 for f in open_ if f.severity == "warning")
    report.score = max(0, 100 - crit * config.PENALTY_CRITICAL - warn * config.PENALTY_WARNING)
    failing_checks = {f.check_id for f in open_}
    report.checks_passed = max(0, report.checks_total - len(failing_checks))
    report.shippable = crit == 0
    return report
