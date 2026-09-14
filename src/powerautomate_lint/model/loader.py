"""Finds flow definitions in whatever the user points at.

Four input shapes are supported, sniffed rather than declared:

    a single Workflows/<Name>-<GUID>.json
    an unpacked solution directory
    a solution .zip, managed or unmanaged
    a directory containing any of the above

Two directory layouts exist in the wild and both appear in Microsoft's own
repositories. Newer solutions unpack to ``SolutionPackage/src/Workflows/``,
older ones to ``SolutionPackage/Workflows/``. In the CoE Starter Kit the split
is 186 to 53. Matching on the ``Workflows`` directory name rather than a fixed
prefix handles both, and also handles a bare ``Workflows`` folder that someone
has copied out on its own.

Display names come from the ``.json.data.xml`` sidecar when there is one. A real
exported .zip has no sidecars; its metadata lives inline in customizations.xml.
Rather than parse that for v1, the zip reader falls back to the file stem with
the trailing GUID stripped, which is what the sidecar would have said anyway in
almost every case. Callers that need authoritative display names should unpack
first.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from .flow import Flow, build_flow

_GUID_SUFFIX = re.compile(
    r"-[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)


@dataclass
class LoadError:
    path: str
    message: str


@dataclass
class LoadResult:
    flows: list[Flow]
    errors: list[LoadError]


def _display_name(json_path: Path, stem: str) -> str:
    """Read the sidecar for a display name, else derive one from the stem."""
    sidecar = json_path.with_name(json_path.name + ".data.xml")
    if sidecar.exists():
        try:
            root = ElementTree.fromstring(sidecar.read_text(encoding="utf-8-sig"))
            name = root.findtext("Name")
            if name:
                return name.strip()
            # Older sidecars use an attribute instead of a child element.
            attr = root.get("Name")
            if attr:
                return attr.strip()
        except ElementTree.ParseError:
            pass
    return _GUID_SUFFIX.sub("", stem)


def _is_flow_json(path: Path) -> bool:
    if path.suffix.lower() != ".json":
        return False
    if path.name.lower().endswith(".data.xml"):
        return False
    return path.parent.name.lower() == "workflows"


def load(target: str | Path) -> LoadResult:
    """Load every flow reachable from ``target``."""
    path = Path(target)
    flows: list[Flow] = []
    errors: list[LoadError] = []

    if not path.exists():
        return LoadResult([], [LoadError(str(path), "path does not exist")])

    if path.is_file():
        if path.suffix.lower() == ".zip":
            _load_zip(path, flows, errors)
        elif path.suffix.lower() == ".json":
            _load_json_file(path, flows, errors)
        else:
            errors.append(
                LoadError(str(path), "not a .json flow definition or a .zip solution")
            )
        return LoadResult(flows, errors)

    # Directory. Collect flow JSONs at any depth, plus any solution zips.
    candidates = sorted(p for p in path.rglob("*.json") if _is_flow_json(p))
    if not candidates:
        # Maybe the caller pointed at a folder of exported zips.
        zips = sorted(path.rglob("*.zip"))
        if zips:
            for z in zips:
                _load_zip(z, flows, errors)
            return LoadResult(flows, errors)
        errors.append(
            LoadError(
                str(path),
                "no Workflows/*.json found; point at an unpacked solution, a "
                "Workflows folder, a flow .json or a solution .zip",
            )
        )
        return LoadResult(flows, errors)

    for candidate in candidates:
        _load_json_file(candidate, flows, errors)
    return LoadResult(flows, errors)


def _load_json_file(path: Path, flows: list[Flow], errors: list[LoadError]) -> None:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        errors.append(LoadError(str(path), f"invalid JSON: {exc.msg} at line {exc.lineno}"))
        return
    except OSError as exc:
        errors.append(LoadError(str(path), f"cannot read: {exc}"))
        return

    if not isinstance(document, dict):
        errors.append(LoadError(str(path), "top level is not a JSON object"))
        return

    flows.append(
        build_flow(
            document,
            name=_display_name(path, path.stem),
            path=str(path),
        )
    )


def _load_zip(path: Path, flows: list[Flow], errors: list[LoadError]) -> None:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        errors.append(LoadError(str(path), f"cannot open zip: {exc}"))
        return

    with archive:
        # Zip entry casing is not guaranteed, so match case-insensitively.
        names = [
            n
            for n in archive.namelist()
            if n.lower().endswith(".json")
            and "/workflows/" in ("/" + n.lower())
            and not n.lower().endswith(".data.xml")
        ]
        if not names:
            errors.append(
                LoadError(str(path), "no Workflows/*.json entries inside the zip")
            )
            return

        for entry in sorted(names):
            try:
                raw = archive.read(entry).decode("utf-8-sig")
                document = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                errors.append(LoadError(f"{path}!{entry}", f"invalid JSON: {exc}"))
                continue
            if not isinstance(document, dict):
                errors.append(
                    LoadError(f"{path}!{entry}", "top level is not a JSON object")
                )
                continue
            stem = Path(entry).stem
            flows.append(
                build_flow(
                    document,
                    name=_GUID_SUFFIX.sub("", stem),
                    path=f"{path}!{entry}",
                )
            )
