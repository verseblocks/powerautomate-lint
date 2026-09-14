"""Markdown and JSON output.

The Markdown form is written to be pasted into a pull request comment or a
review document, so it leads with the counts a reader needs and groups by flow
rather than by rule. Someone fixing findings works one flow at a time.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from ..rules import registry
from ..rules.base import Finding

_ICON = {"error": "error", "warning": "warning", "note": "note"}


def _rel(file: str, root: Path | None) -> str:
    if root is None:
        return file
    archive, sep, entry = file.partition("!")
    try:
        rel = str(Path(archive).relative_to(root))
    except ValueError:
        rel = archive
    return f"{rel}{sep}{entry}" if sep else rel


def markdown(
    findings: Iterable[Finding],
    *,
    root: Path | None = None,
    flows_scanned: int = 0,
    expressions_scanned: int = 0,
) -> str:
    ordered = sorted(findings, key=lambda f: f.sort_key())
    counts = Counter(f.severity for f in ordered)

    out: list[str] = ["# Power Automate lint results", ""]
    out.append(
        f"Scanned {flows_scanned} flow{'s' if flows_scanned != 1 else ''}"
        + (f" and {expressions_scanned} expressions" if expressions_scanned else "")
        + "."
    )
    out.append("")
    if not ordered:
        out.append("No findings.")
        out.append("")
        return "\n".join(out)

    out.append(
        f"{counts.get('error', 0)} errors, {counts.get('warning', 0)} warnings, "
        f"{counts.get('note', 0)} notes."
    )
    out.append("")

    by_rule = Counter(f.rule_id for f in ordered)
    out.append("| Rule | Count | Summary |")
    out.append("| --- | --- | --- |")
    for rule_id, count in sorted(by_rule.items()):
        rule = registry.get(rule_id)
        summary = rule.summary if rule else ""
        out.append(f"| `{rule_id}` | {count} | {summary} |")
    out.append("")

    grouped: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for finding in ordered:
        grouped[(finding.flow, finding.file)].append(finding)

    for (flow, file), items in sorted(grouped.items()):
        out.append(f"## {flow}")
        out.append("")
        out.append(f"`{_rel(file, root)}`")
        out.append("")
        for finding in items:
            out.append(
                f"- `{finding.rule_id}` {_ICON.get(finding.severity, '')}: "
                f"{finding.message}"
            )
            if finding.expression:
                snippet = finding.expression.strip()
                if len(snippet) > 160:
                    snippet = snippet[:157] + "..."
                out.append(f"  - expression: `{snippet}`")
            out.append(f"  - at: `{finding.pointer}`")
            if finding.detail:
                out.append(f"  - {finding.detail}")
        out.append("")

    return "\n".join(out)


def as_json(
    findings: Iterable[Finding],
    *,
    root: Path | None = None,
    flows_scanned: int = 0,
    expressions_scanned: int = 0,
) -> str:
    ordered = sorted(findings, key=lambda f: f.sort_key())
    counts = Counter(f.severity for f in ordered)
    payload = {
        "summary": {
            "flowsScanned": flows_scanned,
            "expressionsScanned": expressions_scanned,
            "errors": counts.get("error", 0),
            "warnings": counts.get("warning", 0),
            "notes": counts.get("note", 0),
            "total": len(ordered),
        },
        "findings": [
            {
                "ruleId": f.rule_id,
                "severity": f.severity,
                "message": f.message,
                "file": _rel(f.file, root),
                "flow": f.flow,
                "jsonPointer": f.pointer,
                "expression": f.expression,
                "offset": f.offset,
                "detail": f.detail,
            }
            for f in ordered
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
