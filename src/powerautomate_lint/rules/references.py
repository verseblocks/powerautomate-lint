"""Reference-integrity rules: does every expression name something real.

This family is the reason the project exists. Nothing else offline resolves
``outputs('X')`` against the flow's actual action graph, so nothing else can
tell you that ``X`` is not there.

The rules:

    PAL101  the reference names nothing, even case-insensitively      error
    PAL102  the reference resolves only after case folding            warning
    PAL103  variables() with no InitializeVariable anywhere           error
    PAL106  unknown function name                                     error
    PAL107  function name cased differently from the documentation    note

PAL102 exists because of a behaviour Microsoft does not document. In the CoE
Starter Kit, ``CLEANUPHELPER-SolutionObjects`` calls
``outputs('Get_Flow_To_Remove')`` while the action is named
``Get_Flow_to_Remove``. Those flows ship and run, so the runtime is folding
case. That makes the reference work today and break the moment anyone renames
the action through the designer, which is a warning rather than an error, and
is exactly the kind of thing a reviewer wants flagged.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from ..expression import (
    ExpressionSyntaxError,
    FunctionCall,
    Interpolation,
    Literal,
    Node,
    iter_expressions,
)
from ..expression.ast import Index, PropertyAccess
from ..model.flow import Flow, canonical
from .base import Finding, Rule, registry
from .catalog import KNOWN_FUNCTIONS, canonical_casing

#: Functions whose first argument names an action.
_ACTION_REF_FUNCTIONS = frozenset({"outputs", "body", "actions", "result"})
#: Functions whose first argument names a Foreach or Until container.
_LOOP_REF_FUNCTIONS = frozenset({"items", "iterationindexes"})


def _walk(node: Node) -> Iterator[Node]:
    yield node
    if isinstance(node, FunctionCall):
        for arg in node.args:
            yield from _walk(arg)
    elif isinstance(node, PropertyAccess):
        yield from _walk(node.target)
    elif isinstance(node, Index):
        yield from _walk(node.target)
        yield from _walk(node.index)


def _iter_strings(obj: object, pointer: str) -> Iterator[tuple[str, str]]:
    """Yield every (string value, JSON pointer) in a flow document subtree."""
    if isinstance(obj, str):
        yield obj, pointer
    elif isinstance(obj, dict):
        for key, value in obj.items():
            esc = str(key).replace("~", "~0").replace("/", "~1")
            yield from _iter_strings(value, f"{pointer}/{esc}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _iter_strings(value, f"{pointer}/{i}")


def _iter_calls(flow: Flow) -> Iterator[tuple[FunctionCall, Interpolation, str]]:
    """Every function call in every expression in the flow, with its pointer."""
    for value, pointer in _iter_strings(flow.definition, flow.definition_pointer):
        if "@" not in value:
            continue
        try:
            interpolations = iter_expressions(value)
        except ExpressionSyntaxError:
            # Syntax is PAL301's problem, not this family's. Skipping keeps a
            # malformed expression from producing a cascade of bogus findings.
            continue
        for interp in interpolations:
            for node in _walk(interp.node):
                if isinstance(node, FunctionCall):
                    yield node, interp, pointer


def _first_string_arg(call: FunctionCall) -> str | None:
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, Literal) and first.kind == "string":
        return str(first.value)
    return None


def _resolvable_targets(flow: Flow) -> set[str]:
    """Everything an action-reference is allowed to name."""
    targets = set(flow.actions)
    targets |= set(flow.triggers)
    return targets


def check_action_references(flow: Flow) -> Iterable[Finding]:
    """PAL101 and PAL102 in one pass, since they share all the work.

    Both the action family and the loop family resolve through the same three
    outcomes: exact hit, case-folded hit, or nothing. Sharing the resolution is
    not just tidiness. Resolving ``items()`` without case folding produced 55
    false PAL101 errors against Microsoft's own flows, every one of them a
    reference like ``items('Apply_to_each_new_User_to_Add')`` against an action
    named ``Apply_to_each_New_User_to_Add``. Those are PAL102 warnings, and a
    linter that calls them errors is one nobody runs twice.
    """
    findings: list[Finding] = []
    actions_and_triggers = _resolvable_targets(flow)
    loops = flow.foreach_names

    for call, interp, pointer in _iter_calls(flow):
        fname = call.name.lower()
        if fname in _ACTION_REF_FUNCTIONS:
            universe, noun = actions_and_triggers, "action or trigger"
        elif fname in _LOOP_REF_FUNCTIONS:
            universe, noun = loops, "loop"
        else:
            continue

        ref = _first_string_arg(call)
        if ref is None:
            # A computed reference, e.g. outputs(variables('n')). Not
            # statically resolvable, and not an error.
            continue

        finding = _resolve(
            call=call,
            ref=ref,
            universe=universe,
            noun=noun,
            flow=flow,
            interp=interp,
            pointer=pointer,
        )
        if finding is not None:
            findings.append(finding)

    return findings


def _resolve(
    *,
    call: FunctionCall,
    ref: str,
    universe: set[str],
    noun: str,
    flow: Flow,
    interp: Interpolation,
    pointer: str,
) -> Finding | None:
    """Resolve one reference against a set of legal names.

    Returns None when the reference is fine, a PAL102 warning when it only
    resolves case-insensitively, and a PAL101 error when it resolves to nothing.
    """
    key = canonical(ref)
    if key in universe:
        return None

    lowered = key.lower()
    for candidate in universe:
        if candidate.lower() == lowered:
            return Finding(
                rule_id="PAL102",
                severity="warning",
                message=(
                    f"{call.name}('{ref}') resolves only because the runtime "
                    f"ignores case; the {noun} is named '{candidate}'"
                ),
                file=flow.path,
                flow=flow.name,
                pointer=pointer,
                expression=interp.source,
                offset=call.offset,
                detail=(
                    "This works today. It stops working the moment the target is "
                    "renamed, and nothing in the designer will warn you. Match "
                    "the case exactly."
                ),
            )

    return Finding(
        rule_id="PAL101",
        severity="error",
        message=f"{call.name}('{ref}') names no {noun} in this flow",
        file=flow.path,
        flow=flow.name,
        pointer=pointer,
        expression=interp.source,
        offset=call.offset,
        detail=(
            "At run time this yields null rather than failing, so the flow "
            "reports success while passing a missing value downstream."
        ),
    )


def check_variables(flow: Flow) -> Iterable[Finding]:
    """PAL103: a variable is read but never initialised."""
    findings: list[Finding] = []
    initialised = flow.variable_names

    for call, interp, pointer in _iter_calls(flow):
        if call.name.lower() != "variables":
            continue
        ref = _first_string_arg(call)
        if ref is None:
            continue
        if ref.lower() in initialised:
            continue
        findings.append(
            Finding(
                rule_id="PAL103",
                severity="error",
                message=f"variables('{ref}') is read but never initialised in this flow",
                file=flow.path,
                flow=flow.name,
                pointer=pointer,
                expression=interp.source,
                offset=call.offset,
                detail=(
                    "Initialize variable must appear somewhere in the flow. "
                    "Reading an uninitialised variable fails the run."
                ),
            )
        )
    return findings


def check_functions(flow: Flow) -> Iterable[Finding]:
    """PAL106 unknown function, PAL107 non-documented casing."""
    findings: list[Finding] = []
    seen_casing: set[tuple[str, str]] = set()

    for call, interp, pointer in _iter_calls(flow):
        lowered = call.name.lower()
        if lowered not in KNOWN_FUNCTIONS:
            findings.append(
                Finding(
                    rule_id="PAL106",
                    severity="error",
                    message=f"'{call.name}' is not a Workflow Definition Language function",
                    file=flow.path,
                    flow=flow.name,
                    pointer=pointer,
                    expression=interp.source,
                    offset=call.offset,
                )
            )
            continue

        documented = canonical_casing(lowered)
        if documented is not None and call.name != documented:
            key = (call.name, documented)
            if key in seen_casing:
                continue
            seen_casing.add(key)
            findings.append(
                Finding(
                    rule_id="PAL107",
                    severity="note",
                    message=(
                        f"'{call.name}' is documented as '{documented}'"
                    ),
                    file=flow.path,
                    flow=flow.name,
                    pointer=pointer,
                    expression=interp.source,
                    offset=call.offset,
                    detail=(
                        "The runtime accepts either. Matching the documented "
                        "casing makes the expression searchable."
                    ),
                )
            )
    return findings


registry.register(
    Rule(
        id="PAL101",
        severity="error",
        summary="Expression references an action that does not exist",
        help=(
            "outputs(), body(), actions() and result() must name an action or "
            "trigger declared in the same flow. An unresolved reference "
            "evaluates to null at run time rather than failing, so the flow "
            "reports success while silently passing a missing value downstream."
        ),
        check=check_action_references,
    )
)

registry.register(
    Rule(
        id="PAL102",
        severity="warning",
        summary="Reference resolves only because the runtime ignores case",
        help=(
            "The referenced action exists but is spelled with different case. "
            "The runtime folds case so this works today, and it breaks the "
            "moment the action is renamed. Microsoft's own CoE Starter Kit "
            "contains nine of these across five flows."
        ),
        check=lambda flow: (),  # produced by check_action_references
    )
)

registry.register(
    Rule(
        id="PAL103",
        severity="error",
        summary="Variable is read but never initialised",
        help=(
            "variables('name') requires an Initialize variable action "
            "somewhere in the flow. Reading an uninitialised variable fails "
            "the run."
        ),
        check=check_variables,
    )
)

registry.register(
    Rule(
        id="PAL106",
        severity="error",
        summary="Unknown Workflow Definition Language function",
        help=(
            "The function name does not appear in the documented function "
            "catalogue, case-insensitively. Usually a typo; occasionally a "
            "function from a different expression language."
        ),
        check=check_functions,
    )
)

registry.register(
    Rule(
        id="PAL107",
        severity="note",
        summary="Function name cased differently from the documentation",
        help=(
            "The runtime accepts any casing. Matching the documented spelling "
            "keeps expressions greppable across a repository."
        ),
        check=lambda flow: (),  # produced by check_functions
    )
)
