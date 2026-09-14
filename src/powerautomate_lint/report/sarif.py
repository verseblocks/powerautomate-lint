"""SARIF 2.1.0 output.

SARIF is the reason this tool is usable in a pull request: GitHub code scanning
ingests it and renders findings as annotations on the diff, and Azure DevOps
extensions read it too.

Two details are deliberate rather than incidental:

Paths are emitted POSIX-style and relative to the scan root. Without that the
same scan produces different bytes on Windows and Linux, which makes the golden
SARIF fixtures untestable on a matrix build.

Ordering is fully deterministic. Findings are sorted before emission so a
regression in rule ordering shows up as a diff rather than as flaky CI.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

from ..rules import registry
from ..rules.base import Finding

SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"

_LEVEL = {"error": "error", "warning": "warning", "note": "note"}


def _uri(file: str, root: Path | None) -> str:
    """Relative POSIX URI for a finding's file.

    A ``zip!entry`` path keeps its shape; the zip itself is relativised and the
    entry is appended, so a finding inside an archive still points somewhere a
    reader can act on.
    """
    if "!" in file:
        archive, _, entry = file.partition("!")
        return f"{_uri(archive, root)}!{PurePosixPath(entry.replace(chr(92), '/'))}"
    p = Path(file)
    if root is not None:
        try:
            p = p.relative_to(root)
        except ValueError:
            pass
    return PurePosixPath(p.as_posix()).as_posix()


def build(
    findings: Iterable[Finding],
    *,
    root: Path | None = None,
    version: str = "0.0.0",
    rule_ids: Sequence[str] | None = None,
) -> dict:
    """Build a SARIF log object for the given findings."""
    ordered = sorted(findings, key=lambda f: f.sort_key())

    used = rule_ids if rule_ids is not None else sorted({f.rule_id for f in ordered})
    rules = []
    for rule_id in used:
        rule = registry.get(rule_id)
        if rule is None:
            continue
        rules.append(
            {
                "id": rule.id,
                "name": rule.id,
                "shortDescription": {"text": rule.summary},
                "fullDescription": {"text": rule.help},
                "help": {"text": rule.help},
                "defaultConfiguration": {"level": _LEVEL.get(rule.severity, "note")},
                "properties": {"tags": ["power-automate", "dataverse", "expression"]},
            }
        )

    results = []
    for finding in ordered:
        region: dict = {}
        if finding.expression:
            # SARIF columns are 1-based. The offset is into the expression body,
            # not the file, so this is a logical location rather than a byte
            # region; snippet carries the text a reviewer needs.
            region = {
                "startLine": 1,
                "startColumn": finding.offset + 1,
                "snippet": {"text": finding.expression[:400]},
            }

        location: dict = {
            "physicalLocation": {
                "artifactLocation": {"uri": _uri(finding.file, root)},
            },
            "logicalLocations": [
                {
                    "name": finding.flow,
                    "fullyQualifiedName": f"{finding.flow}{finding.pointer}",
                    "kind": "member",
                }
            ],
        }
        if region:
            location["physicalLocation"]["region"] = region

        results.append(
            {
                "ruleId": finding.rule_id,
                "level": _LEVEL.get(finding.severity, "note"),
                "message": {"text": finding.message},
                "locations": [location],
                "properties": {
                    "jsonPointer": finding.pointer,
                    "flow": finding.flow,
                    **({"detail": finding.detail} if finding.detail else {}),
                },
            }
        )

    return {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "powerautomate-lint",
                        "informationUri": "https://github.com/verseblocks/powerautomate-lint",
                        "version": version,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def dumps(
    findings: Iterable[Finding],
    *,
    root: Path | None = None,
    version: str = "0.0.0",
    rule_ids: Sequence[str] | None = None,
) -> str:
    """Serialise a SARIF log. Trailing newline so files end cleanly."""
    log = build(findings, root=root, version=version, rule_ids=rule_ids)
    return json.dumps(log, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
