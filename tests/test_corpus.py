"""Assertions against real Microsoft-authored flows.

This is the file that can prove the implementation wrong, which is the only kind
of test worth having here. Hand-authored fixtures verify that a rule fires when
you build an input designed to make it fire. These verify something harder: that
the tool is correct about artefacts nobody wrote for its benefit.

Two assertions are load-bearing.

ZERO ERRORS ON MICROSOFT'S OWN FLOWS.
    PAL101, PAL103 and PAL106 must be silent across every vendored flow. An
    early prototype that read only the top level of ``definition.actions``
    produced 449 false PAL101 findings against the CoE core solution, and a
    version that resolved ``items()`` without case folding produced 55. Both
    bugs would sail past hand-authored fixtures. They cannot pass this.

THE U+00A0 DEPENDENCY IS REAL.
    Removing the no-break space from the lexer's whitespace set must break
    exactly three expressions in two flows. That is not a style preference. It
    is a behaviour of the runtime that Microsoft does not document and that its
    own shipping flows rely on.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from powerautomate_lint.analyze import analyze
from powerautomate_lint.expression import ExpressionSyntaxError, lexer
from powerautomate_lint.expression.template import parse_template
from powerautomate_lint.model.loader import load

VENDOR = Path(__file__).parent.parent / "fixtures" / "vendor" / "coe"
#: Flow files sit under a Workflows/ folder because that is the only shape the
#: loader accepts for a directory scan, and mirroring reality keeps the
#: fixtures honest about how the tool is actually pointed at input.
FLOWS = VENDOR / "Workflows"
NBSP = chr(0x00A0)


def _iter_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _iter_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_strings(value)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((VENDOR / "MANIFEST.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def result():
    return analyze([VENDOR])


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def test_vendored_fixtures_match_their_recorded_hashes(manifest):
    """The fixtures are upstream bytes, not something we edited into passing."""
    for entry in manifest["files"]:
        path = FLOWS / entry["file"]
        assert path.exists(), f"{entry['file']} is missing"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == entry["sha256"], f"{entry['file']} has been modified"


def test_manifest_records_a_pinned_commit(manifest):
    assert manifest["source"]["commit"] == "d4ceb8b718883d841ef9680dc344494ebd68d3b7"
    assert manifest["source"]["licence"] == "MIT"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def test_all_vendored_flows_load(result):
    assert result.flows_scanned == 6
    assert result.errors == []


def test_display_names_come_from_the_sidecar(result):
    names = {f.name for f in result.flows}
    # Sidecar names contain spaces and pipes; a stem-derived name never would.
    assert "CLEANUP HELPER - Solution Objects" in names
    assert "Admin | Capacity Alerts" in names


def test_every_expression_parses(result):
    """Zero syntax failures across every string in every vendored flow."""
    failures = []
    for flow in result.flows:
        for value in _iter_strings(flow.definition):
            if "@" not in value:
                continue
            try:
                parse_template(value)
            except ExpressionSyntaxError as exc:
                failures.append((flow.name, exc.code, value[:120]))
    assert failures == []


def test_a_meaningful_number_of_expressions_was_scanned(result):
    """Guards against a loader that silently finds nothing.

    Without this, every "zero findings" assertion below would also pass on an
    empty scan.
    """
    # The six vendored flows carry 784 expressions between them. The bar is set
    # well below that so a fixture edit does not break the guard, and well above
    # zero so an empty scan cannot pass it.
    assert result.expressions_scanned > 500


# --------------------------------------------------------------------------
# The U+00A0 dependency
# --------------------------------------------------------------------------


def test_removing_nbsp_from_whitespace_breaks_exactly_three_expressions(result, monkeypatch):
    """The discriminating test for the lexer's whitespace set.

    Microsoft's own flows separate concat() arguments with U+00A0 instead of a
    space. A lexer that does not treat it as whitespace rejects them.
    """
    monkeypatch.setattr(
        lexer, "WHITESPACE", frozenset(c for c in lexer.WHITESPACE if c != NBSP)
    )

    broken = []
    for flow in result.flows:
        for value in _iter_strings(flow.definition):
            if "@" not in value:
                continue
            try:
                parse_template(value)
            except ExpressionSyntaxError as exc:
                broken.append((flow.name, exc.code))

    assert len(broken) == 3, broken
    assert {code for _, code in broken} == {"unexpected-character"}
    assert {name for name, _ in broken} == {
        "Admin | Sync Template v3 CoE Solution Metadata",
        "SetupWizard>UpdateDataflowEnvironment",
    }


# --------------------------------------------------------------------------
# Zero false positives on Microsoft's code
# --------------------------------------------------------------------------


@pytest.mark.parametrize("rule_id", ["PAL101", "PAL103", "PAL106"])
def test_no_errors_on_microsofts_own_flows(result, rule_id):
    """Error-severity rules must be silent on artefacts Microsoft ships.

    If one of these starts firing, either the rule is wrong or Microsoft
    changed something. Either way the build should say so.
    """
    hits = [f for f in result.findings if f.rule_id == rule_id]
    assert hits == [], [f"{f.flow}: {f.message}" for f in hits]


# --------------------------------------------------------------------------
# PAL102, asserted by name against the real flows
# --------------------------------------------------------------------------


def test_pal102_finds_the_solution_objects_case_mismatches(result):
    """The five references in CLEANUPHELPER-SolutionObjects, by name."""
    messages = [
        f.message
        for f in result.findings
        if f.rule_id == "PAL102" and f.flow == "CLEANUP HELPER - Solution Objects"
    ]
    for ref, actual in [
        ("Get_Flow_To_Remove", "Get_Flow_to_Remove"),
        ("Get_BPF_To_Remove", "Get_BPF_to_Remove"),
        ("Get_App_To_Remove", "Get_App_to_Remove"),
        ("Get_BPF_To_Add", "Get_BPF_to_Add"),
        ("Get_App_To_Add", "Get_App_to_Add"),
    ]:
        assert any(
            f"outputs('{ref}')" in m and f"'{actual}'" in m for m in messages
        ), f"expected a PAL102 for {ref} -> {actual}; got {messages}"


def test_pal102_covers_the_other_known_flows(result):
    found = {
        (f.flow, f.message.split("(")[1].split(")")[0].strip("'"))
        for f in result.findings
        if f.rule_id == "PAL102"
    }
    assert ("SYNC HELPER - Apps", "Get_app_from_Inventory") in found
    assert ("Admin | Capacity Alerts", "Create_Close_To_Capacity") in found


def test_pal102_catches_the_items_case_mismatch(result):
    """items() resolution must case-fold like the action family does.

    Resolving loops without case folding turned 55 warnings into 55 errors
    against Microsoft's own flows.
    """
    hits = [
        f
        for f in result.findings
        if f.rule_id == "PAL102" and "items(" in f.message
    ]
    assert hits, "expected at least one items() case-mismatch warning"
    assert all("the loop is named" in f.message for f in hits)


# --------------------------------------------------------------------------
# Graph construction
# --------------------------------------------------------------------------


def test_container_descent_reaches_deeply_nested_actions():
    """A Foreach five containers deep must still be found and resolvable."""
    loaded = load(VENDOR)
    flow = next(
        f for f in loaded.flows if f.name == "CLEANUP HELPER - Cloud Flow User Shared With"
    )
    deep = flow.actions.get("Apply_to_each_New_User_to_Add")
    assert deep is not None, "nested Foreach was not collected"
    assert deep.type == "Foreach"
    assert deep.depth == 5
    assert deep.ancestors[0] == "Get_Power_Apps_User_Shared_With_Data"
    assert "Apply_to_each_New_User_to_Add" in flow.foreach_names


def test_pointers_are_json_pointers(result):
    for finding in result.findings:
        assert finding.pointer.startswith("/properties/definition"), finding.pointer


def test_findings_are_deterministically_orderable(result):
    once = [f.sort_key() for f in sorted(result.findings, key=lambda f: f.sort_key())]
    twice = [f.sort_key() for f in sorted(result.findings, key=lambda f: f.sort_key())]
    assert once == twice
