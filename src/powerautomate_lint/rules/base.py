"""Finding and rule types.

Severities follow SARIF: ``error``, ``warning``, ``note``. The CLI's
``--fail-on`` threshold maps onto them directly so a pipeline can decide what
blocks a merge.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..model.flow import Flow

Severity = str  # "error" | "warning" | "note"

_ORDER = {"note": 0, "warning": 1, "error": 2}


def severity_rank(severity: Severity) -> int:
    return _ORDER.get(severity, 0)


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    message: str
    #: Path of the flow file, or ``zip!entry``.
    file: str
    #: Flow display name.
    flow: str
    #: RFC 6901 pointer to the offending node within the flow document.
    pointer: str
    #: The expression the finding came from, when it came from one.
    expression: str = ""
    #: Character offset within ``expression``, when known.
    offset: int = 0
    #: Free-form extra detail rendered in Markdown output.
    detail: str = ""

    def sort_key(self) -> tuple:
        return (self.file, self.rule_id, self.pointer, self.offset, self.message)


@dataclass(frozen=True)
class Rule:
    id: str
    severity: Severity
    #: One line, shown in ``--list-rules`` and in the SARIF rule metadata.
    summary: str
    #: Why it matters, and what to do. Rendered in SARIF help text.
    help: str
    check: Callable[[Flow], Iterable[Finding]] = field(repr=False, default=None)  # type: ignore[assignment]


class Registry:
    def __init__(self) -> None:
        self._rules: dict[str, Rule] = {}

    def register(self, rule: Rule) -> Rule:
        if rule.id in self._rules:
            raise ValueError(f"duplicate rule id {rule.id}")
        self._rules[rule.id] = rule
        return rule

    def all(self) -> list[Rule]:
        return [self._rules[k] for k in sorted(self._rules)]

    def get(self, rule_id: str) -> Rule | None:
        return self._rules.get(rule_id)

    def select(self, patterns: Iterable[str] | None) -> list[Rule]:
        """Select rules by exact id or by prefix, e.g. ``PAL1`` or ``PAL101``."""
        if not patterns:
            return self.all()
        wanted = [p.strip().upper() for p in patterns if p.strip()]
        out = []
        for rule in self.all():
            if any(rule.id == w or rule.id.startswith(w) for w in wanted):
                out.append(rule)
        return out


registry = Registry()
