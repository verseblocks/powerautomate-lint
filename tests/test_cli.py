"""CLI, loader and report tests.

The exit codes get real coverage because they are the contract a pipeline
depends on, and the difference between "clean" and "could not scan anything" is
the difference between a useful gate and a green build that checks nothing.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from powerautomate_lint.cli import main
from powerautomate_lint.model.loader import load
from powerautomate_lint.report import sarif

VENDOR = Path(__file__).parent.parent / "fixtures" / "vendor" / "coe"

BROKEN_FLOW = {
    "properties": {
        "definition": {
            "triggers": {"manual": {"type": "Request"}},
            "actions": {
                "Compose": {"type": "Compose", "inputs": "@outputs('Missing_Action')"}
            },
        }
    }
}

CLEAN_FLOW = {
    "properties": {
        "definition": {
            "triggers": {"manual": {"type": "Request"}},
            "actions": {
                "Get_a_row": {"type": "OpenApiConnection"},
                "Compose": {"type": "Compose", "inputs": "@outputs('Get_a_row')"},
            },
        }
    }
}


@pytest.fixture
def broken_dir(tmp_path: Path) -> Path:
    flows = tmp_path / "src" / "Workflows"
    flows.mkdir(parents=True)
    (flows / "Broken-11111111-1111-1111-1111-111111111111.json").write_text(
        json.dumps(BROKEN_FLOW), encoding="utf-8"
    )
    return tmp_path / "src"


@pytest.fixture
def clean_dir(tmp_path: Path) -> Path:
    flows = tmp_path / "src" / "Workflows"
    flows.mkdir(parents=True)
    (flows / "Clean-22222222-2222-2222-2222-222222222222.json").write_text(
        json.dumps(CLEAN_FLOW), encoding="utf-8"
    )
    return tmp_path / "src"


# --------------------------------------------------------------------------
# Exit codes
# --------------------------------------------------------------------------


def test_exit_zero_when_clean(clean_dir, capsys):
    assert main([str(clean_dir)]) == 0


def test_exit_one_when_an_error_is_found(broken_dir, capsys):
    assert main([str(broken_dir)]) == 1


def test_exit_two_when_nothing_could_be_scanned(tmp_path, capsys):
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert main([str(empty)]) == 2
    assert "no flows were scanned" in capsys.readouterr().err


def test_exit_two_on_a_missing_path(capsys):
    assert main(["./definitely-not-here"]) == 2


def test_exit_two_with_no_arguments(capsys):
    assert main([]) == 2


def test_fail_on_none_reports_findings_but_does_not_fail(broken_dir, capsys):
    """Useful for a report-only job that should never block a merge."""
    assert main([str(broken_dir), "--fail-on", "none"]) == 0
    assert "PAL101" in capsys.readouterr().out


def test_fail_on_note_catches_a_note(tmp_path, capsys):
    flows = tmp_path / "Workflows"
    flows.mkdir(parents=True)
    doc = {
        "properties": {
            "definition": {
                "actions": {"C": {"type": "Compose", "inputs": "@tolower('A')"}}
            }
        }
    }
    (flows / "Note-33333333-3333-3333-3333-333333333333.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )
    assert main([str(tmp_path), "--fail-on", "error"]) == 0
    assert main([str(tmp_path), "--fail-on", "note"]) == 1


# --------------------------------------------------------------------------
# Formats
# --------------------------------------------------------------------------


def test_list_rules(capsys):
    assert main(["--list-rules"]) == 0
    out = capsys.readouterr().out
    for rule_id in ("PAL101", "PAL102", "PAL103", "PAL106", "PAL107"):
        assert rule_id in out


def test_sarif_output_is_wellformed(broken_dir, tmp_path, capsys):
    out = tmp_path / "results.sarif"
    main([str(broken_dir), "--format", "sarif", "-o", str(out)])
    log = json.loads(out.read_text(encoding="utf-8"))

    assert log["version"] == "2.1.0"
    assert log["$schema"].endswith("sarif-schema-2.1.0.json")
    run = log["runs"][0]
    assert run["tool"]["driver"]["name"] == "powerautomate-lint"
    assert run["results"], "expected at least one result"

    result = run["results"][0]
    assert result["ruleId"] == "PAL101"
    assert result["level"] == "error"
    assert result["message"]["text"]
    uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert "\\" not in uri, "SARIF URIs must be POSIX so Windows and Linux agree"
    assert result["properties"]["jsonPointer"].startswith("/properties/definition")

    described = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert {r["ruleId"] for r in run["results"]} <= described


def test_sarif_is_byte_stable(broken_dir):
    first = sarif.dumps(_findings(broken_dir), root=broken_dir)
    second = sarif.dumps(_findings(broken_dir), root=broken_dir)
    assert first == second


def test_json_output(broken_dir, capsys):
    main([str(broken_dir), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["errors"] == 1
    assert payload["summary"]["flowsScanned"] == 1
    assert payload["findings"][0]["ruleId"] == "PAL101"


def test_markdown_output(broken_dir, capsys):
    main([str(broken_dir), "--format", "md"])
    out = capsys.readouterr().out
    assert out.startswith("# Power Automate lint results")
    assert "PAL101" in out
    assert "Missing_Action" in out


def test_markdown_says_so_when_clean(clean_dir, capsys):
    main([str(clean_dir), "--format", "md"])
    assert "No findings." in capsys.readouterr().out


def test_text_output_has_a_summary_line(broken_dir, capsys):
    main([str(broken_dir)])
    out = capsys.readouterr().out
    assert "1 flows, " in out
    assert "1 errors" in out


# --------------------------------------------------------------------------
# Rule selection
# --------------------------------------------------------------------------


def test_rules_filter_by_exact_id(broken_dir, capsys):
    main([str(broken_dir), "--format", "json", "--rules", "PAL103"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"] == []


def test_rules_filter_by_prefix(broken_dir, capsys):
    main([str(broken_dir), "--format", "json", "--rules", "PAL1"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"][0]["ruleId"] == "PAL101"


def test_unknown_rule_selector_is_an_error(broken_dir, capsys):
    assert main([str(broken_dir), "--rules", "NOPE999"]) == 2


# --------------------------------------------------------------------------
# Loader shapes
# --------------------------------------------------------------------------


def test_loads_a_single_flow_file(broken_dir):
    target = next(broken_dir.rglob("*.json"))
    result = load(target)
    assert len(result.flows) == 1
    assert result.errors == []


def test_loads_a_solution_zip(tmp_path):
    archive = tmp_path / "solution.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "Workflows/Broken-44444444-4444-4444-4444-444444444444.json",
            json.dumps(BROKEN_FLOW),
        )
        zf.writestr("Other/Solution.xml", "<ImportExportXml />")
    result = load(archive)
    assert len(result.flows) == 1
    assert "!" in result.flows[0].path


def test_zip_entry_lookup_is_case_insensitive(tmp_path):
    archive = tmp_path / "odd-casing.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "WORKFLOWS/Broken-55555555-5555-5555-5555-555555555555.json",
            json.dumps(BROKEN_FLOW),
        )
    assert len(load(archive).flows) == 1


def test_older_solution_layout_without_src(tmp_path):
    """SolutionPackage/Workflows, the layout 53 of 239 CoE flows still use."""
    flows = tmp_path / "SolutionPackage" / "Workflows"
    flows.mkdir(parents=True)
    (flows / "Old-66666666-6666-6666-6666-666666666666.json").write_text(
        json.dumps(CLEAN_FLOW), encoding="utf-8"
    )
    assert len(load(tmp_path).flows) == 1


def test_invalid_json_is_reported_not_raised(tmp_path):
    flows = tmp_path / "Workflows"
    flows.mkdir(parents=True)
    (flows / "Bad-77777777-7777-7777-7777-777777777777.json").write_text(
        "{not json", encoding="utf-8"
    )
    result = load(tmp_path)
    assert result.flows == []
    assert len(result.errors) == 1
    assert "invalid JSON" in result.errors[0].message


def test_bom_prefixed_json_loads(tmp_path):
    flows = tmp_path / "Workflows"
    flows.mkdir(parents=True)
    (flows / "Bom-88888888-8888-8888-8888-888888888888.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps(CLEAN_FLOW).encode("utf-8")
    )
    assert len(load(tmp_path).flows) == 1


def test_non_flow_json_is_ignored(tmp_path):
    """A package.json next to a Workflows folder must not be parsed as a flow."""
    (tmp_path / "package.json").write_text('{"name": "x"}', encoding="utf-8")
    flows = tmp_path / "Workflows"
    flows.mkdir()
    (flows / "Clean-99999999-9999-9999-9999-999999999999.json").write_text(
        json.dumps(CLEAN_FLOW), encoding="utf-8"
    )
    result = load(tmp_path)
    assert len(result.flows) == 1


def test_vendored_corpus_scans_through_the_cli(capsys):
    code = main([str(VENDOR), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["flowsScanned"] == 6
    assert payload["summary"]["errors"] == 0
    assert code == 0


def _findings(path: Path):
    from powerautomate_lint.analyze import analyze

    return analyze([path]).findings
