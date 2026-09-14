"""Tokeniser for the Workflow Definition Language expression grammar.

The grammar itself is small. What makes a hand-written lexer necessary is a
handful of behaviours that Microsoft's documentation does not describe, and that
Microsoft's own shipping flows depend on:

U+00A0 IS WHITESPACE.
    Three expressions in the Center of Excellence Starter Kit separate function
    arguments with a no-break space instead of U+0020, for example
    ``concat('a', outputs('x'), 'b')`` in
    AdminSyncTemplatev3CoESolutionMetadata. Those flows run in production. A
    lexer that only skips ASCII space and tab rejects expressions the runtime
    accepts, so the whitespace set has to include the Unicode separators. This
    is asserted directly in the test suite against the vendored corpus.

STRING LITERALS DOUBLE THEIR QUOTES.
    Single-quoted only, and an embedded quote is written ``''``. There is no
    backslash escape; ``'it\\'s'`` is not valid and ``'it''s'`` is.

@ AND @@ LIVE OUTSIDE THE EXPRESSION GRAMMAR.
    Those belong to the *template* layer that wraps expressions in a flow's JSON
    string values, not to the expression itself. See ``template.py``. This lexer
    is handed the inside of an expression and nothing else, which keeps it
    reusable for any caller that already knows where its expression starts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .errors import ExpressionSyntaxError

# ASCII whitespace plus the Unicode separators that reach expressions by the
# copy-paste-from-a-browser route. U+00A0 is the load-bearing one: it appears
# in three expressions in Microsoft's own CoE Starter Kit and those flows run
# in production. Written as code points so the set is readable and so no
# editor or pipeline can silently normalise an invisible character away.
_WHITESPACE_CODEPOINTS = (
    0x0009,  # tab
    0x000A,  # line feed
    0x000B,  # vertical tab
    0x000C,  # form feed
    0x000D,  # carriage return
    0x0020,  # space
    0x00A0,  # NO-BREAK SPACE -- required by real flows, see module docstring
    0x1680,  # ogham space mark
    0x2028,  # line separator
    0x2029,  # paragraph separator
    0x202F,  # narrow no-break space
    0x205F,  # medium mathematical space
    0x3000,  # ideographic space
    0xFEFF,  # zero-width no-break space / BOM
    *range(0x2000, 0x200B),  # en quad through hair space
)

WHITESPACE = frozenset(chr(c) for c in _WHITESPACE_CODEPOINTS)


class TokenKind(Enum):
    IDENT = auto()
    STRING = auto()
    NUMBER = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    COMMA = auto()
    DOT = auto()
    QUESTION = auto()
    EOF = auto()


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    #: For STRING this is the decoded value with ``''`` collapsed to ``'``.
    #: For NUMBER it is the literal text, so the parser decides int vs float.
    value: str
    #: 0-based offset of the token's first character.
    offset: int

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.kind.name}({self.value!r})@{self.offset}"


_SINGLE_CHAR = {
    "(": TokenKind.LPAREN,
    ")": TokenKind.RPAREN,
    "[": TokenKind.LBRACKET,
    "]": TokenKind.RBRACKET,
    ",": TokenKind.COMMA,
    ".": TokenKind.DOT,
    "?": TokenKind.QUESTION,
}

# Identifiers in WDL are function names and property segments. Property segments
# reached through dot access can contain hyphens (``body/value-1``), and locale
# identifiers like ``en-US`` appear as bare segments, so hyphen is included.
_IDENT_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$")
_IDENT_CONT = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$0123456789-"
)


def tokenize(expression: str) -> list[Token]:
    """Tokenise one expression body.

    The input is the expression *without* its leading ``@`` and without the
    ``@{...}`` interpolation braces. Raises ExpressionSyntaxError with an offset.
    """
    tokens: list[Token] = []
    i = 0
    n = len(expression)

    while i < n:
        ch = expression[i]

        if ch in WHITESPACE:
            i += 1
            continue

        if ch in _SINGLE_CHAR:
            tokens.append(Token(_SINGLE_CHAR[ch], ch, i))
            i += 1
            continue

        if ch == "'":
            start = i
            i += 1
            chars: list[str] = []
            while True:
                if i >= n:
                    raise ExpressionSyntaxError(
                        "unterminated-string",
                        "string literal is not closed",
                        start,
                        expression,
                    )
                if expression[i] == "'":
                    # A doubled quote is a literal quote; a single one ends it.
                    if i + 1 < n and expression[i + 1] == "'":
                        chars.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                chars.append(expression[i])
                i += 1
            tokens.append(Token(TokenKind.STRING, "".join(chars), start))
            continue

        if ch.isdigit() or (
            ch == "-"
            and i + 1 < n
            and expression[i + 1].isdigit()
            and _is_numeric_position(tokens)
        ):
            start = i
            if ch == "-":
                i += 1
            seen_dot = False
            seen_exp = False
            while i < n:
                c = expression[i]
                if c.isdigit():
                    i += 1
                elif c == "." and not seen_dot and not seen_exp:
                    # Only a decimal point if a digit follows; otherwise this is
                    # property access on a number, which is not valid anyway but
                    # should fail at the parser with a clearer error.
                    if i + 1 < n and expression[i + 1].isdigit():
                        seen_dot = True
                        i += 1
                    else:
                        break
                elif c in "eE" and not seen_exp:
                    nxt = i + 1
                    if nxt < n and expression[nxt] in "+-":
                        nxt += 1
                    if nxt < n and expression[nxt].isdigit():
                        seen_exp = True
                        i = nxt + 1
                    else:
                        break
                else:
                    break
            tokens.append(Token(TokenKind.NUMBER, expression[start:i], start))
            continue

        if ch in _IDENT_START:
            start = i
            i += 1
            while i < n and expression[i] in _IDENT_CONT:
                i += 1
            tokens.append(Token(TokenKind.IDENT, expression[start:i], start))
            continue

        raise ExpressionSyntaxError(
            "unexpected-character",
            f"unexpected character {ch!r}",
            i,
            expression,
        )

    tokens.append(Token(TokenKind.EOF, "", n))
    return tokens


def _is_numeric_position(tokens: list[Token]) -> bool:
    """Decide whether a ``-`` starts a negative number rather than being stray.

    WDL has no infix arithmetic operators, so a ``-`` can only legitimately open
    a negative literal, and only where a value is expected: at the start, or
    directly after ``(`` or ``,``.
    """
    if not tokens:
        return True
    return tokens[-1].kind in (TokenKind.LPAREN, TokenKind.COMMA)
