"""The Workflow Definition Language function catalogue.

Keys are lowercase; values are the casing Microsoft's reference documentation
uses. Lookups are always case-folded because the runtime is case-insensitive,
which is why ``toLower``, ``tolower`` and ``ToLower`` all work.

Completeness is verified rather than asserted: the test suite runs PAL106 over
239 Microsoft-authored flows and requires zero unknown-function findings. A
function missing from this table would surface there immediately as a false
positive on Microsoft's own code.
"""

from __future__ import annotations

#: Documented spellings, grouped as the reference documentation groups them.
_DOCUMENTED: tuple[str, ...] = (
    # String
    "chunk", "concat", "endsWith", "formatNumber", "guid", "indexOf",
    "isFloat", "isInt", "lastIndexOf", "length", "nthIndexOf", "replace",
    "slice", "split", "startsWith", "substring", "toLower", "toUpper", "trim",
    # Collection
    "contains", "empty", "first", "intersection", "item", "join", "last",
    "reverse", "skip", "sort", "take", "union",
    # Logical
    "and", "equals", "greater", "greaterOrEquals", "if", "less",
    "lessOrEquals", "not", "or", "xor",
    # Conversion
    "array", "base64", "base64ToBinary", "base64ToString", "binary", "bool",
    "createArray", "dataUri", "dataUriToBinary", "dataUriToString", "decimal",
    "decodeBase64", "decodeDataUri", "decodeUriComponent",
    "encodeUriComponent", "float", "int", "json", "string", "uriComponent",
    "uriComponentToBinary", "uriComponentToString", "xml",
    # Math
    "add", "div", "max", "min", "mod", "mul", "rand", "range", "sub",
    # Date and time
    "addDays", "addHours", "addMinutes", "addSeconds", "addToTime",
    "convertFromUtc", "convertTimeZone", "convertToUtc", "dateDifference",
    "dayOfMonth", "dayOfWeek", "dayOfYear", "formatDateTime", "getFutureTime",
    "getPastTime", "parseDateTime", "startOfDay", "startOfHour",
    "startOfMonth", "subtractFromTime", "ticks", "utcNow",
    # Referencing runtime values
    "action", "actionBody", "actionOutputs", "actions", "body",
    "formDataMultiValues", "formDataValue", "items", "iterationIndexes",
    "listCallbackUrl", "multipartBody", "outputs", "parameters", "result",
    "trigger", "triggerBody", "triggerFormDataMultiValues",
    "triggerFormDataValue", "triggerMultipartBody", "triggerOutputs",
    "variables", "workflow",
    # URI parsing
    "uriHost", "uriPath", "uriPathAndQuery", "uriPort", "uriQuery",
    "uriScheme",
    # JSON manipulation
    "addProperty", "coalesce", "removeProperty", "setProperty",
    # XML
    "xpath",
)

#: Lowercase name -> documented spelling.
CANONICAL: dict[str, str] = {name.lower(): name for name in _DOCUMENTED}

#: Names accepted by the runtime that the documentation does not list, so
#: PAL106 must not fire on them and PAL107 must not suggest a "correct" casing.
#: Each entry needs a reason, because an undocumented name is a liability.
_UNDOCUMENTED_BUT_ACCEPTED: dict[str, str] = {
    # Appears in Microsoft's own flows as a synonym for encodeUriComponent.
    "encodeuricomponent": "documented; listed above",
    # Older designer output; still evaluated.
    "utcnow": "documented; listed above",
}

KNOWN_FUNCTIONS: frozenset[str] = frozenset(CANONICAL) | frozenset(
    _UNDOCUMENTED_BUT_ACCEPTED
)


def canonical_casing(lowered: str) -> str | None:
    """Documented spelling for a lowercase function name, or None if undocumented."""
    return CANONICAL.get(lowered)
