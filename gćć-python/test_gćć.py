"""Testy parsera strukturalnego (Pass 1) + lex + canonical + preps + ident.

Semantyka wyrażeń (BinOp/Logic/FunctionCall/Chain/Struct) jest testowana
w `test_expression.py`. Tutaj sprawdzamy szkielet modułu: definicje, control
structures, parametry, pola, walidację identyfikatorów.
"""

import os

import pytest

import lexer
import morph_anal
import preprocess
import parser as parser_mod
import expression
import ast_nodes as ast


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
    """Parser + ekspresion resolver."""
    def _parse(text):
        morphs = preprocess.preprocess(morph_anal.analyze(lexer.lex(text), db))
        module = parser_mod.parse(morphs, preps)
        expression.resolve_module(module, preps)
        return module
    return _parse


@pytest.fixture(scope="session")
def parse_struct_only(db, preps):
    """Tylko Pass 1 — bez resolvera. Phrase pozostaje surowe."""
    def _parse(text):
        morphs = preprocess.preprocess(morph_anal.analyze(lexer.lex(text), db))
        return parser_mod.parse(morphs, preps)
    return _parse


# ---------- Lexer ----------

def test_lex_skips_comments():
    toks = lexer.lex("# komentarz\nx to pięć\n")
    word_values = [t[1] for t in toks if t[0] is lexer.Token.WORD]
    assert word_values == [("x",), ("pięć",)]


def test_lex_emits_indent_and_dedent_on_eof():
    toks = lexer.lex("aby działać:\n    x to pięć\n")
    kinds = [t[0] for t in toks]
    assert lexer.Token.INDENT in kinds
    assert kinds[-1] is lexer.Token.DEDENT


def test_lex_emits_newline_after_each_content_line():
    toks = lexer.lex("aby działać:\n    x to pięć\n")
    newlines = [t for t in toks if t[0] is lexer.Token.NEWLINE]
    assert len(newlines) == 2


def test_lex_no_newline_for_empty_or_comment_lines():
    toks = lexer.lex("# komentarz\n\nx to pięć\n")
    newlines = [t for t in toks if t[0] is lexer.Token.NEWLINE]
    assert len(newlines) == 1


def test_lex_string_literal_preserves_internal_spaces():
    toks = lexer.lex('x to "ala ma kota"\n')
    text_values = [t[1] for t in toks if t[0] is lexer.Token.TEXT]
    assert text_values == ["ala ma kota"]


def test_lex_colon_split_from_preceding_word():
    toks = lexer.lex("klienta:\n")
    kinds = [t[0] for t in toks]
    assert kinds[0] is lexer.Token.WORD
    assert kinds[1] is lexer.Token.COLON


def test_lex_to_becomes_assign_token():
    toks = lexer.lex("x to pięć\n")
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
    toks = lexer.lex("(jeden plus dwa)\n")
    kinds = [t[0] for t in toks]
    assert lexer.Token.LPAREN in kinds
    assert lexer.Token.RPAREN in kinds


def test_lex_to_inside_underscore_identifier_stays_word():
    toks = lexer.lex("to_zrobic\n")
    word_toks = [t for t in toks if t[0] is lexer.Token.WORD]
    assert word_toks == [(lexer.Token.WORD, ("to", "zrobic"))]
    assert not any(t[0] is lexer.Token.ASSIGN for t in toks)


def test_lex_camelcase_splits_into_lowercase_segments():
    toks = lexer.lex("UżytkownikAdministrujący\n")
    word_toks = [t for t in toks if t[0] is lexer.Token.WORD]
    assert word_toks == [
        (lexer.Token.WORD, ("użytkownik", "administrujący")),
    ]


def test_lex_arrow_token():
    toks = lexer.lex("aby działać -> tekst:\n    zwrócić\n")
    kinds = [t[0] for t in toks]
    assert lexer.Token.ARROW in kinds


# ---------- canonical ----------

def _canonical_of(text, db):
    morphs = morph_anal.analyze(lexer.lex(text), db)
    word = next(m for m in morphs if m[0] is lexer.Token.WORD)
    return morph_anal.canonical(word)


def test_canonical_prefers_lemma_equal_form(db):
    assert _canonical_of("rzecz\n", db) == ("rzecz",)


def test_canonical_falls_back_to_first_analysis_when_no_lemma_matches_form(db):
    assert _canonical_of("klienta\n", db) == ("klient",)


def test_canonical_unknown_segment_uses_segment_as_lemma(db):
    assert _canonical_of("fibonacci\n", db) == ("fibonacci",)


def test_canonical_does_not_lemmatize_single_letters(db):
    assert _canonical_of("n\n", db) == ("n",)
    assert _canonical_of("a\n", db) == ("a",)


def test_canonical_participle_active_keeps_form(db):
    assert _canonical_of("administrującego\n", db) == ("administrujący",)


def test_canonical_participle_passive(db):
    assert _canonical_of("obserwowanego\n", db) == ("obserwowany",)


def test_canonical_multi_segment_identifier(db):
    assert _canonical_of("zapisz_w_bazie\n", db) == ("zapisać", "w", "baza")


def test_canonical_inflected_noun_in_underscore_id(db):
    assert _canonical_of("inna_rzecz\n", db) == ("inny", "rzecz")


def test_canonical_prefers_adj_over_substantivized_neuter(db):
    assert _canonical_of("zielonego\n", db) == ("zielony",)
    assert _canonical_of("pięknego\n", db) == ("piękny",)


# ---------- preps ----------

def test_load_returns_preps_dict(loaded):
    db, preps = loaded
    assert isinstance(preps, dict)
    assert len(preps) > 0


def test_preps_contains_basic_prepositions(preps):
    assert "na" in preps and "acc" in preps["na"] and "loc" in preps["na"]
    assert "w" in preps and "acc" in preps["w"] and "loc" in preps["w"]
    assert "dla" in preps and "gen" in preps["dla"]


def test_preps_aliases_vocalic_variants(preps):
    assert "z" in preps
    assert "ze" not in preps
    assert "we" not in preps
    assert "nade" not in preps


def test_preps_excludes_archaic_qualifiers(preps):
    assert "gwoli" not in preps


# ---------- Parser strukturalny: definicje funkcji ----------

def test_parse_func_decl_no_params(parse):
    m = parse("aby działać:\n    zwrócić\n")
    assert isinstance(m.body[0], ast.FunctionDef)
    assert ("działać",) in m.body[0].name.lemmas_set
    assert m.body[0].params == []


def test_parse_func_decl_with_param_no_prep(parse):
    m = parse("aby pisać x:\n    zwrócić\n")
    fd = m.body[0]
    assert len(fd.params) == 1
    assert fd.params[0].prep is None
    assert ("x",) in fd.params[0].name.lemmas_set


def test_parse_func_decl_with_prep(parse):
    m = parse("aby pisać_coś_do_klienta coś do klienta:\n    zwrócić\n")
    fd = m.body[0]
    assert len(fd.params) == 2
    assert fd.params[1].prep == ("do",)


def test_parse_func_decl_locative_with_prep(parse):
    m = parse("aby zapisywać_w_bazie x w bazie:\n    zwrócić\n")
    fd = m.body[0]
    p = fd.params[1]
    assert p.prep == ("w",)
    assert "loc" in p.case


def test_parse_func_decl_multiple_params(parse):
    m = parse(
        "aby wysłać coś do odbiorcy przez kanał od nadawcy:\n    zwrócić\n"
    )
    fd = m.body[0]
    assert len(fd.params) == 4
    preps_seen = [p.prep for p in fd.params]
    assert preps_seen == [None, ("do",), ("przez",), ("od",)]


def test_parse_func_decl_param_with_type(parse):
    m = parse("aby pisać x (Tekst):\n    zwrócić\n")
    fd = m.body[0]
    assert fd.params[0].type == ("tekst",)


def test_parse_func_decl_return_type(parse):
    m = parse("aby działać -> wynik:\n    zwrócić\n")
    fd = m.body[0]
    assert fd.return_type == ("wynik",)


def test_parse_func_decl_full_types(parse):
    m = parse(
        "aby usuwać_z_listy element (Tekst) z listy (Tekst) -> wynik:\n"
        "    zwrócić\n"
    )
    fd = m.body[0]
    assert fd.params[0].type == ("tekst",)
    assert fd.params[1].type == ("tekst",)
    assert fd.return_type == ("wynik",)


def test_parse_multiple_function_definitions(parse):
    m = parse(
        "aby działać:\n    zwrócić\n\n"
        "aby testować:\n    zwrócić\n"
    )
    assert len(m.body) == 2


# ---------- Parser strukturalny: definicje struktur ----------

def test_parse_struct_def_basic(parse):
    src = "definicja Sesji:\n    token (Tekst)\n    użytkownik (Tekst)\n"
    m = parse(src)
    sd = m.body[0]
    assert isinstance(sd, ast.StructDef)
    assert sd.name == ("sesja",)
    assert len(sd.fields) == 2


def test_parse_struct_name_camelcase_split(parse):
    src = "definicja AdresKorespondencyjny:\n    wartość (Tekst)\n"
    m = parse(src)
    assert m.body[0].name == ("adres", "korespondencyjny")


def test_parse_struct_field_name_lemmatized(parse):
    # Konwencja: pola deklaruj w mianowniku (head w nom). `autor` nom +
    # `komentarza` gen — head jest w nom, więc _field_lemmas akceptuje.
    src = "definicja Postu:\n    autor_komentarza (Tekst)\n"
    m = parse(src)
    assert ("autor", "komentarz") in m.body[0].fields[0].name.lemmas_set


def test_parse_struct_field_underscore_name(parse):
    src = "definicja Sesji:\n    adres_ip (Tekst)\n"
    m = parse(src)
    assert ("adres", "ip") in m.body[0].fields[0].name.lemmas_set


def test_parse_struct_then_function(parse):
    src = (
        "definicja Sesji:\n    token (Tekst)\n"
        "aby działać:\n    zwrócić\n"
    )
    m = parse(src)
    assert isinstance(m.body[0], ast.StructDef)
    assert isinstance(m.body[1], ast.FunctionDef)


# ---------- Parser strukturalny: control structures ----------

def test_parse_if_no_else(parse):
    src = (
        "aby działać:\n"
        "    jeśli a mniejsze od b:\n        x to jeden\n"
    )
    m = parse(src)
    if_node = m.body[0].body[0]
    assert isinstance(if_node, ast.If)
    assert if_node.else_body == []


def test_parse_if_else(parse):
    src = (
        "aby działać:\n"
        "    jeśli a mniejsze od b:\n        x to jeden\n"
        "    inaczej:\n        x to dwa\n"
    )
    m = parse(src)
    if_node = m.body[0].body[0]
    assert isinstance(if_node, ast.If)
    assert len(if_node.then_body) == 1
    assert len(if_node.else_body) == 1


def test_parse_nested_if(parse):
    src = (
        "aby działać:\n"
        "    jeśli a mniejsze od b:\n"
        "        jeśli c większe od d:\n"
        "            x to jeden\n"
        "        inaczej:\n"
        "            x to dwa\n"
    )
    m = parse(src)
    outer = m.body[0].body[0]
    assert isinstance(outer, ast.If)
    inner = outer.then_body[0]
    assert isinstance(inner, ast.If)
    assert len(inner.else_body) == 1


def test_parse_while(parse):
    src = (
        "aby działać:\n"
        "    dopóki a mniejsze od dziesięć:\n        a to a plus jeden\n"
    )
    m = parse(src)
    w = m.body[0].body[0]
    assert isinstance(w, ast.While)
    assert isinstance(w.cond, ast.Phrase)
    assert isinstance(w.cond.resolved, ast.BinOp) and w.cond.resolved.op == "<"


def test_parse_else_if_chain(parse):
    src = (
        "aby działać:\n"
        "    jeśli x mniejsze od jeden:\n        a to jeden\n"
        "    inaczej jeśli x mniejsze od dwa:\n        a to dwa\n"
        "    inaczej:\n        a to trzy\n"
    )
    m = parse(src)
    if1 = m.body[0].body[0]
    assert isinstance(if1, ast.If)
    if2 = if1.else_body[0]
    assert isinstance(if2, ast.If)
    assert len(if2.else_body) == 1
    assert isinstance(if2.else_body[0], ast.Assignment)


def test_parse_break_inside_while(parse):
    src = (
        "aby działać:\n"
        "    dopóki a mniejsze od dziesięć:\n"
        "        jeśli a równe pięć:\n            stop\n"
        "        a to a plus jeden\n"
    )
    m = parse(src)
    w = m.body[0].body[0]
    if_node = w.body[0]
    assert isinstance(if_node.then_body[0], ast.Break)


def test_parse_break_standalone(parse):
    src = "aby działać:\n    stop\n"
    m = parse(src)
    assert isinstance(m.body[0].body[0], ast.Break)


def test_parse_return_with_int(parse):
    m = parse("aby działać:\n    zwrócić pięć\n")
    r = m.body[0].body[0]
    assert isinstance(r, ast.Return)
    assert r.value.resolved == ast.IntLit(5)


def test_parse_return_with_expr(parse):
    m = parse("aby działać:\n    zwrócić dwa plus trzy\n")
    r = m.body[0].body[0]
    assert isinstance(r.value.resolved, ast.BinOp)


def test_parse_return_without_value(parse):
    m = parse("aby działać:\n    zwrócić\n")
    r = m.body[0].body[0]
    assert isinstance(r, ast.Return)
    assert r.value is None


# ---------- Assignment ----------

def test_parse_assignment_int_value(parse):
    m = parse("aby działać:\n    liczba to pięć\n")
    a = m.body[0].body[0]
    assert isinstance(a, ast.Assignment)
    assert isinstance(a.target, ast.Phrase)
    assert isinstance(a.value, ast.Phrase)
    assert a.value.resolved == ast.IntLit(5)


def test_parse_assignment_target_is_phrase(parse):
    m = parse("aby działać:\n    x to pięć\n")
    a = m.body[0].body[0]
    assert isinstance(a.target, ast.Phrase)


def test_parse_assignment_string_literal(parse):
    m = parse('aby działać:\n    x to "siemka"\n')
    a = m.body[0].body[0]
    assert a.value.resolved == ast.StrLit("siemka")


def test_parse_equality_is_comparison_not_assignment(parse):
    """`x to a równe b` — `to` to assignment, `równe` to porównanie."""
    m = parse("aby działać:\n    x to a równe b\n")
    a = m.body[0].body[0]
    assert isinstance(a, ast.Assignment)
    assert isinstance(a.value.resolved, ast.BinOp) and a.value.resolved.op == "="


# ---------- Walidacja identyfikatorów ----------

def _ident_of(parse, surface):
    m = parse(f"aby działać {surface}:\n    zwrócić\n")
    return m.body[0].params[0].name


def test_ident_valid_subst_only(parse):
    ident = _ident_of(parse, "autora")
    assert ("autor",) in ident.lemmas_set
    assert ident.case and "gen" in ident.case


def test_ident_valid_subst_plus_rest(parse):
    ident = _ident_of(parse, "autora_książki")
    assert ("autor", "książka") in ident.lemmas_set
    assert ident.case


def test_ident_valid_adj_plus_subst(parse):
    ident = _ident_of(parse, "szanownego_autora")
    assert ("szanowny", "autor") in ident.lemmas_set
    assert ident.case == frozenset({"gen", "acc"})


def test_ident_valid_two_adj_plus_subst(parse):
    ident = _ident_of(parse, "pięknego_szanownego_autora")
    assert len(ident.surface) == 3
    assert ident.case == frozenset({"gen", "acc"})


def test_ident_valid_adj_plus_subst_plus_rest(parse):
    ident = _ident_of(parse, "zielonego_drzewa_z_lasu")
    assert len(ident.surface) == 4
    assert "gen" in ident.case


def test_ident_valid_pact_alone(parse):
    ident = _ident_of(parse, "obserwującego")
    assert ("obserwujący",) in ident.lemmas_set
    assert ident.case


def test_ident_valid_ppas_alone(parse):
    ident = _ident_of(parse, "obserwowanego")
    assert ("obserwowany",) in ident.lemmas_set
    assert ident.case


def test_ident_invalid_qub_plus_adj(parse):
    with pytest.raises(ast.IdentifierError, match="czy_zielony"):
        _ident_of(parse, "czy_zielony")


def test_ident_pcon_plus_subst_is_valid_function_id(parse):
    ident = _ident_of(parse, "ruszając_kółkiem")
    assert ("ruszać", "kółko") in ident.lemmas_set
    assert ident.case is None


def test_ident_fin_plus_subst_is_valid_function_id(parse):
    ident = _ident_of(parse, "jadę_samochodem")
    assert ("jechać", "samochód") in ident.lemmas_set
    assert ident.case is None


def test_ident_invalid_error_mentions_expected_form(parse):
    with pytest.raises(ast.IdentifierError, match=r"\[przymiotnik\.\.\.\] \[rzeczownik\] \[reszta\]"):
        _ident_of(parse, "czy_zielony")
