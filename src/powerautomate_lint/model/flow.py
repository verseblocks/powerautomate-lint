"""The flow model: actions, triggers, and the containers they nest inside.

Building this correctly is most of the work, and getting it wrong is silent. A
resolver that only reads the top level of ``definition.actions`` reports
hundreds of references as unresolved, because the action they name is nested
three containers deep. When this model was first prototyped against the 114
core CoE flows, a top-level-only walk produced 449 false "unresolved reference"
findings. The correct descent produces zero.

Five container shapes hold child actions, and they do not agree on where they
put them:

    Scope       -> .actions
    If          -> .actions  and  .else.actions
    Foreach     -> .actions
    Until       -> .actions
    Switch      -> .cases.<name>.actions  and  .default.actions

Names in ``definition.actions`` keys are the authoritative identifiers, but a
reference does not spell them the same way: the designer writes a space and the
expression writes an underscore. ``outputs('Get_a_row')`` names the action
``Get a row``. So every lookup goes through the same canonicalisation.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


def canonical(name: str) -> str:
    """Convert an action name to the form an expression reference uses."""
    return name.replace(" ", "_")


@dataclass
class Action:
    #: The key as it appears in the definition, spaces and all.
    name: str
    #: The reference form, spaces replaced by underscores.
    ref_name: str
    #: e.g. ``OpenApiConnection``, ``Scope``, ``Foreach``, ``InitializeVariable``.
    type: str
    #: RFC 6901 JSON pointer to this action's object within the flow document.
    pointer: str
    #: Names of the actions this one declares in ``runAfter``, canonicalised.
    run_after: tuple[str, ...] = ()
    #: Container nesting, outermost first, canonicalised. Empty at top level.
    ancestors: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def depth(self) -> int:
        return len(self.ancestors)

    @property
    def is_container(self) -> bool:
        return self.type in ("Scope", "If", "Foreach", "Until", "Switch")


@dataclass
class Trigger:
    name: str
    ref_name: str
    type: str
    pointer: str
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class Flow:
    #: Display name, from the sidecar or the file stem.
    name: str
    #: Source path, for reporting.
    path: str
    definition: dict[str, Any] = field(default_factory=dict, repr=False)
    actions: dict[str, Action] = field(default_factory=dict)
    triggers: dict[str, Trigger] = field(default_factory=dict)
    #: Pointer prefix of the definition within the document, e.g.
    #: ``/properties/definition``. Findings need document-relative pointers.
    definition_pointer: str = ""

    # -- lookup -----------------------------------------------------------

    def find_action(self, ref: str) -> Action | None:
        """Exact lookup by reference name."""
        return self.actions.get(canonical(ref))

    def find_action_folded(self, ref: str) -> Action | None:
        """Case-insensitive lookup.

        Kept separate from ``find_action`` on purpose: the difference between
        the two is the entire content of rule PAL102. Nine references across
        five flows in the CoE corpus resolve only through this path, including
        ``outputs('Get_Flow_To_Remove')`` against an action actually named
        ``Get_Flow_to_Remove``.
        """
        target = canonical(ref).lower()
        for key, action in self.actions.items():
            if key.lower() == target:
                return action
        return None

    @property
    def variable_names(self) -> dict[str, Action]:
        """Variables initialised anywhere in the flow, keyed by lowered name.

        Variable names are matched case-insensitively because the runtime does;
        two InitializeVariable actions differing only in case would collide.
        """
        out: dict[str, Action] = {}
        for action in self.actions.values():
            if action.type != "InitializeVariable":
                continue
            for var in action.raw.get("inputs", {}).get("variables", []) or []:
                name = var.get("name")
                if isinstance(name, str) and name:
                    out.setdefault(name.lower(), action)
        return out

    @property
    def foreach_names(self) -> set[str]:
        """Canonical names of Foreach and Until containers.

        ``items('Apply_to_each')`` names one of these, so a reference to a
        Foreach is valid even though it is not an ordinary action output.
        """
        return {
            name
            for name, action in self.actions.items()
            if action.type in ("Foreach", "Until")
        }


_CHILD_KEYS = ("actions",)


def _iter_child_blocks(spec: dict[str, Any], pointer: str) -> Iterator[tuple[dict, str]]:
    """Yield every (actions-dict, pointer) block a container holds."""
    for key in _CHILD_KEYS:
        block = spec.get(key)
        if isinstance(block, dict):
            yield block, f"{pointer}/{key}"

    # If/else
    else_block = spec.get("else")
    if isinstance(else_block, dict):
        inner = else_block.get("actions")
        if isinstance(inner, dict):
            yield inner, f"{pointer}/else/actions"

    # Switch cases and default
    cases = spec.get("cases")
    if isinstance(cases, dict):
        for case_name, case in cases.items():
            if isinstance(case, dict):
                inner = case.get("actions")
                if isinstance(inner, dict):
                    yield inner, f"{pointer}/cases/{_escape(case_name)}/actions"
    default = spec.get("default")
    if isinstance(default, dict):
        inner = default.get("actions")
        if isinstance(inner, dict):
            yield inner, f"{pointer}/default/actions"


def _escape(segment: str) -> str:
    """Escape a JSON pointer segment per RFC 6901."""
    return segment.replace("~", "~0").replace("/", "~1")


def _run_after(spec: dict[str, Any]) -> tuple[str, ...]:
    block = spec.get("runAfter")
    if not isinstance(block, dict):
        return ()
    return tuple(canonical(k) for k in block.keys())


def build_flow(
    document: dict[str, Any],
    *,
    name: str,
    path: str,
) -> Flow:
    """Build a Flow from a parsed ``Workflows/*.json`` document.

    Handles both document shapes seen in the wild: the unpacked-solution form
    where the definition sits under ``properties.definition``, and the bare
    form where it is at the root.
    """
    if isinstance(document.get("properties"), dict) and isinstance(
        document["properties"].get("definition"), dict
    ):
        definition = document["properties"]["definition"]
        def_pointer = "/properties/definition"
    elif isinstance(document.get("definition"), dict):
        definition = document["definition"]
        def_pointer = "/definition"
    else:
        definition = document
        def_pointer = ""

    flow = Flow(
        name=name,
        path=path,
        definition=definition,
        definition_pointer=def_pointer,
    )

    triggers = definition.get("triggers")
    if isinstance(triggers, dict):
        for tname, tspec in triggers.items():
            if not isinstance(tspec, dict):
                continue
            flow.triggers[canonical(tname)] = Trigger(
                name=tname,
                ref_name=canonical(tname),
                type=str(tspec.get("type", "")),
                pointer=f"{def_pointer}/triggers/{_escape(tname)}",
                raw=tspec,
            )

    root = definition.get("actions")
    if isinstance(root, dict):
        _collect(root, f"{def_pointer}/actions", (), flow)

    return flow


def _collect(
    block: dict[str, Any],
    pointer: str,
    ancestors: tuple[str, ...],
    flow: Flow,
) -> None:
    for aname, spec in block.items():
        if not isinstance(spec, dict):
            continue
        ptr = f"{pointer}/{_escape(aname)}"
        action = Action(
            name=aname,
            ref_name=canonical(aname),
            type=str(spec.get("type", "")),
            pointer=ptr,
            run_after=_run_after(spec),
            ancestors=ancestors,
            raw=spec,
        )
        # Last writer wins on a duplicate key, matching json.loads behaviour.
        flow.actions[action.ref_name] = action

        for child_block, child_pointer in _iter_child_blocks(spec, ptr):
            _collect(
                child_block,
                child_pointer,
                ancestors + (action.ref_name,),
                flow,
            )
