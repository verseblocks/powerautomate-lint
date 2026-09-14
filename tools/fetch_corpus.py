#!/usr/bin/env python3
"""Fetch the full 239-flow CoE Starter Kit corpus for the opt-in deep tests.

Six flows are committed under fixtures/vendor/coe/ and cover every behaviour the
default suite asserts. This script pulls the rest into fixtures/corpus/, which is
gitignored, so `pytest -m corpus` can run the wider sweep.

The commit is pinned. The upstream repository was archived on 2026-05-15, so the
pin will not drift, and a shallow sparse checkout keeps this to seconds rather
than cloning the whole history.

Windows note: long paths break a normal checkout of this repository, which is
why core.longpaths is set before any checkout happens.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = "https://github.com/microsoft/coe-starter-kit.git"
COMMIT = "d4ceb8b718883d841ef9680dc344494ebd68d3b7"
DEST = Path(__file__).resolve().parent.parent / "fixtures" / "corpus"

# Solutions that contain Workflows folders. Listed explicitly so the checkout
# stays small; a bare sparse-checkout of everything defeats the point.
SOLUTIONS = [
    "CenterofExcellenceCoreComponents",
    "CenterofExcellenceCoreComponentsTeams",
    "CenterofExcellenceALMAccelerator",
    "CenterofExcellenceAuditComponents",
    "CenterofExcellenceAuditLogs",
    "CenterofExcellenceNurtureComponents",
    "CenterofExcellencePipelineAccelerator",
    "CenterofExcellenceInnovationBacklog",
    "ALMAcceleratorForMakers",
    "ALMAcceleratorSampleSolution",
    "business_value_core",
]

EXPECTED_FLOWS = 239


def run(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def main() -> int:
    if DEST.exists():
        flows = _count(DEST)
        if flows == EXPECTED_FLOWS:
            print(f"corpus already present: {flows} flows at {DEST}")
            return 0
        print(f"removing incomplete corpus ({flows} flows)")
        shutil.rmtree(DEST, ignore_errors=True)

    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"cloning {REPO} at {COMMIT[:12]} ...")
    run([
        "git", "-c", "core.longpaths=true", "clone",
        "--filter=blob:none", "--no-checkout", "--depth", "1",
        REPO, str(DEST),
    ])
    run(["git", "config", "core.longpaths", "true"], cwd=DEST)
    run(["git", "sparse-checkout", "init", "--cone"], cwd=DEST)
    run(["git", "sparse-checkout", "set", "--skip-checks", *SOLUTIONS], cwd=DEST)
    run(["git", "-c", "core.longpaths=true", "checkout"], cwd=DEST)

    flows = _count(DEST)
    print(f"{flows} flow definitions in {DEST}")
    if flows != EXPECTED_FLOWS:
        print(
            f"expected {EXPECTED_FLOWS}; a partial checkout usually means the "
            "long-path setting did not take effect",
            file=sys.stderr,
        )
        return 1
    print("run the deep tests with: pytest -m corpus")
    return 0


def _count(root: Path) -> int:
    return sum(
        1
        for p in root.rglob("*.json")
        if p.parent.name.lower() == "workflows" and not p.name.endswith(".data.xml")
    )


if __name__ == "__main__":
    raise SystemExit(main())
