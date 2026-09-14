"""AST node types for Workflow Definition Language expressions.

Deliberately small. WDL has no operators, no statements and no control flow: an
expression is a literal, a function call, or a chain of property and index
accesses over one of those. Everything conditional is a function, so ``if()``
and ``and()`` are ordinary FunctionCall nodes rather than special forms.

Every node carries the offset of its first character so a finding can point at
the exact spot inside an expression, which is what the SARIF region needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Literal:
    """A string, number, boolean or null literal.

    ``kind`` is one of ``string``, ``number``, ``boolean``, ``null``. Booleans
    and null arrive as bare identifiers from the lexer and are promoted here,
    because WDL spells them ``true``, ``false`` and ``null`` with no keyword
    status of their own.
    """

    value: object
    kind: str
    offset: int


@dataclass(frozen=True)
class FunctionCall:
    name: str
    args: tuple[Node, ...]
    offset: int
    #: Offset of the closing parenthesis, used to report a whole-call region.
    end_offset: int = 0


@dataclass(frozen=True)
class PropertyAccess:
    """``target.name``, or ``target?.name`` when ``safe`` is set."""

    target: Node
    name: str
    safe: bool
    offset: int


@dataclass(frozen=True)
class Index:
    """``target['key']`` or ``target[0]``, or ``target?['key']`` when safe.

    The safe form is overwhelmingly the common one in real flows, because
    ``outputs('x')?['body/value']`` is what the designer generates.
    """

    target: Node
    index: Node
    safe: bool
    offset: int


@dataclass(frozen=True)
class Identifier:
    """A bare identifier used as a value.

    Valid WDL has very few of these. It appears as the root of a property chain
    in some hand-written expressions, so the parser accepts it rather than
    rejecting expressions the runtime tolerates.
    """

    name: str
    offset: int


#: Any expression node. Written as a runtime union rather than typing.Union
#: because the package targets Python 3.10 and above.
Node = Literal | FunctionCall | PropertyAccess | Index | Identifier


@dataclass(frozen=True)
class Interpolation:
    """One ``@{...}`` hole inside a template string."""

    node: Node
    #: Offset of the ``@`` in the *original* JSON string value.
    offset: int
    #: The raw source text of the expression body, for reporting.
    source: str


@dataclass(frozen=True)
class Template:
    """A JSON string value decomposed into literal text and interpolations.

    A value that is a single whole-string expression (``"@concat('a','b')"``)
    produces one Interpolation and no literal parts. A value that mixes text and
    holes (``"Hello @{variables('name')}"``) produces both. A value with no
    expression at all produces a single literal part, which callers skip.
    """

    parts: tuple[str | Interpolation, ...] = field(default_factory=tuple)

    @property
    def interpolations(self) -> tuple[Interpolation, ...]:
        return tuple(p for p in self.parts if isinstance(p, Interpolation))

    @property
    def has_expression(self) -> bool:
        return any(isinstance(p, Interpolation) for p in self.parts)
