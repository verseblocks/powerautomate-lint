"""Errors raised while lexing and parsing Workflow Definition Language expressions.

Every error carries a character offset into the source expression. Offsets are
the whole point: a linter that says "syntax error" without saying where is not
usable in a pull request, and the SARIF report needs a region.
"""

from __future__ import annotations


class ExpressionError(Exception):
    """Base class for anything wrong with an expression."""


class ExpressionSyntaxError(ExpressionError):
    """The expression could not be lexed or parsed.

    Attributes:
        code: stable machine-readable identifier, e.g. ``unterminated-string``.
              Tests assert on the code, never on the message text, so messages
              stay free to improve.
        offset: 0-based character offset into the expression where the problem
                was detected.
        expression: the full source expression, for context in reports.
    """

    def __init__(self, code: str, message: str, offset: int, expression: str) -> None:
        super().__init__(f"{message} (at offset {offset})")
        self.code = code
        self.message = message
        self.offset = offset
        self.expression = expression

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ExpressionSyntaxError(code={self.code!r}, offset={self.offset}, "
            f"message={self.message!r})"
        )
