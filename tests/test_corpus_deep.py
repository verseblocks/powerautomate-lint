"""The wide sweep over all 239 CoE flows. Opt-in.

Run ``python tools/fetch_corpus.py`` then ``pytest -m corpus``. Skipped
automatically when the corpus is absent, so a normal clone still gets a green
suite from the six committed fixtures.

The six vendored flows prove the specific behaviours. This file proves the
absence of behaviour across everything Microsoft ships, which is a different and
weaker-looking claim that happens to be the one that caught both real bugs
during development.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from powerautomate_lint.analyze import analyze
from powerautomate_lint.expression import ExpressionSyntaxError
from powerautomate_lint.expression.template import parse_template

CORPUS = Path(__file__).parent.parent / "fixtures" / "corpus"
EXPECTED_FLOWS = 239

pytestmark = pytest.mark.corpus


def _count_flows(root: Path) -> int:
    return sum(
        1
        for p in root.rglob("*.json")
        if p.parent.name.lower() == "workflows" and not p.name.endswith(".data.xml")
    )


@pytest.fixture(scope="module")
def result():
    if not CORPUS.exists() or _count_flows(CORPUS) != EXPECTED_FLOWS:
        pytest.skip("run tools/fetch_corpus.py first")
    return analyze([CORPUS])


def _iter_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        yield from (s for v in node.values() for s in _iter_strings(v))
    elif isinstance(node, list):
        yield from (s for v in node for s in _iter_strings(v))


def test_every_flow_loads(result):
    assert result.flows_scanned == EXPECTED_FLOWS
    assert result.errors == []


def test_both_directory_layouts_are_found(result):
    """186 flows live under SolutionPackage/src/Workflows, 53 under the older
    SolutionPackage/Workflows. Missing either is a silent 20% coverage hole."""
    paths = [f.path.replace("\\", "/") for f in result.flows]
    new_layout = sum(1 for p in paths if "/SolutionPackage/src/Workflows/" in p)
    old_layout = sum(1 for p in paths if "/SolutionPackage/Workflows/" in p)
    assert new_layout == 186
    assert old_layout == 53


def test_every_expression_in_the_corpus_parses(result):
    failures = []
    for flow in result.flows:
        for value in _iter_strings(flow.definition):
            if "@" not in value:
                continue
            try:
                parse_template(value)
            except ExpressionSyntaxError as exc:
                failures.append((flow.name, exc.code, value[:100]))
    assert failures == [], failures[:10]


def test_expression_volume(result):
    """Coverage guard. Around 15,300 expressions live in these flows."""
    assert result.expressions_scanned > 14000


@pytest.mark.parametrize("rule_id", ["PAL101", "PAL103", "PAL106"])
def test_zero_errors_across_every_microsoft_flow(result, rule_id):
    """The gate. Any error-severity finding here is a bug in this tool until
    proven otherwise, and the day Microsoft changes something the build says so."""
    hits = [f for f in result.findings if f.rule_id == rule_id]
    assert hits == [], [f"{f.flow}: {f.message}" for f in hits][:15]


def test_pal102_count_is_stable(result):
    """67 occurrences, 12 distinct references, 8 flows, at the pinned commit.

    The occurrence count is a range so an unrelated tweak does not fail the
    build, but a collapse to zero or an explosion does. The distinct counts are
    exact, because those are the numbers quoted publicly and they should not be
    allowed to drift quietly.
    """
    hits = [f for f in result.findings if f.rule_id == "PAL102"]
    assert 60 <= len(hits) <= 75, len(hits)
    distinct = {(f.flow, f.message.split("'")[1]) for f in hits}
    assert len(distinct) == 12, sorted(distinct)
    assert len({f.flow for f in hits}) == 8, sorted({f.flow for f in hits})
