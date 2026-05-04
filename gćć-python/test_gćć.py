import os

import pytest

import lexer
import morph_anal
import parser as parser_mod

SGJP_PATH = os.path.join(os.path.dirname(__file__), "..", "sgjp.tab")


@pytest.fixture(scope="session")
def db():
    return morph_anal.load(SGJP_PATH)


@pytest.fixture(scope="session")
def parse(db):
    def _parse(text):
        return parser_mod.parse(morph_anal.analyze(lexer.lex(text), db))
    return _parse


# ---------- Lexer ----------

def test_lex_skips_comments():
    toks = lexer.lex("# komentarz\nx to 1\n")
    word_values = [t[1] for t in toks if t[0] is lexer.Token.WORD]
    assert word_values == [("x",)]


def test_lex_emits_indent_and_dedent_on_eof():
    toks = lexer.lex("aby f:\n    x to 1\n")
    kinds = [t[0] for t in toks]
    assert lexer.Token.INDENT in kinds
    # DEDENT auto-flushed at EOF (otherwise parser can't close func body)
    assert kinds[-1] is lexer.Token.DEDENT


def test_lex_string_literal_preserves_internal_spaces():
    toks = lexer.lex('x to "ala ma kota"\n')
    text_values = [t[1] for t in toks if t[0] is lexer.Token.TEXT]
    assert text_values == ["ala ma kota"]


def test_lex_colon_split_from_preceding_word():
    toks = lexer.lex("klienta:\n")
    kinds = [t[0] for t in toks]
    # WORD then COLON, not 'klienta:' as single word
    assert kinds[0] is lexer.Token.WORD
    assert kinds[1] is lexer.Token.COLON


def test_lex_negative_number_is_two_tokens():
    toks = lexer.lex("x to -1\n")
    sigs = [(t[0], t[1]) for t in toks]
    # liczby zawsze nieujemne, minus jako BIN_OP
    assert (lexer.Token.BIN_OP, "-") in sigs
    assert (lexer.Token.NUMBER, 1) in sigs


def test_lex_to_becomes_assign_token():
    toks = lexer.lex("x to 5\n")
    assert any(t[0] is lexer.Token.ASSIGN for t in toks)


def test_lex_underscore_splits_word_into_segment_tuple():
    toks = lexer.lex("zapisz_w_bazie\n")
    word_toks = [t for t in toks if t[0] is lexer.Token.WORD]
    assert word_toks == [(lexer.Token.WORD, ("zapisz", "w", "bazie"))]


def test_lex_single_word_is_one_element_tuple():
    toks = lexer.lex("aby\n")
    word_toks = [t for t in toks if t[0] is lexer.Token.WORD]
    assert word_toks == [(lexer.Token.WORD, ("aby",))]


def test_lex_recognizes_parens():
    toks = lexer.lex("(1 + 2)\n")
    kinds = [t[0] for t in toks]
    assert lexer.Token.LPAREN in kinds
    assert lexer.Token.RPAREN in kinds


def test_lex_comparison_operators():
    toks = lexer.lex("a < b > c <= d >= e != f = g\n")
    op_values = [t[1] for t in toks if t[0] is lexer.Token.BIN_OP]
    assert op_values == ["<", ">", "<=", ">=", "!=", "="]


def test_lex_multichar_operators_are_greedy():
    # <= musi być jednym tokenem, nie < + =
    toks = lexer.lex("a <= b\n")
    op_values = [t[1] for t in toks if t[0] is lexer.Token.BIN_OP]
    assert op_values == ["<="]


def test_lex_to_inside_underscore_identifier_stays_word():
    # Standalone "to" → ASSIGN, but "to_zrobic" jako identyfikator dalej WORD
    toks = lexer.lex("to_zrobic\n")
    word_toks = [t for t in toks if t[0] is lexer.Token.WORD]
    assert word_toks == [(lexer.Token.WORD, ("to", "zrobic"))]
    assert not any(t[0] is lexer.Token.ASSIGN for t in toks)


# ---------- morph_anal.canonical ----------

def _canonical_of(text, db):
    morphs = morph_anal.analyze(lexer.lex(text), db)
    word = next(m for m in morphs if m[0] is lexer.Token.WORD)
    return morph_anal.canonical(word)


def test_canonical_prefers_lemma_equal_form(db):
    # 'rzecz' ma 4 analizy: 2× impt 'rzec' (verb), 2× subst 'rzecz' (noun).
    # Heurystyka lemma==forma wybiera rzeczownik.
    assert _canonical_of("rzecz\n", db) == ("rzecz",)


def test_canonical_falls_back_to_first_analysis_when_no_lemma_matches_form(db):
    # 'klienta' to gen.acc rzeczownika 'klient'; żadna analiza nie ma lemmy 'klienta'
    assert _canonical_of("klienta\n", db) == ("klient",)


def test_canonical_unknown_segment_uses_segment_as_lemma(db):
    # 'fibonacci' nie istnieje w sgjp — fallback na samo słowo
    assert _canonical_of("fibonacci\n", db) == ("fibonacci",)


def test_canonical_does_not_lemmatize_single_letters(db):
    # 'n' miało analizy 'brev' z lemmą 'nad' — pojedyncze litery zostawiamy bez zmian
    assert _canonical_of("n\n", db) == ("n",)
    assert _canonical_of("a\n", db) == ("a",)


def test_canonical_multi_segment_identifier(db):
    # zapisz_w_bazie -> zapisać + w + baza
    assert _canonical_of("zapisz_w_bazie\n", db) == ("zapisać", "w", "baza")


def test_canonical_inflected_noun_in_underscore_id(db):
    # inna_rzecz: 'inna' (adj sg.f.nom) -> 'inny'; 'rzecz' (subst) -> 'rzecz'
    assert _canonical_of("inna_rzecz\n", db) == ("inny", "rzecz")


# ---------- Parser ----------

def test_parse_function_def_with_assignment(parse):
    ast = parse("aby działać:\n    liczba to 5\n")
    assert isinstance(ast, parser_mod.Module)
    fd = ast.body[0]
    assert isinstance(fd, parser_mod.FunctionDef)
    assert fd.name == ("działać",)
    a = fd.body[0]
    assert isinstance(a, parser_mod.Assignment)
    assert a.target == ("liczba",)
    assert a.value == parser_mod.IntLit(5)


def test_parse_assignment_string_literal(parse):
    ast = parse('aby f:\n    x to "siemka"\n')
    a = ast.body[0].body[0]
    assert a.value == parser_mod.StrLit("siemka")


def test_parse_assignment_var_with_canonical_name(parse):
    ast = parse("aby f:\n    x to inna_rzecz\n")
    a = ast.body[0].body[0]
    assert isinstance(a.value, parser_mod.Var)
    assert a.value.name == ("inny", "rzecz")


def test_parse_binop_precedence_mul_over_add(parse):
    # 2 + 3 * 5 -> BinOp(+, 2, BinOp(*, 3, 5))
    ast = parse("aby f:\n    x to 2 + 3 * 5\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == "+"
    assert expr.left == parser_mod.IntLit(2)
    assert isinstance(expr.right, parser_mod.BinOp) and expr.right.op == "*"
    assert expr.right.left == parser_mod.IntLit(3)
    assert expr.right.right == parser_mod.IntLit(5)


def test_parse_left_associativity_of_subtraction(parse):
    # 10 - 3 - 2 -> ((10 - 3) - 2), evaluates to 5
    ast = parse("aby f:\n    x to 10 - 3 - 2\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == "-"
    assert expr.right == parser_mod.IntLit(2)
    assert isinstance(expr.left, parser_mod.BinOp) and expr.left.op == "-"
    assert expr.left.left == parser_mod.IntLit(10)
    assert expr.left.right == parser_mod.IntLit(3)


def test_parse_parens_override_precedence(parse):
    # (2 + 3) * 4 -> BinOp(*, BinOp(+, 2, 3), 4)
    ast = parse("aby f:\n    x to (2 + 3) * 4\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == "*"
    assert isinstance(expr.left, parser_mod.BinOp) and expr.left.op == "+"
    assert expr.right == parser_mod.IntLit(4)


def test_parse_unary_minus(parse):
    ast = parse("aby f:\n    x to -5\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.UnaryOp)
    assert expr.op == "-"
    assert expr.operand == parser_mod.IntLit(5)


def test_parse_multiple_function_definitions(parse):
    ast = parse("aby f:\n    x to 1\n\naby g:\n    y to 2\n")
    assert len(ast.body) == 2
    # Pojedyncze litery nie są lematyzowane
    assert ast.body[0].name == ("f",)
    assert ast.body[1].name == ("g",)


def test_parse_division(parse):
    ast = parse("aby f:\n    x to 19 / 6\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == "/"


def test_parse_modulo(parse):
    ast = parse("aby f:\n    x to 19 % 6\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == "%"


def test_parse_modulo_same_precedence_as_mul(parse):
    # 1 + 19 % 6 -> BinOp(+, 1, BinOp(%, 19, 6))
    ast = parse("aby f:\n    x to 1 + 19 % 6\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == "+"
    assert isinstance(expr.right, parser_mod.BinOp) and expr.right.op == "%"


def test_parse_comparison(parse):
    ast = parse("aby f:\n    x to a < b\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == "<"


@pytest.mark.parametrize("op", ["<", ">", "<=", ">=", "!=", "="])
def test_parse_all_comparison_operators(parse, op):
    ast = parse(f"aby f:\n    x to a {op} b\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == op


def test_parse_comparison_lower_precedence_than_arith(parse):
    # 1 + 2 < 3 + 4 -> BinOp(<, BinOp(+, 1, 2), BinOp(+, 3, 4))
    ast = parse("aby f:\n    x to 1 + 2 < 3 + 4\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp) and expr.op == "<"
    assert isinstance(expr.left, parser_mod.BinOp) and expr.left.op == "+"
    assert isinstance(expr.right, parser_mod.BinOp) and expr.right.op == "+"


def test_parse_equality_is_comparison_not_assignment(parse):
    # `a = b` w wyrażeniu to porównanie; przypisanie jest tylko przez `to`.
    ast = parse("aby f:\n    x to a = b\n")
    a = ast.body[0].body[0]
    assert isinstance(a, parser_mod.Assignment)  # x to ...
    assert a.target == ("x",)
    assert isinstance(a.value, parser_mod.BinOp) and a.value.op == "="


def test_parse_if_no_else(parse):
    src = "aby f:\n    jeśli a < b:\n        x to 1\n"
    ast = parse(src)
    if_node = ast.body[0].body[0]
    assert isinstance(if_node, parser_mod.If)
    assert isinstance(if_node.cond, parser_mod.BinOp) and if_node.cond.op == "<"
    assert len(if_node.then_body) == 1
    assert if_node.else_body == []


def test_parse_if_else(parse):
    src = "aby f:\n    jeśli a < b:\n        x to 1\n    inaczej:\n        x to 2\n"
    ast = parse(src)
    if_node = ast.body[0].body[0]
    assert isinstance(if_node, parser_mod.If)
    assert len(if_node.then_body) == 1
    assert len(if_node.else_body) == 1
    assert if_node.then_body[0].value == parser_mod.IntLit(1)
    assert if_node.else_body[0].value == parser_mod.IntLit(2)


def test_parse_if_with_equality_condition(parse):
    # `=` w condition to porównanie (nie przypisanie)
    src = "aby f:\n    jeśli a = 5:\n        x to 1\n"
    ast = parse(src)
    if_node = ast.body[0].body[0]
    assert isinstance(if_node.cond, parser_mod.BinOp) and if_node.cond.op == "="


def test_parse_nested_if(parse):
    src = (
        "aby f:\n"
        "    jeśli a < b:\n"
        "        jeśli c > d:\n"
        "            x to 1\n"
        "        inaczej:\n"
        "            x to 2\n"
    )
    ast = parse(src)
    outer = ast.body[0].body[0]
    assert isinstance(outer, parser_mod.If)
    inner = outer.then_body[0]
    assert isinstance(inner, parser_mod.If)
    assert len(inner.else_body) == 1


def test_parse_while(parse):
    src = "aby f:\n    dopóki a < 10:\n        a to a + 1\n"
    ast = parse(src)
    w = ast.body[0].body[0]
    assert isinstance(w, parser_mod.While)
    assert isinstance(w.cond, parser_mod.BinOp) and w.cond.op == "<"
    assert len(w.body) == 1


def test_parse_while_with_if_inside(parse):
    src = (
        "aby f:\n"
        "    dopóki a < 10:\n"
        "        jeśli a = 5:\n"
        "            x to 1\n"
        "        a to a + 1\n"
    )
    ast = parse(src)
    w = ast.body[0].body[0]
    assert isinstance(w, parser_mod.While)
    assert isinstance(w.body[0], parser_mod.If)
    assert isinstance(w.body[1], parser_mod.Assignment)


def test_parse_else_if_chain(parse):
    src = (
        "aby f:\n"
        "    jeśli x < 1:\n"
        "        a to 1\n"
        "    inaczej jeśli x < 2:\n"
        "        a to 2\n"
        "    inaczej jeśli x < 3:\n"
        "        a to 3\n"
        "    inaczej:\n"
        "        a to 4\n"
    )
    ast = parse(src)
    if1 = ast.body[0].body[0]
    assert isinstance(if1, parser_mod.If)
    # else_body zawiera pojedyncze If — kolejny szczebel łańcucha
    assert len(if1.else_body) == 1
    if2 = if1.else_body[0]
    assert isinstance(if2, parser_mod.If)
    if3 = if2.else_body[0]
    assert isinstance(if3, parser_mod.If)
    # Ostatnie ogniwo ma "płaskie" else_body (czyste statementy, nie If)
    assert len(if3.else_body) == 1
    assert isinstance(if3.else_body[0], parser_mod.Assignment)


def test_parse_else_if_without_final_else(parse):
    src = (
        "aby f:\n"
        "    jeśli x < 1:\n"
        "        a to 1\n"
        "    inaczej jeśli x < 2:\n"
        "        a to 2\n"
    )
    ast = parse(src)
    if1 = ast.body[0].body[0]
    if2 = if1.else_body[0]
    assert isinstance(if2, parser_mod.If)
    assert if2.else_body == []


def test_parse_break_inside_while(parse):
    src = (
        "aby f:\n"
        "    dopóki a < 10:\n"
        "        jeśli a = 5:\n"
        "            stop\n"
        "        a to a + 1\n"
    )
    ast = parse(src)
    w = ast.body[0].body[0]
    assert isinstance(w, parser_mod.While)
    if_node = w.body[0]
    assert isinstance(if_node, parser_mod.If)
    assert isinstance(if_node.then_body[0], parser_mod.Break)


def test_parse_break_standalone(parse):
    # Parser nie sprawdza, że stop musi być wewnątrz pętli — to robota semantyki.
    src = "aby f:\n    stop\n"
    ast = parse(src)
    assert isinstance(ast.body[0].body[0], parser_mod.Break)


def test_parse_nested_parens(parse):
    # (1 + 2) * (3 + 4)
    ast = parse("aby f:\n    x to (1 + 2) * (3 + 4)\n")
    expr = ast.body[0].body[0].value
    assert expr.op == "*"
    assert expr.left.op == "+" and expr.right.op == "+"
