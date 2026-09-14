"""Rule behaviour against purpose-built flows.

Each rule gets a positive case that must fire and a negative case that must
stay silent. The negative cases matter more: a rule that cannot be quiet is a
rule nobody leaves switched on.

Flows are built inline rather than loaded from disk so the input that produces
a finding is visible next to the assertion.
"""

from __future__ import annotations

import pytest

from powerautomate_lint.model.flow import build_flow
from powerautomate_lint.rules import CHECKS
from powerautomate_lint.rules.base import severity_rank


def make_flow(actions: dict, triggers: dict | None = None, name: str = "Test flow"):
    document = {
        "properties": {
            "definition": {
                "triggers": triggers or {},
                "actions": actions,
            }
        }
    }
    return build_flow(document, name=name, path="test.json")


def run(flow) -> list:
    out = []
    for check in CHECKS:
        out.extend(check(flow))
    return out


def ids(findings) -> list[str]:
    return sorted(f.rule_id for f in findings)


# --------------------------------------------------------------------------
# PAL101: reference names nothing
# --------------------------------------------------------------------------


def test_pal101_fires_on_a_missing_action():
    flow = make_flow(
        {
            "Compose": {
                "type": "Compose",
                "inputs": "@outputs('Does_Not_Exist')",
            }
        }
    )
    findings = run(flow)
    assert ids(findings) == ["PAL101"]
    assert "Does_Not_Exist" in findings[0].message
    assert findings[0].severity == "error"


def test_pal101_silent_when_the_action_exists():
    flow = make_flow(
        {
            "Get_a_row": {"type": "OpenApiConnection"},
            "Compose": {"type": "Compose", "inputs": "@outputs('Get_a_row')"},
        }
    )
    assert run(flow) == []


def test_pal101_resolves_spaces_to_underscores():
    """outputs('Get_a_row') names the action 'Get a row'."""
    flow = make_flow(
        {
            "Get a row": {"type": "OpenApiConnection"},
            "Compose": {"type": "Compose", "inputs": "@outputs('Get_a_row')"},
        }
    )
    assert run(flow) == []


def test_pal101_accepts_a_trigger_reference():
    flow = make_flow(
        {"Compose": {"type": "Compose", "inputs": "@outputs('When_a_row_is_added')"}},
        triggers={"When a row is added": {"type": "OpenApiConnectionWebhook"}},
    )
    assert run(flow) == []


def test_pal101_ignores_a_computed_reference():
    """outputs(variables('n')) is not statically resolvable, and not an error."""
    flow = make_flow(
        {
            "Init": {
                "type": "InitializeVariable",
                "inputs": {"variables": [{"name": "n", "type": "string"}]},
            },
            "Compose": {"type": "Compose", "inputs": "@outputs(variables('n'))"},
        }
    )
    assert run(flow) == []


def test_pal101_resolves_actions_nested_in_every_container_shape():
    """Scope, If/else, Foreach, Until and Switch cases/default all descend."""
    flow = make_flow(
        {
            "Scope": {
                "type": "Scope",
                "actions": {"In_Scope": {"type": "Compose"}},
            },
            "Condition": {
                "type": "If",
                "actions": {"In_If": {"type": "Compose"}},
                "else": {"actions": {"In_Else": {"type": "Compose"}}},
            },
            "Apply_to_each": {
                "type": "Foreach",
                "actions": {"In_Foreach": {"type": "Compose"}},
            },
            "Do_until": {
                "type": "Until",
                "actions": {"In_Until": {"type": "Compose"}},
            },
            "Switch": {
                "type": "Switch",
                "cases": {"Case_1": {"actions": {"In_Case": {"type": "Compose"}}}},
                "default": {"actions": {"In_Default": {"type": "Compose"}}},
            },
            "Consume": {
                "type": "Compose",
                "inputs": (
                    "@concat(outputs('In_Scope'), outputs('In_If'), "
                    "outputs('In_Else'), outputs('In_Foreach'), "
                    "outputs('In_Until'), outputs('In_Case'), outputs('In_Default'))"
                ),
            },
        }
    )
    assert run(flow) == []


# --------------------------------------------------------------------------
# PAL102: resolves only under case folding
# --------------------------------------------------------------------------


def test_pal102_fires_on_a_case_only_match():
    flow = make_flow(
        {
            "Get_Flow_to_Remove": {"type": "OpenApiConnection"},
            "Compose": {"type": "Compose", "inputs": "@outputs('Get_Flow_To_Remove')"},
        }
    )
    findings = run(flow)
    assert ids(findings) == ["PAL102"]
    assert findings[0].severity == "warning"
    assert "Get_Flow_to_Remove" in findings[0].message


def test_pal102_applies_to_loops_too():
    flow = make_flow(
        {
            "Apply_to_each_New_User": {
                "type": "Foreach",
                "actions": {
                    "Compose": {
                        "type": "Compose",
                        "inputs": "@items('Apply_to_each_new_User')",
                    }
                },
            }
        }
    )
    findings = run(flow)
    assert ids(findings) == ["PAL102"]
    assert "the loop is named" in findings[0].message


def test_exact_case_produces_nothing():
    flow = make_flow(
        {
            "Apply_to_each": {
                "type": "Foreach",
                "actions": {
                    "Compose": {"type": "Compose", "inputs": "@items('Apply_to_each')"}
                },
            }
        }
    )
    assert run(flow) == []


def test_items_naming_a_non_loop_is_an_error_not_a_warning():
    flow = make_flow(
        {
            "Get_a_row": {"type": "OpenApiConnection"},
            "Compose": {"type": "Compose", "inputs": "@items('Get_a_row')"},
        }
    )
    findings = run(flow)
    assert ids(findings) == ["PAL101"]
    assert "names no loop" in findings[0].message


# --------------------------------------------------------------------------
# PAL103: uninitialised variable
# --------------------------------------------------------------------------


def test_pal103_fires_when_no_initialise_exists():
    flow = make_flow(
        {"Compose": {"type": "Compose", "inputs": "@variables('counter')"}}
    )
    findings = run(flow)
    assert ids(findings) == ["PAL103"]
    assert findings[0].severity == "error"


def test_pal103_silent_when_initialised_anywhere():
    flow = make_flow(
        {
            "Scope": {
                "type": "Scope",
                "actions": {
                    "Init": {
                        "type": "InitializeVariable",
                        "inputs": {"variables": [{"name": "counter", "type": "integer"}]},
                    }
                },
            },
            "Compose": {"type": "Compose", "inputs": "@variables('counter')"},
        }
    )
    assert run(flow) == []


def test_pal103_matches_variable_names_case_insensitively():
    flow = make_flow(
        {
            "Init": {
                "type": "InitializeVariable",
                "inputs": {"variables": [{"name": "Counter", "type": "integer"}]},
            },
            "Compose": {"type": "Compose", "inputs": "@variables('counter')"},
        }
    )
    assert run(flow) == []


# --------------------------------------------------------------------------
# PAL106 / PAL107: the function catalogue
# --------------------------------------------------------------------------


def test_pal106_fires_on_an_unknown_function():
    flow = make_flow(
        {"Compose": {"type": "Compose", "inputs": "@totallyNotAFunction('x')"}}
    )
    findings = run(flow)
    assert ids(findings) == ["PAL106"]


@pytest.mark.parametrize("spelling", ["utcNow", "utcnow", "UTCNOW", "toLower", "tolower"])
def test_known_functions_are_accepted_in_any_case(spelling):
    flow = make_flow({"Compose": {"type": "Compose", "inputs": f"@{spelling}()"}})
    assert [f.rule_id for f in run(flow) if f.rule_id == "PAL106"] == []


def test_pal107_notes_undocumented_casing():
    flow = make_flow({"Compose": {"type": "Compose", "inputs": "@tolower('A')"}})
    findings = [f for f in run(flow) if f.rule_id == "PAL107"]
    assert len(findings) == 1
    assert findings[0].severity == "note"
    assert "toLower" in findings[0].message


def test_pal107_silent_on_documented_casing():
    flow = make_flow({"Compose": {"type": "Compose", "inputs": "@toLower('A')"}})
    assert [f for f in run(flow) if f.rule_id == "PAL107"] == []


def test_pal107_reports_each_distinct_misspelling_once_per_flow():
    flow = make_flow(
        {
            "A": {"type": "Compose", "inputs": "@tolower('a')"},
            "B": {"type": "Compose", "inputs": "@tolower('b')"},
        }
    )
    assert len([f for f in run(flow) if f.rule_id == "PAL107"]) == 1


# --------------------------------------------------------------------------
# Cross-cutting
# --------------------------------------------------------------------------


def test_a_malformed_expression_does_not_cascade():
    """A syntax error must not produce a pile of reference findings."""
    flow = make_flow(
        {"Compose": {"type": "Compose", "inputs": "@concat('unclosed"}}
    )
    assert run(flow) == []


def test_findings_carry_a_pointer_into_the_document():
    flow = make_flow(
        {"Compose": {"type": "Compose", "inputs": "@outputs('Nope')"}}
    )
    finding = run(flow)[0]
    assert finding.pointer == "/properties/definition/actions/Compose/inputs"


def test_severity_ordering():
    assert severity_rank("error") > severity_rank("warning") > severity_rank("note")


def test_bare_definition_at_the_document_root_is_supported():
    """Some exports put the definition at the root rather than under properties."""
    flow = build_flow(
        {"definition": {"actions": {"Compose": {"type": "Compose", "inputs": "@outputs('X')"}}}},
        name="Bare",
        path="bare.json",
    )
    findings = run(flow)
    assert ids(findings) == ["PAL101"]
    assert findings[0].pointer.startswith("/definition/")
