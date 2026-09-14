"""Lexer, parser and template tests.

These are pure functions over strings, so they assert real behaviour rather than
"it did not crash". Every malformed case asserts on the error *code* and the
*offset*, never on the message text, so messages stay free to improve.
"""

from __future__ import annotations

import pytest

from powerautomate_lint.expression import (
    WHITESPACE,
    ExpressionSyntaxError,
    FunctionCall,
    Identifier,
    Index,
    Literal,
    PropertyAccess,
    parse,
    parse_template,
    tokenize,
)

NBSP = " "


# --------------------------------------------------------------------------
# Whitespace, including the behaviour Microsoft does not document
# --------------------------------------------------------------------------


def test_nbsp_is_whitespace():
    """U+00A0 must be whitespace or three real CoE flows fail to parse.

    See tests/test_corpus.py for the assertion against the actual flows.
    """
    assert NBSP in WHITESPACE


def test_nbsp_separates_arguments():
    node = parse(f"concat('a',{NBSP}outputs('x'),{NBSP}'b')")
    assert isinstance(node, FunctionCall)
    assert node.name == "concat"
    assert len(node.args) == 3


@pytest.mark.parametrize("code", [0x20, 0x09, 0x0A, 0x0D, 0xA0, 0x2007, 0x3000, 0xFEFF])
def test_whitespace_variants_are_skipped(code):
    node = parse(f"concat({chr(code)}'a',{chr(code)}'b'{chr(code)})")
    assert isinstance(node, FunctionCall)
    assert len(node.args) == 2


# --------------------------------------------------------------------------
# String literals
# --------------------------------------------------------------------------


def test_doubled_quote_is_a_literal_quote():
    node = parse("'it''s'")
    assert isinstance(node, Literal)
    assert node.value == "it's"


def test_empty_string_literal():
    node = parse("''")
    assert isinstance(node, Literal)
    assert node.value == ""


def test_backslash_is_not_an_escape():
    # A backslash is an ordinary character; the quote after it still closes.
    node = parse("'a\\'")
    assert isinstance(node, Literal)
    assert node.value == "a\\"


def test_unterminated_string_reports_its_start():
    with pytest.raises(ExpressionSyntaxError) as exc:
        parse("concat('abc)")
    assert exc.value.code == "unterminated-string"
    assert exc.value.offset == 7


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src,expected",
    [("1", 1), ("0", 0), ("42", 42), ("1.5", 1.5), ("1e3", 1000.0), ("2.5e-2", 0.025)],
)
def test_number_literals(src, expected):
    node = parse(src)
    assert isinstance(node, Literal)
    assert node.value == expected


def test_negative_number_only_where_a_value_is_expected():
    node = parse("add(-1,-2)")
    assert isinstance(node, FunctionCall)
    assert [a.value for a in node.args] == [-1, -2]


# --------------------------------------------------------------------------
# Calls, property access, indexing
# --------------------------------------------------------------------------


def test_zero_argument_call():
    node = parse("utcNow()")
    assert isinstance(node, FunctionCall)
    assert node.args == ()


def test_safe_index_is_the_common_designer_shape():
    node = parse("outputs('Get_a_row')?['body/name']")
    assert isinstance(node, Index)
    assert node.safe is True
    assert isinstance(node.index, Literal)
    assert node.index.value == "body/name"
    assert isinstance(node.target, FunctionCall)


def test_chained_access():
    node = parse("workflow()?['tags']?['flowDisplayName']")
    assert isinstance(node, Index)
    assert isinstance(node.target, Index)


def test_property_access_with_hyphen():
    node = parse("body('x').en-US")
    assert isinstance(node, PropertyAccess)
    assert node.name == "en-US"


def test_bare_identifier_is_accepted():
    node = parse("someIdent")
    assert isinstance(node, Identifier)


@pytest.mark.parametrize("literal,value", [("true", True), ("false", False), ("null", None)])
def test_bare_literals(literal, value):
    node = parse(literal)
    assert isinstance(node, Literal)
    assert node.value is value


def test_if_is_an_ordinary_function_not_a_keyword():
    node = parse("if(equals(1,1),'y','n')")
    assert isinstance(node, FunctionCall)
    assert node.name == "if"


# --------------------------------------------------------------------------
# Syntax errors: code and offset both asserted
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src,code,offset",
    [
        ("concat('a',)", "trailing-comma", 11),
        ("concat('a'", "unclosed-call", 10),
        ("outputs('x')?", "dangling-question", 12),
        ("outputs('x')['a'", "unclosed-index", 16),
        ("", "empty-expression", 0),
        ("concat('a') extra", "trailing-input", 12),
        ("body('x').", "expected-property", 10),
        ("#", "unexpected-character", 0),
        (",", "unexpected-token", 0),
    ],
)
def test_syntax_errors(src, code, offset):
    with pytest.raises(ExpressionSyntaxError) as exc:
        parse(src)
    assert exc.value.code == code
    assert exc.value.offset == offset


# --------------------------------------------------------------------------
# Template layer: @, @@, @{...}
# --------------------------------------------------------------------------


def test_whole_string_expression():
    tpl = parse_template("@outputs('x')")
    assert len(tpl.interpolations) == 1
    assert tpl.interpolations[0].source == "outputs('x')"


def test_doubled_at_is_an_escaped_literal():
    tpl = parse_template("@@notAnExpression")
    assert tpl.has_expression is False
    assert tpl.parts == ("@notAnExpression",)


def test_escaped_interpolation_brace():
    tpl = parse_template("literal @@{not an expression}")
    assert tpl.has_expression is False
    assert "@{not an expression}" in "".join(p for p in tpl.parts if isinstance(p, str))


def test_mixed_text_and_interpolations():
    tpl = parse_template("Hi @{variables('n')}, you have @{variables('c')} items")
    assert len(tpl.interpolations) == 2
    assert tpl.interpolations[0].source == "variables('n')"
    assert tpl.interpolations[1].source == "variables('c')"


def test_brace_inside_a_string_literal_does_not_close_the_interpolation():
    tpl = parse_template("@{concat('{', variables('x'), '}')}")
    assert len(tpl.interpolations) == 1
    node = tpl.interpolations[0].node
    assert isinstance(node, FunctionCall)
    assert len(node.args) == 3


def test_nested_braces_are_depth_counted():
    tpl = parse_template("@{json('{\"a\":1}')}")
    assert len(tpl.interpolations) == 1


def test_lone_at_mid_string_is_plain_text():
    tpl = parse_template("mail to someone@example.com please")
    assert tpl.has_expression is False


def test_unterminated_interpolation():
    with pytest.raises(ExpressionSyntaxError) as exc:
        parse_template("@{concat('a'")
    assert exc.value.code == "unterminated-interpolation"


def test_plain_string_has_no_expressions():
    assert parse_template("just text").has_expression is False


def test_interpolation_offset_is_relative_to_the_value():
    tpl = parse_template("abc @{utcNow()}")
    assert tpl.interpolations[0].offset == 4


def test_tokenize_reports_eof():
    tokens = tokenize("utcNow()")
    assert tokens[-1].kind.name == "EOF"
    assert tokens[-1].offset == 8
