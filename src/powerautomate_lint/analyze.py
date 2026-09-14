"""Top-level scan: load flows, run rules, count what was looked at.

The expression count is reported because it is the only honest measure of
coverage. "Scanned 239 flows, 0 findings" could mean the flows are clean or it
could mean the loader silently found nothing to parse. "Scanned 239 flows and
15,312 expressions" cannot be mistaken for the second.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .expression import ExpressionSyntaxError, iter_expressions
from .model.flow import Flow
from .model.loader import LoadError, load
from .rules import CHECKS
from .rules.base import Finding


@dataclass
class AnalysisResult:
    findings: list[Finding] = field(default_factory=list)
    errors: list[LoadError] = field(default_factory=list)
    flows_scanned: int = 0
    expressions_scanned: int = 0
    flows: list[Flow] = field(default_factory=list, repr=False)


def count_expressions(flow: Flow) -> int:
    """Number of expression interpolations anywhere in the flow definition."""
    total = 0
    stack: list[object] = [flow.definition]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            if "@" in node:
                try:
                    total += len(iter_expressions(node))
                except ExpressionSyntaxError:
                    pass
        elif isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return total


def analyze(
    paths: Iterable[str | Path],
    *,
    rule_ids: Sequence[str] | None = None,
) -> AnalysisResult:
    """Scan every path and return findings plus coverage counts.

    ``rule_ids`` filters the output rather than the checks that run. Two rules
    are emitted as a by-product of another rule's single pass, so skipping a
    check to satisfy a filter would silently drop its sibling.
    """
    result = AnalysisResult()
    wanted = set(rule_ids) if rule_ids else None

    for path in paths:
        loaded = load(path)
        result.errors.extend(loaded.errors)
        for flow in loaded.flows:
            result.flows.append(flow)
            result.flows_scanned += 1
            result.expressions_scanned += count_expressions(flow)
            for check in CHECKS:
                for finding in check(flow):
                    if wanted is None or finding.rule_id in wanted:
                        result.findings.append(finding)

    return result
