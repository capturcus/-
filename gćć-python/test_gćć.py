import os

import pytest

import lexer
import morph_anal
import parser as parser_mod

SGJP_PATH = os.path.join(os.path.dirname(__file__), "..", "sgjp.tab")


@pytest.fixture(scope="session")
def loaded():
    return morph_anal.load(SGJP_PATH)


@pytest.fixture(scope="session")
def db(loaded):
    return loaded[0]


@pytest.fixture(scope="session")
def preps(loaded):
    return loaded[1]


@pytest.fixture(scope="session")
def parse(db, preps):
    def _parse(text):
        return parser_mod.parse(morph_anal.analyze(lexer.lex(text), db), preps)
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


def test_lex_emits_newline_after_each_content_line():
    toks = lexer.lex("aby f:\n    x to 1\n")
    # NEWLINE po `aby f:` i po `x to 1`
    newlines = [t for t in toks if t[0] is lexer.Token.NEWLINE]
    assert len(newlines) == 2


def test_lex_no_newline_for_empty_or_comment_lines():
    toks = lexer.lex("# komentarz\n\nx to 1\n")
    # Tylko jedna NEWLINE — z linii zawierającej `x to 1`
    newlines = [t for t in toks if t[0] is lexer.Token.NEWLINE]
    assert len(newlines) == 1


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
    # Single WORD bez argumentów to Phrase(args=[]) — nie ma osobnego Var
    ast = parse("aby f:\n    x to inna_rzecz\n")
    a = ast.body[0].body[0]
    assert isinstance(a.value, parser_mod.Phrase)
    assert a.value.name == ("inny", "rzecz")
    assert a.value.args == []


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


# ---------- Funkcje: deklaracja z parametrami ----------

def test_parse_func_decl_no_params(parse):
    ast = parse("aby działać:\n    x to 1\n")
    fd = ast.body[0]
    assert fd.name == ("działać",)
    assert fd.params == []


def test_parse_func_decl_with_param_no_prep(parse):
    # `aby pisać coś:` — `coś` to acc bez przyimka
    ast = parse("aby pisać coś:\n    x to 1\n")
    fd = ast.body[0]
    assert fd.name == ("pisać",)
    assert len(fd.params) == 1
    p = fd.params[0]
    assert isinstance(p, parser_mod.Param)
    assert p.prep is None
    assert p.name == ("coś",)
    assert p.case == frozenset({"acc"})


def test_parse_func_decl_with_prep(parse):
    # `aby czytać z klienta:` — `klient` (gen) z przyimkiem `z`
    ast = parse("aby czytać z klienta:\n    x to 1\n")
    fd = ast.body[0]
    p = fd.params[0]
    assert p.prep == ("z",)
    assert p.name == ("klient",)
    assert p.case == frozenset({"gen", "acc"})  # `klienta` to gen∨acc


def test_parse_func_decl_locative_with_prep(parse):
    # `aby nasłuchiwać na porcie:` — `port` (loc) z `na`
    ast = parse("aby nasłuchiwać na porcie:\n    x to 1\n")
    fd = ast.body[0]
    p = fd.params[0]
    assert p.prep == ("na",)
    assert p.name == ("port",)
    assert p.case == frozenset({"loc"})


def test_parse_func_decl_multiple_params(parse):
    # `aby wysłać coś do odbiorcy przez kanał od nadawcy:`
    src = "aby wysłać coś do odbiorcy przez kanał od nadawcy:\n    x to 1\n"
    ast = parse(src)
    fd = ast.body[0]
    assert fd.name == ("wysłać",)
    assert len(fd.params) == 4
    assert fd.params[0].prep is None and fd.params[0].name == ("coś",)
    assert fd.params[1].prep == ("do",) and fd.params[1].name == ("odbiorca",)
    assert fd.params[2].prep == ("przez",) and fd.params[2].name == ("kanał",)
    assert fd.params[3].prep == ("od",) and fd.params[3].name == ("nadawca",)


def test_parse_func_decl_preserves_surface(parse):
    ast = parse("aby czytać z klienta:\n    x to 1\n")
    p = ast.body[0].params[0]
    assert p.surface == ("klienta",)


# ---------- Funkcje: wywołanie ----------

def test_parse_phrase_no_args(parse):
    ast = parse("aby f:\n    siema\n")
    phrase = ast.body[0].body[0]
    assert isinstance(phrase, parser_mod.Phrase)
    assert phrase.args == []


def test_parse_phrase_with_string_arg(parse):
    ast = parse('aby f:\n    pisz "witaj, świecie"\n')
    phrase = ast.body[0].body[0]
    assert isinstance(phrase, parser_mod.Phrase)
    assert phrase.name == ("pisać",)
    assert len(phrase.args) == 1
    arg = phrase.args[0]
    assert arg.prep is None
    assert isinstance(arg.value, parser_mod.StrLit)
    assert arg.value.value == "witaj, świecie"


def test_parse_phrase_with_var_arg(parse):
    ast = parse("aby f:\n    pisz tekstem\n")
    phrase = ast.body[0].body[0]
    assert isinstance(phrase, parser_mod.Phrase)
    arg = phrase.args[0]
    assert arg.prep is None
    assert isinstance(arg.value, parser_mod.Phrase)
    assert arg.value.name == ("tekst",)
    assert arg.value.args == []
    assert arg.case == frozenset({"inst"})


def test_parse_phrase_with_prep_arg(parse):
    # `zapisz w mapie` — argument `w mapie` (prep `w`, loc)
    ast = parse("aby f:\n    zapisz w mapie\n")
    phrase = ast.body[0].body[0]
    assert isinstance(phrase, parser_mod.Phrase)
    assert len(phrase.args) == 1
    arg = phrase.args[0]
    assert arg.prep == ("w",)
    assert isinstance(arg.value, parser_mod.Phrase)
    assert arg.value.name == ("mapa",)
    assert arg.value.args == []
    # `mapie` jest formą dat∨loc
    assert arg.case == frozenset({"dat", "loc"})


def test_parse_phrase_multiple_args(parse):
    # `zaloguj annę tekstem` — dwa argumenty bez przyimków
    ast = parse("aby f:\n    zaloguj annę tekstem\n")
    phrase = ast.body[0].body[0]
    assert phrase.name == ("zalogować",)
    assert len(phrase.args) == 2
    assert phrase.args[0].prep is None
    assert phrase.args[1].prep is None


def test_parse_phrase_mixed_prep_and_no_prep(parse):
    src = "aby f:\n    zapisz_token w globalnej_mapie dla użytkownika\n"
    ast = parse(src)
    phrase = ast.body[0].body[0]
    assert phrase.name == ("zapisać", "token")
    assert len(phrase.args) == 2
    assert phrase.args[0].prep == ("w",)
    assert phrase.args[0].value.name == ("globalny", "mapa")
    assert phrase.args[1].prep == ("dla",)
    assert phrase.args[1].value.name == ("użytkownik",)


def test_parse_phrase_does_not_consume_next_statement(parse):
    # NEWLINE separuje wywołania — drugie nie jest argumentem pierwszego.
    # Uważamy z jednoliterowymi nazwami (`a` to przyimek w sgjp).
    src = (
        "aby f:\n"
        "    pisz wynik\n"
        "    pisz tekst\n"
    )
    ast = parse(src)
    body = ast.body[0].body
    assert len(body) == 2
    assert isinstance(body[0], parser_mod.Phrase)
    assert isinstance(body[1], parser_mod.Phrase)
    assert len(body[0].args) == 1
    assert len(body[1].args) == 1


def test_parse_dispatch_assignment_vs_phrase(parse):
    # `liczba to 5` to assignment, `pisz 5` to phrase (rozróżnienie po peek+1)
    ast = parse("aby f:\n    liczba to 5\n    pisz 5\n")
    body = ast.body[0].body
    assert isinstance(body[0], parser_mod.Assignment)
    assert isinstance(body[1], parser_mod.Phrase)


def test_parse_top_level_phrase(parse):
    # Wywołanie poza definicją funkcji
    ast = parse('pisz "hello"\n')
    assert isinstance(ast.body[0], parser_mod.Phrase)


# ---------- Phrase jako primary expression ----------

def test_parse_phrase_in_assignment_rhs(parse):
    # `pakiet to opakuj coś od klienta` — RHS to Phrase z dwoma argumentami
    ast = parse("aby f:\n    pakiet to opakuj coś od klienta\n")
    a = ast.body[0].body[0]
    assert isinstance(a, parser_mod.Assignment)
    assert a.target == ("pakiet",)
    assert isinstance(a.value, parser_mod.Phrase)
    assert a.value.name == ("opakować",)
    assert len(a.value.args) == 2
    # arg1: coś (no prep)
    assert a.value.args[0].prep is None
    assert isinstance(a.value.args[0].value, parser_mod.Phrase)
    assert a.value.args[0].value.name == ("coś",)
    assert a.value.args[0].value.args == []
    # arg2: od klienta
    assert a.value.args[1].prep == ("od",)
    assert a.value.args[1].value.name == ("klient",)


def test_parse_phrase_in_right_operand_of_binop(parse):
    # `liczba to 2 + odzyskaj liczbe z bazy` — Phrase jest prawym operandem +
    ast = parse("aby f:\n    liczba to 2 + odzyskaj liczbe z bazy\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp)
    assert expr.op == "+"
    assert isinstance(expr.left, parser_mod.IntLit) and expr.left.value == 2
    assert isinstance(expr.right, parser_mod.Phrase)
    assert expr.right.name == ("odzyskać",)
    assert len(expr.right.args) == 2
    assert expr.right.args[0].prep is None
    assert expr.right.args[1].prep == ("z",)


def test_parse_phrase_in_left_operand_of_binop(parse):
    # `wynik to odzyskaj liczbe z bazy + 6` — argumenty Phrase NIE pożerają `+ 6`
    ast = parse("aby f:\n    wynik to odzyskaj liczbe z bazy + 6\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp)
    assert expr.op == "+"
    assert isinstance(expr.left, parser_mod.Phrase)
    assert expr.left.name == ("odzyskać",)
    assert len(expr.left.args) == 2  # liczbe i z bazy — NIE 1 z gobble'd `+ 6`
    assert isinstance(expr.right, parser_mod.IntLit)
    assert expr.right.value == 6


def test_parse_phrase_args_dont_eat_binop(parse):
    # Eksplicytnie: simple_value w argach NIE wchodzi w binarne operatory
    ast = parse("aby f:\n    x to f a + b\n")
    expr = ast.body[0].body[0].value
    assert isinstance(expr, parser_mod.BinOp)
    assert expr.op == "+"
    # Lewa strona to Phrase f z jednym argiem `a`
    assert isinstance(expr.left, parser_mod.Phrase)
    assert len(expr.left.args) == 1


def test_parse_nested_phrase_requires_parens(parse):
    # Bez nawiasów: `f g h` to Phrase(f, [Arg(g), Arg(h)]), NIE Phrase(f, [Arg(Phrase(g, [h]))])
    ast = parse("aby f:\n    pisz alfa beta\n")
    phrase = ast.body[0].body[0]
    assert phrase.name == ("pisać",)
    assert len(phrase.args) == 2
    assert isinstance(phrase.args[0].value, parser_mod.Phrase)
    assert phrase.args[0].value.args == []
    assert isinstance(phrase.args[1].value, parser_mod.Phrase)
    assert phrase.args[1].value.args == []


def test_parse_nested_phrase_with_parens(parse):
    # Z nawiasami: `f (g h)` to Phrase(f, [Arg(Phrase(g, [h]))])
    ast = parse("aby f:\n    pisz (formatuj liczbę)\n")
    phrase = ast.body[0].body[0]
    assert phrase.name == ("pisać",)
    assert len(phrase.args) == 1
    inner = phrase.args[0].value
    assert isinstance(inner, parser_mod.Phrase)
    assert inner.name == ("formatować",)
    assert len(inner.args) == 1


# ---------- morph_anal: prepositions ----------

def test_load_returns_preps_dict(loaded):
    db, preps = loaded
    assert isinstance(preps, dict)


def test_preps_contains_basic_prepositions(preps):
    # Zestaw przypadków dla typowych przyimków
    assert "do" in preps and "gen" in preps["do"]
    assert "z" in preps and "gen" in preps["z"] and "inst" in preps["z"]
    assert "na" in preps and "acc" in preps["na"] and "loc" in preps["na"]
    assert "w" in preps and "acc" in preps["w"] and "loc" in preps["w"]
    assert "dla" in preps and "gen" in preps["dla"]


def test_preps_aliases_vocalic_variants(preps):
    # `ze` aliasuje do `z`, `we` do `w`, etc. — w `preps` mamy tylko bazowe
    assert "z" in preps
    # Nie ma osobnego klucza `ze` (został zaaliasowany pod `z`)
    assert "ze" not in preps
    assert "we" not in preps
    assert "nade" not in preps


def test_preps_excludes_archaic_qualifiers(preps):
    # `gwoli` ma `przest.` w sgjp — powinien być wykluczony
    assert "gwoli" not in preps


def test_parse_nested_parens(parse):
    # (1 + 2) * (3 + 4)
    ast = parse("aby f:\n    x to (1 + 2) * (3 + 4)\n")
    expr = ast.body[0].body[0].value
    assert expr.op == "*"
    assert expr.left.op == "+" and expr.right.op == "+"
