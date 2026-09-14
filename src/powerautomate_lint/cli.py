"""Command line interface.

Exit codes are chosen so a pipeline can act on them:

    0  scan completed and nothing met the --fail-on threshold
    1  scan completed and something met the threshold
    2  the input could not be scanned at all

The distinction between 1 and 2 matters. A build that cannot find any flows is
not a passing build, and a tool that returns 0 in that case will sit green in a
pipeline forever while checking nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .analyze import analyze
from .report import sarif, text
from .rules import registry
from .rules.base import severity_rank

_THRESHOLDS = ("none", "note", "warning", "error")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="palint",
        description=(
            "Lint Power Automate cloud flows offline. Resolves every expression "
            "reference against the flow's own action graph. No tenant, no "
            "credentials, no network."
        ),
        epilog="https://github.com/verseblocks/powerautomate-lint",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help=(
            "unpacked solution folders, Workflows folders, solution .zip files, "
            "or individual flow .json files"
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "md", "json", "sarif"),
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="write the report to this file instead of stdout",
    )
    parser.add_argument(
        "--rules",
        help="comma-separated rule ids or prefixes to run, e.g. PAL101,PAL3",
    )
    parser.add_argument(
        "--fail-on",
        choices=_THRESHOLDS,
        default="error",
        help="lowest severity that sets exit code 1 (default: error)",
    )
    parser.add_argument(
        "--list-rules",
        action="store_true",
        help="print the rule catalogue and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"palint {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_rules:
        for rule in registry.all():
            print(f"{rule.id}  {rule.severity:<8}  {rule.summary}")
        return 0

    if not args.paths:
        print("palint: no paths given (try --help)", file=sys.stderr)
        return 2

    selected = None
    if args.rules:
        wanted = [r for r in args.rules.split(",") if r.strip()]
        selected = [r.id for r in registry.select(wanted)]
        if not selected:
            print(
                f"palint: --rules {args.rules!r} matched no rules", file=sys.stderr
            )
            return 2

    result = analyze(args.paths, rule_ids=selected)

    for error in result.errors:
        print(f"palint: {error.path}: {error.message}", file=sys.stderr)

    if not result.flows_scanned:
        print("palint: no flows were scanned", file=sys.stderr)
        return 2

    root = _common_root(args.paths)

    if args.format == "sarif":
        rendered = sarif.dumps(
            result.findings,
            root=root,
            version=__version__,
            rule_ids=selected,
        )
    elif args.format == "json":
        rendered = text.as_json(
            result.findings,
            root=root,
            flows_scanned=result.flows_scanned,
            expressions_scanned=result.expressions_scanned,
        )
    elif args.format == "md":
        rendered = text.markdown(
            result.findings,
            root=root,
            flows_scanned=result.flows_scanned,
            expressions_scanned=result.expressions_scanned,
        )
    else:
        rendered = _plain(result, root)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)

    if args.fail_on == "none":
        return 0
    threshold = severity_rank(args.fail_on)
    if any(severity_rank(f.severity) >= threshold for f in result.findings):
        return 1
    return 0


def _plain(result, root: Path | None) -> str:
    lines: list[str] = []
    for finding in sorted(result.findings, key=lambda f: f.sort_key()):
        loc = text._rel(finding.file, root)
        lines.append(
            f"{loc}: {finding.severity}: [{finding.rule_id}] "
            f"{finding.flow}: {finding.message}"
        )
    counts = {
        "error": sum(1 for f in result.findings if f.severity == "error"),
        "warning": sum(1 for f in result.findings if f.severity == "warning"),
        "note": sum(1 for f in result.findings if f.severity == "note"),
    }
    lines.append("")
    lines.append(
        f"{result.flows_scanned} flows, {result.expressions_scanned} expressions, "
        f"{counts['error']} errors, {counts['warning']} warnings, "
        f"{counts['note']} notes"
    )
    return "\n".join(lines) + "\n"


def _common_root(paths: list[str]) -> Path | None:
    """Directory to make report paths relative to."""
    resolved = [Path(p).resolve() for p in paths]
    if not resolved:
        return None
    if len(resolved) == 1:
        p = resolved[0]
        return p if p.is_dir() else p.parent
    try:
        import os

        return Path(os.path.commonpath([str(p) for p in resolved]))
    except ValueError:
        return None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
