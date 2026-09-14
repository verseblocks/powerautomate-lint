"""Recursive-descent parser for Workflow Definition Language expressions.

The grammar, in full:

    expression  := postfix
    postfix     := primary ( '.' IDENT | '?' '.' IDENT | '[' expression ']'
                           | '?' '[' expression ']' )*
    primary     := STRING | NUMBER | 'true' | 'false' | 'null'
                 | IDENT '(' arglist? ')'
                 | IDENT
    arglist     := expression ( ',' expression )*

There are no operators to give precedence to, which is why this is short. Every
comparison, boolean and arithmetic operation in WDL is a function call, so
``add(1, 2)`` rather than ``1 + 2``.

Trailing commas are rejected. The runtime rejects them too, and accepting them
here would mean the linter stays silent on a real syntax error.
"""

from __future__ import annotations

from .ast import FunctionCall, Identifier, Index, Literal, Node, PropertyAccess
from .errors import ExpressionSyntaxError
from .lexer import Token, TokenKind, tokenize

_BARE_LITERALS = {
    "true": (True, "boolean"),
    "false": (False, "boolean"),
    "null": (None, "null"),
}


def parse(expression: str) -> Node:
    """Parse one expression body into an AST.

    The input must not include the leading ``@`` or the ``@{}`` braces; use
    ``template.parse_template`` for a raw JSON string value.
    """
    parser = _Parser(expression, tokenize(expression))
    node = parser.parse_expression()
    parser.expect_eof()
    return node


class _Parser:
    def __init__(self, source: str, tokens: list[Token]) -> None:
        self.source = source
        self.tokens = tokens
        self.pos = 0

    # -- plumbing ---------------------------------------------------------

    def peek(self) -> Token:
        """The token at the cursor.

        A method rather than a property on purpose. As a property, a type
        checker narrows ``self.peek().kind`` inside a branch and then has no
        way to know that ``advance()`` moved the cursor, so a perfectly correct
        follow-up comparison gets reported as a non-overlapping identity check.
        """
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind is not TokenKind.EOF:
            self.pos += 1
        return tok

    def accept(self, kind: TokenKind) -> Token | None:
        if self.peek().kind is kind:
            return self.advance()
        return None

    def expect(self, kind: TokenKind, code: str, what: str) -> Token:
        if self.peek().kind is not kind:
            raise ExpressionSyntaxError(
                code,
                f"expected {what}, found {self._describe(self.peek())}",
                self.peek().offset,
                self.source,
            )
        return self.advance()

    def expect_eof(self) -> None:
        if self.peek().kind is not TokenKind.EOF:
            raise ExpressionSyntaxError(
                "trailing-input",
                f"unexpected {self._describe(self.peek())} after end of expression",
                self.peek().offset,
                self.source,
            )

    @staticmethod
    def _describe(tok: Token) -> str:
        if tok.kind is TokenKind.EOF:
            return "end of expression"
        if tok.kind is TokenKind.STRING:
            return "a string literal"
        if tok.kind is TokenKind.NUMBER:
            return f"number {tok.value}"
        return f"{tok.value!r}"

    # -- grammar ----------------------------------------------------------

    def parse_expression(self) -> Node:
        return self.parse_postfix()

    def parse_postfix(self) -> Node:
        node = self.parse_primary()
        while True:
            if self.peek().kind is TokenKind.DOT:
                dot = self.advance()
                name = self.expect(
                    TokenKind.IDENT, "expected-property", "a property name after '.'"
                )
                node = PropertyAccess(node, name.value, safe=False, offset=dot.offset)
                continue

            if self.peek().kind is TokenKind.QUESTION:
                question = self.advance()
                if self.peek().kind is TokenKind.DOT:
                    self.advance()
                    name = self.expect(
                        TokenKind.IDENT,
                        "expected-property",
                        "a property name after '?.'",
                    )
                    node = PropertyAccess(
                        node, name.value, safe=True, offset=question.offset
                    )
                    continue
                if self.peek().kind is TokenKind.LBRACKET:
                    self.advance()
                    index = self.parse_expression()
                    self.expect(
                        TokenKind.RBRACKET, "unclosed-index", "']' to close the index"
                    )
                    node = Index(node, index, safe=True, offset=question.offset)
                    continue
                raise ExpressionSyntaxError(
                    "dangling-question",
                    "'?' must be followed by '.' or '['",
                    question.offset,
                    self.source,
                )

            if self.peek().kind is TokenKind.LBRACKET:
                bracket = self.advance()
                index = self.parse_expression()
                self.expect(
                    TokenKind.RBRACKET, "unclosed-index", "']' to close the index"
                )
                node = Index(node, index, safe=False, offset=bracket.offset)
                continue

            return node

    def parse_primary(self) -> Node:
        tok = self.peek()

        if tok.kind is TokenKind.STRING:
            self.advance()
            return Literal(tok.value, "string", tok.offset)

        if tok.kind is TokenKind.NUMBER:
            self.advance()
            text = tok.value
            value: object
            if any(c in text for c in ".eE"):
                value = float(text)
            else:
                value = int(text)
            return Literal(value, "number", tok.offset)

        if tok.kind is TokenKind.IDENT:
            lowered = tok.value.lower()
            if lowered in _BARE_LITERALS and self.tokens[self.pos + 1].kind is not TokenKind.LPAREN:
                self.advance()
                value, kind = _BARE_LITERALS[lowered]
                return Literal(value, kind, tok.offset)

            self.advance()
            if self.peek().kind is TokenKind.LPAREN:
                self.advance()
                args: list[Node] = []
                if self.peek().kind is not TokenKind.RPAREN:
                    while True:
                        args.append(self.parse_expression())
                        if self.accept(TokenKind.COMMA):
                            if self.peek().kind is TokenKind.RPAREN:
                                raise ExpressionSyntaxError(
                                    "trailing-comma",
                                    "trailing comma in argument list",
                                    self.peek().offset,
                                    self.source,
                                )
                            continue
                        break
                closing = self.expect(
                    TokenKind.RPAREN,
                    "unclosed-call",
                    f"')' to close the call to {tok.value}",
                )
                return FunctionCall(
                    tok.value, tuple(args), tok.offset, closing.offset
                )
            return Identifier(tok.value, tok.offset)

        if tok.kind is TokenKind.EOF:
            raise ExpressionSyntaxError(
                "empty-expression",
                "expression is empty",
                tok.offset,
                self.source,
            )

        raise ExpressionSyntaxError(
            "unexpected-token",
            f"unexpected {self._describe(tok)}",
            tok.offset,
            self.source,
        )
