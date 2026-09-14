"""Offline linting for Power Automate cloud flows.

No tenant, no credentials, no network. Point it at an unpacked solution, a
solution .zip or a single flow definition and it resolves every expression
reference against the flow's own action graph.

    from powerautomate_lint import analyze
    result = analyze(["./src"])

The expression parser is usable on its own and has no dependencies:

    from powerautomate_lint.expression import parse, parse_template
"""

__version__ = "0.1.0"

from .analyze import AnalysisResult, analyze, count_expressions

__all__ = ["AnalysisResult", "analyze", "count_expressions", "__version__"]
