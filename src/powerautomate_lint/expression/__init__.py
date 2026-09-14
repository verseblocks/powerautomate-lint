"""Offline parser for the Power Automate / Logic Apps expression language.

Zero dependencies, no network, no credentials. This subpackage is the stable
public surface and is safe to import on its own:

    from powerautomate_lint.expression import parse, parse_template

``parse`` takes an expression body. ``parse_template`` takes a raw JSON string
value from a flow definition and tells you which parts of it are expressions.
"""

from .ast import (
    FunctionCall,
    Identifier,
    Index,
    Interpolation,
    Literal,
    Node,
    PropertyAccess,
    Template,
)
from .errors import ExpressionError, ExpressionSyntaxError
from .lexer import WHITESPACE, Token, TokenKind, tokenize
from .parser import parse
from .template import iter_expressions, parse_template

__all__ = [
    "ExpressionError",
    "ExpressionSyntaxError",
    "FunctionCall",
    "Identifier",
    "Index",
    "Interpolation",
    "Literal",
    "Node",
    "PropertyAccess",
    "Template",
    "Token",
    "TokenKind",
    "WHITESPACE",
    "iter_expressions",
    "parse",
    "parse_template",
    "tokenize",
]
