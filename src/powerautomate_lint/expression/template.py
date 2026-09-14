"""Splits a flow's JSON string value into literal text and expressions.

This is the layer above the expression grammar, and it is where most naive
implementations go wrong. The rules, as the runtime actually behaves:

WHOLE-STRING FORM.
    A value whose first character is ``@`` and which is not escaped is a single
    expression covering the entire string. ``"@outputs('x')"`` is an expression.
    The value's type is whatever the expression returns, so this form is how a
    flow passes a non-string.

INTERPOLATED FORM.
    ``@{...}`` anywhere in a string embeds an expression whose result is
    stringified and spliced in. A value may contain several, mixed with text:
    ``"Hi @{variables('n')}, you have @{variables('c')} items"``.

ESCAPING.
    A literal at-sign at the start of a string is written ``@@``. So ``"@@x"``
    is the text ``@x`` and not an expression. Inside the string, ``@@{`` escapes
    a literal ``@{``. A lone ``@`` in the middle of a string is just text, which
    is why an email address in a subject line is not a syntax error.

BRACE MATCHING.
    The closing brace of an interpolation cannot be found by scanning for the
    next ``}``: expression bodies contain string literals that may themselves
    contain braces, as in ``@{concat('{', variables('x'), '}')}``. Depth
    counting has to skip over single-quoted literals, honouring the ``''``
    doubling rule.
"""

from __future__ import annotations

from .ast import Interpolation, Template
from .errors import ExpressionSyntaxError
from .parser import parse


def parse_template(value: str) -> Template:
    """Decompose a JSON string value into literal parts and interpolations.

    Raises ExpressionSyntaxError if an embedded expression is malformed or an
    interpolation is unterminated. Offsets on the returned Interpolation nodes
    are relative to ``value``.
    """
    if not isinstance(value, str) or not value:
        return Template((value,) if value else ())

    # Whole-string form. Checked before interpolation scanning because a value
    # like "@concat('a','b')" has no braces at all.
    if value.startswith("@@"):
        # Escaped: the whole value is literal text with one @ removed.
        return Template((value[1:],))

    if value.startswith("@") and not value.startswith("@{"):
        body = value[1:]
        node = parse(body)
        return Template((Interpolation(node, 0, body),))

    parts: list[str | Interpolation] = []
    buf: list[str] = []
    i = 0
    n = len(value)

    while i < n:
        ch = value[i]

        if ch == "@":
            # Escaped literal "@{" written as "@@{".
            if value.startswith("@@{", i):
                buf.append("@{")
                i += 3
                continue
            if value.startswith("@{", i):
                start = i
                body, end = _scan_interpolation(value, i + 2)
                if buf:
                    parts.append("".join(buf))
                    buf = []
                node = parse(body)
                parts.append(Interpolation(node, start, body))
                i = end
                continue
        buf.append(ch)
        i += 1

    if buf:
        parts.append("".join(buf))

    return Template(tuple(parts))


def _scan_interpolation(value: str, start: int) -> tuple[str, int]:
    """Find the end of an ``@{`` interpolation that begins at ``start``.

    ``start`` is the offset just past the ``{``. Returns the body text and the
    offset just past the matching ``}``.
    """
    depth = 1
    i = start
    n = len(value)

    while i < n:
        ch = value[i]

        if ch == "'":
            # Skip a single-quoted literal wholesale, honouring '' doubling, so
            # that braces inside string literals do not affect depth.
            i += 1
            while i < n:
                if value[i] == "'":
                    if i + 1 < n and value[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            else:
                raise ExpressionSyntaxError(
                    "unterminated-string",
                    "string literal is not closed inside the interpolation",
                    start - 2,
                    value,
                )
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return value[start:i], i + 1
        i += 1

    raise ExpressionSyntaxError(
        "unterminated-interpolation",
        "'@{' is never closed",
        start - 2,
        value,
    )


def iter_expressions(value: str) -> list[Interpolation]:
    """Convenience wrapper returning just the interpolations of a value.

    Returns an empty list for a value with no expressions, so callers can walk
    every string in a flow definition without branching.
    """
    return list(parse_template(value).interpolations)
