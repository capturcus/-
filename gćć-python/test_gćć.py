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


# SGJP (db/preps) pochodzi ze współdzielonej fixturki sesyjnej w conftest.py.


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


# ---------- String escape sequences ----------

def test_lex_string_with_newline_escape():
    toks = lexer.lex('x to "hello\\nworld"\n')
    text_values = [t[1] for t in toks if t[0] is lexer.Token.TEXT]
    assert text_values == ["hello\nworld"]


def test_lex_string_with_tab_escape():
    toks = lexer.lex('x to "a\\tb"\n')
    text_values = [t[1] for t in toks if t[0] is lexer.Token.TEXT]
    assert text_values == ["a\tb"]


def test_lex_string_with_carriage_return_escape():
    toks = lexer.lex('x to "a\\rb"\n')
    text_values = [t[1] for t in toks if t[0] is lexer.Token.TEXT]
    assert text_values == ["a\rb"]


def test_lex_string_with_backslash_escape():
    toks = lexer.lex('x to "\\\\"\n')
    text_values = [t[1] for t in toks if t[0] is lexer.Token.TEXT]
    assert text_values == ["\\"]


def test_lex_string_with_quote_escape():
    toks = lexer.lex('x to "\\"hi\\""\n')
    text_values = [t[1] for t in toks if t[0] is lexer.Token.TEXT]
    assert text_values == ['"hi"']


def test_lex_string_with_multiple_escapes():
    toks = lexer.lex('x to "line1\\nline2\\ttab"\n')
    text_values = [t[1] for t in toks if t[0] is lexer.Token.TEXT]
    assert text_values == ["line1\nline2\ttab"]


def test_lex_string_unknown_escape_raises():
    with pytest.raises(ast.InterpreterError, match="nieznany escape"):
        lexer.lex('x to "hello\\xworld"\n')


def test_lex_string_empty():
    toks = lexer.lex('x to ""\n')
    text_values = [t[1] for t in toks if t[0] is lexer.Token.TEXT]
    assert text_values == [""]


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


def test_lex_camelcase_splits_into_segments_preserving_case():
    toks = lexer.lex("UżytkownikAdministrujący\n")
    word_toks = [t for t in toks if t[0] is lexer.Token.WORD]
    assert word_toks == [
        (lexer.Token.WORD, ("Użytkownik", "Administrujący")),
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
    assert fd.params[0].type.head == ("Tekst",)


def test_parse_func_decl_return_type(parse):
    m = parse("aby działać -> wynik:\n    zwrócić\n")
    fd = m.body[0]
    assert fd.return_type.head == ("wynik",)


def test_parse_func_decl_full_types(parse):
    m = parse(
        "aby usuwać_z_listy element (Tekst) z listy (Tekst) -> wynik:\n"
        "    zwrócić\n"
    )
    fd = m.body[0]
    assert fd.params[0].type.head == ("Tekst",)
    assert fd.params[1].type.head == ("Tekst",)
    assert fd.return_type.head == ("wynik",)


def test_parse_multiple_function_definitions(parse):
    m = parse(
        "aby działać:\n    zwrócić\n\n"
        "aby testować:\n    zwrócić\n"
    )
    assert len(m.body) == 2


# ---------- Parser strukturalny: deklaracje extern (`można`) ----------

def test_parse_extern_no_params(parse):
    """`można działać -> Nic` — najprostsza deklaracja extern."""
    m = parse("można działać -> Nic\n")
    e = m.body[0]
    assert isinstance(e, ast.ExternFunctionDef)
    assert ("działać",) in e.name.lemmas_set
    assert e.params == []
    assert e.return_type.head == ("Nic",)


def test_parse_extern_one_param_no_prep(parse):
    """`można wypisać tekst (Tekst) -> Nic` — jeden parametr bez przyimka."""
    m = parse("można wypisać tekst (Tekst) -> Nic\n")
    e = m.body[0]
    assert isinstance(e, ast.ExternFunctionDef)
    assert ("wypisać",) in e.name.lemmas_set
    assert len(e.params) == 1
    assert e.params[0].prep is None
    assert e.params[0].type.head == ("Tekst",)


def test_parse_extern_with_prep_param(parse):
    """`można zapisać do bazy (Baza) dane (Tekst) -> Nic` — parametr z przyimkiem."""
    m = parse("można zapisać do bazy (Baza) dane (Tekst) -> Nic\n")
    e = m.body[0]
    assert isinstance(e, ast.ExternFunctionDef)
    preps_seen = [p.prep for p in e.params]
    assert ("do",) in preps_seen
    assert all(p.type is not None for p in e.params)


def test_parse_extern_untyped_param_raises(parse):
    """Extern nie ma ciała do inferencji — parametr bez jawnego typu to błąd."""
    with pytest.raises(ast.InterpreterError, match="jawnego typu parametru"):
        parse("można leżeć na polanie w lesie przy jeziorze\n")


def test_parse_extern_partially_typed_raises(parse):
    """Wszystkie parametry muszą mieć typ — jeden bez typu wystarczy do błędu."""
    with pytest.raises(ast.InterpreterError, match="jawnego typu parametru 'jeziorze'"):
        parse("można leżeć na polanie (Miejsce) w lesie (Miejsce) przy jeziorze -> Liczba\n")


def test_parse_extern_missing_return_type_raises(parse):
    with pytest.raises(ast.InterpreterError, match="typu zwracanego"):
        parse("można wypisać tekst (Tekst)\n")


def test_parse_extern_multiple_prep_params_with_types(parse):
    """`można leżeć na polanie (Miejsce) w lesie (Miejsce) przy jeziorze (Liczba)
    -> Liczba` — typy w nawiasach przy każdym parametrze + typ zwracany."""
    m = parse(
        "można leżeć na polanie (Miejsce) w lesie (Miejsce) "
        "przy jeziorze (Liczba) -> Liczba\n"
    )
    e = m.body[0]
    assert isinstance(e, ast.ExternFunctionDef)
    assert len(e.params) == 3
    types_by_prep = {p.prep: p.type.head for p in e.params}
    assert types_by_prep[("na",)] == ("Miejsce",)
    assert types_by_prep[("w",)] == ("Miejsce",)
    assert types_by_prep[("przy",)] == ("Liczba",)
    assert e.return_type.head == ("Liczba",)


def test_parse_extern_with_return_type(parse):
    """`można policzyć x (Tekst) -> liczba` — z deklaracją typu zwracanego."""
    m = parse("można policzyć x (Tekst) -> liczba\n")
    e = m.body[0]
    assert isinstance(e, ast.ExternFunctionDef)
    assert e.return_type.head == ("liczba",)


def test_parse_extern_rejects_colon_body(parse):
    """`można` nie przyjmuje `:` — błąd składni."""
    with pytest.raises(SyntaxError):
        parse("można działać:\n    zwrócić\n")


def test_parse_extern_alongside_function_def(parse):
    """Extern i zwykłą funkcję można mieszać w jednym module."""
    src = (
        "można wypisać tekst (Tekst) -> Nic\n"
        "aby działać:\n"
        "    zwrócić\n"
    )
    m = parse(src)
    assert isinstance(m.body[0], ast.ExternFunctionDef)
    assert isinstance(m.body[1], ast.FunctionDef)


# ---------- Parser strukturalny: definicje struktur ----------

def test_parse_struct_def_basic(parse):
    src = "definicja Sesji:\n    token (Tekst)\n    użytkownik (Tekst)\n"
    m = parse(src)
    sd = m.body[0]
    assert isinstance(sd, ast.StructDef)
    assert sd.name == ("Sesja",)
    assert len(sd.fields) == 2


def test_parse_struct_name_camelcase_split(parse):
    src = "definicja AdresuKorespondencyjnego:\n    wartość (Tekst)\n"
    m = parse(src)
    assert m.body[0].name == ("Adres", "Korespondencyjny")


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
        "aby działać bok kres:\n"
        "    jeśli bok mniejsze od kres:\n        x to jeden\n"
    )
    m = parse(src)
    if_node = m.body[0].body[0]
    assert isinstance(if_node, ast.If)
    assert if_node.else_body == []


def test_parse_if_else(parse):
    src = (
        "aby działać bok kres:\n"
        "    jeśli bok mniejsze od kres:\n        x to jeden\n"
        "    inaczej:\n        x to dwa\n"
    )
    m = parse(src)
    if_node = m.body[0].body[0]
    assert isinstance(if_node, ast.If)
    assert len(if_node.then_body) == 1
    assert len(if_node.else_body) == 1


def test_parse_nested_if(parse):
    src = (
        "aby działać bok kres próg szczyt:\n"
        "    jeśli bok mniejsze od kres:\n"
        "        jeśli próg większe od szczyt:\n"
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
        "aby działać bok:\n"
        "    dopóki bok mniejsze od dziesięć:\n        bok to bok plus jeden\n"
    )
    m = parse(src)
    w = m.body[0].body[0]
    assert isinstance(w, ast.While)
    assert isinstance(w.cond, ast.Phrase)
    assert isinstance(w.cond.resolved, ast.BinOp) and w.cond.resolved.op == "<"


def test_parse_else_if_chain(parse):
    src = (
        "aby działać x:\n"
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
        "aby działać bok:\n"
        "    dopóki bok mniejsze od dziesięć:\n"
        "        jeśli bok równe pięć:\n            stop\n"
        "        bok to bok plus jeden\n"
    )
    m = parse(src)
    w = m.body[0].body[0]
    if_node = w.body[0]
    assert isinstance(if_node.then_body[0], ast.Break)


def test_parse_break_standalone(parse):
    src = "aby działać:\n    stop\n"
    m = parse(src)
    assert isinstance(m.body[0].body[0], ast.Break)


def test_parse_continue_standalone(parse):
    src = "aby działać:\n    dalej\n"
    m = parse(src)
    assert isinstance(m.body[0].body[0], ast.Continue)


def test_parse_continue_inside_for(parse):
    src = (
        "aby działać lista:\n"
        "    dla użytkownika w liście:\n"
        "        jeśli użytkownik równe pięć:\n            dalej\n"
        "        wynik to użytkownik\n"
    )
    m = parse(src)
    for_node = m.body[0].body[0]
    if_node = for_node.body[0]
    assert isinstance(if_node.then_body[0], ast.Continue)


def test_parse_continue_with_trailing_token_is_error(parse):
    src = "aby działać:\n    dalej coś\n"
    with pytest.raises(SyntaxError):
        parse(src)


def test_parse_dalej_inside_phrase_not_special(parse_struct_only):
    """`dalej` poza początkiem statementu pozostaje zwykłym tokenem phrase'a."""
    src = "aby działać:\n    a to dalej\n"
    m = parse_struct_only(src)
    a = m.body[0].body[0]
    assert isinstance(a, ast.Assignment)
    assert isinstance(a.value, ast.Phrase)
    assert not isinstance(a.value, ast.Continue)


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
    m = parse("aby działać bok kres:\n    x to bok równe kres\n")
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


# ---------- canonical_gen: strict gen w nazwie typu (definicja X) ----------

def test_struct_decl_gen_disambiguates_listy(parse):
    """`listy` w SGJP ma dwa lematy: `list` (m3, gen-pl-tylko-pl-nom) i `lista`
    (f, sg-gen + pl-nom). canonical_gen filtruje po gen — zostaje tylko
    `lista` (sg gen f). Bez tego canonical brałby `pool[0]` = `list`."""
    src = "definicja Listy:\n    rozmiar (Liczba)\n"
    m = parse(src)
    assert m.body[0].name == ("Lista",)


def test_struct_decl_gen_rejects_nom(parse):
    """`definicja Lista:` (sg nom, brak gen) → SyntaxError o dopełniaczu."""
    src = "definicja Lista:\n    x (Tekst)\n"
    with pytest.raises(SyntaxError, match="dopełniacz"):
        parse(src)


def test_struct_decl_gen_ambiguous():
    """Syntetyczny: token z 2 gen-analizami i różnymi lematami → SyntaxError."""
    from morph_anal import MorphAnalysis
    from identifier import canonical_type
    token = (
        lexer.Token.WORD,
        ("xyz",),
        [[
            MorphAnalysis(pos="subst", case=frozenset({"gen"}), number="sg", gender=frozenset({"f"}), lemma="alfa", tag="subst:sg:gen:f", qualifier=""),
            MorphAnalysis(pos="subst", case=frozenset({"gen"}), number="sg", gender=frozenset({"m"}), lemma="beta", tag="subst:sg:gen:m3", qualifier=""),
        ]],
    )
    with pytest.raises(SyntaxError, match="niejednoznaczna"):
        canonical_type(token, required_case="gen")


# ---------- Strict nom dla nazw typów ----------

def test_canonical_nom_rejects_non_nom_field_type(parse):
    """`(Tekstu)` (gen) jako typ pola — strict nom rzuca SyntaxError."""
    src = "definicja Foo:\n    x (Tekstu)\n"
    with pytest.raises(SyntaxError, match="mianownik"):
        parse(src)


def test_canonical_nom_disambiguates_listy_field_type(parse):
    """`(Listy)` jako typ pola — `listy` ma pl-nom dla DWÓCH lemm (`list` m3,
    `lista` f). Strict nom rzuca ambiguity SyntaxError."""
    src = "definicja Foo:\n    x (Listy)\n"
    with pytest.raises(SyntaxError, match="niejednoznaczna w mianowniku"):
        parse(src)


def test_canonical_nom_ambiguous_synthetic():
    """Syntetyczny: token z 2 nom-analizami i różnymi lematami → SyntaxError."""
    from morph_anal import MorphAnalysis
    from identifier import canonical_type
    token = (
        lexer.Token.WORD,
        ("xyz",),
        [[
            MorphAnalysis(pos="subst", case=frozenset({"nom"}), number="sg", gender=frozenset({"f"}), lemma="alfa", tag="subst:sg:nom:f", qualifier=""),
            MorphAnalysis(pos="subst", case=frozenset({"nom"}), number="sg", gender=frozenset({"m"}), lemma="beta", tag="subst:sg:nom:m3", qualifier=""),
        ]],
    )
    with pytest.raises(SyntaxError, match="niejednoznaczna w mianowniku"):
        canonical_type(token, required_case="nom")


# ---------- Capitalization: rozróżnienie typu od zmiennej przez caps ----------

def test_canonical_disambiguates_pora_homograph_in_field_type(parse):
    """Surface "Pora" w SGJP ma analizy z lematami `por` (warzywo, m3) i
    `pora` (czas, f). Pool[0] dla "pora" w SGJP to `por`. Bez `.lower()`
    w canonical-comparison `a.lemma == seg` dla capital "Pora" fallback
    wybrałby pool[0]="por" → wynik `("Por",)` (warzywo). Z `.lower()`
    citation-match wybiera lemma "pora" → wynik `("Pora",)` (czas).

    Test używa "Pora" jako typu pola (parse_field wywołuje canonical())."""
    src = "definicja Pory:\n    x (Pora)\n"
    m = parse(src)
    assert m.body[0].fields[0].type.head == ("Pora",)


def test_canonical_disambiguates_marka_homograph_in_field_type(parse):
    """Surface "Marka" — SGJP ma lematy `marek` (imię męskie m1) i `marka`
    (brand f). Pool[0] = `marek`. Bez `.lower()` capital "Marka" wpada
    w fallback → `("Marek",)`. Z `.lower()` → `("Marka",)`."""
    src = "definicja Marki:\n    x (Marka)\n"
    m = parse(src)
    assert m.body[0].fields[0].type.head == ("Marka",)


def test_canonical_preserves_case_distinction_type_vs_variable(parse):
    """Typ `Forma` i zmienna `forma` mają RÓŻNE lematy — `("Forma",)` vs
    `("forma",)` — dzięki capitalization. Nie kolidują w ctx.types/scope."""
    src = (
        "definicja Formy:\n    nazwa (Tekst)\n"
        "aby działać:\n"
        "    forma to Forma o nazwie \"v\"\n"
    )
    m = parse(src)
    sd = m.body[0]
    assert sd.name == ("Forma",)
    # Drugi assignment LHS to zmienna `forma` (lowercase) — nie koliduje z typem.
    asn = m.body[1].body[0]
    target = asn.target.resolved
    assert isinstance(target, ast.Identifier)
    assert ("forma",) in target.lemmas_set
    # RHS to StructCreation typu Forma (capitalized).
    sc = asn.value.resolved
    assert isinstance(sc, ast.StructCreation)
    assert sc.type_name == ("Forma",)


# ---------- Number/gender w wariantach + scope-key (lemmas, number, gender) ----------


def test_kotek_kotka_coexist_in_scope(parse):
    """`kotek` (m, sg, nom) i `kotka` (f, sg, nom) są deklarowane jako
    odrębne zmienne — różny scope-key mimo że surface `kotka` ma też
    interpretację `gen sg m` od `kotek`."""
    src = (
        "aby działać:\n"
        "    kotek to \"tom\"\n"
        "    kotka to \"lila\"\n"
    )
    m = parse(src)
    # Bez błędu — obie deklaracje akceptowane.
    body = m.body[0].body
    assert len(body) == 2


def test_forma_formy_distinct_scope(parse):
    """`forma` (sg, f) i `formy` (pl, f) mają różne scope-keys —
    deklarujemy je osobno, każda zmienna istnieje niezależnie."""
    src = (
        "aby działać:\n"
        "    forma to \"x\"\n"
        "    formy to pięć\n"
    )
    m = parse(src)
    body = m.body[0].body
    assert len(body) == 2


def test_lhs_ambiguous_nom_kotki_raises(parse):
    """`kotki` w mianowniku ma dwa warianty: `(kotek, pl, m)` i `(kotka,
    pl, f)`. LHS przypisania wymaga jednoznacznego mianownika — error."""
    src = (
        "aby działać:\n"
        "    kotki to \"x\"\n"
    )
    with pytest.raises(SyntaxError, match="niejednoznaczna w mianowniku"):
        parse(src)


def test_lhs_must_have_nom_raises(parse):
    """`Marka` (capital) — surface ma readings: `marek` (m1 sg nom-as-imię)
    i `marka` (f sg nom). Capital → lemmy capitalized. Tu pokazujemy że
    LHS bez nom (`marki` — dop. sg lub mian. pl) z ambiguity raises.
    Używamy `obserwującego` (ppas sg gen) — żadnego wariantu w nom."""
    src = (
        "aby działać:\n"
        "    obserwującego to \"x\"\n"
    )
    with pytest.raises(SyntaxError, match="mianownik"):
        parse(src)


def test_field_decl_ambiguous_nom_kotki_raises(parse):
    """Pole `kotki` w deklaracji struct-a — niejednoznaczne w mianowniku
    (pl m kotek vs pl f kotka) → error."""
    src = (
        "definicja Domu:\n"
        "    kotki (Tekst)\n"
    )
    with pytest.raises(SyntaxError, match="niejednoznaczn"):
        parse(src)


def test_variant_carries_number_gender(db):
    """`make_identifier('formy')` produkuje 2 warianty: (forma, pl, f) i
    (forma, sg, f). Sprawdzenie struktury Variant z polami number/gender."""
    from morph_anal import analyze
    from identifier import make_identifier
    toks = list(lexer.lex("formy"))
    word_tok = next(t for t in toks if t[0] is lexer.Token.WORD)
    analyzed = analyze([word_tok], db)
    ident = make_identifier(analyzed[0])
    keys = {(v.number, v.gender, "nom" in v.case) for v in ident.variants}
    assert ("pl", "f", True) in keys
    assert ("sg", "f", False) in keys  # sg variant jest w gen


def test_pure_adj_splits_by_gender(db):
    """`obserwującego` to ppas sg gen z gender m.n — po normalizacji 2
    osobne warianty (gender='m' i gender='n'). Pure-adj variants — bez
    subst-głowy — dziedziczą number/gender z adj segmentu."""
    from morph_anal import analyze
    from identifier import make_identifier
    toks = list(lexer.lex("obserwującego"))
    word_tok = next(t for t in toks if t[0] is lexer.Token.WORD)
    analyzed = analyze([word_tok], db)
    ident = make_identifier(analyzed[0])
    genders = {v.gender for v in ident.variants}
    assert "m" in genders
    assert "n" in genders


def test_field_decl_field_with_distinct_number_coexist(parse):
    """Dwa pola w jednej strukturze: `forma` (sg) i `formy` (pl) —
    różne pełne klucze, więc współistnieją (nie kolidują)."""
    src = (
        "definicja Słownika:\n"
        "    forma (Tekst)\n"
        "    formy (Tekst)\n"
    )
    m = parse(src)
    sd = m.body[0]
    assert len(sd.fields) == 2


# ---------- Typy wariantowe: lexer (QUESTION) ----------


# ---------- Typy wariantowe: deklaracja unii (`X to A albo B`) ----------


_UNION_STRUCTS = (
    "definicja Błędu:\n"
    "    opis (Tekst)\n"
    "\n"
    "definicja Wyniku z elementem:\n"
    "    wynik (element)\n"
    "\n"
)


def test_parse_union_def_two_members(parse_struct_only):
    m = parse_struct_only(_UNION_STRUCTS + "Rezultat to Wynik albo Błąd\n")
    ud = m.body[2]
    assert isinstance(ud, ast.UnionDef)
    assert ud.name == ("Rezultat",)
    assert ud.members == [("Wynik",), ("Błąd",)]


def test_parse_union_def_three_members(parse_struct_only):
    src = (
        _UNION_STRUCTS
        + "definicja Pustki:\n    nic (Liczba)\n\n"
        + "Rezultat to Wynik albo Błąd albo Pustka\n"
    )
    ud = parse_struct_only(src).body[3]
    assert isinstance(ud, ast.UnionDef)
    assert ud.members == [("Wynik",), ("Błąd",), ("Pustka",)]


def test_parse_union_def_requires_single_name_lhs(parse_struct_only):
    with pytest.raises(ast.InterpreterError, match="pojedynczej nazwy"):
        parse_struct_only("Rezultat dobry to Wynik albo Błąd\n")


def test_parse_union_def_trailing_albo_raises(parse_struct_only):
    with pytest.raises(ast.InterpreterError, match="co najmniej dwóch"):
        parse_struct_only("Rezultat to Wynik albo\n")


def test_parse_union_def_member_with_params_raises(parse_struct_only):
    # warianty deklaruje się bez parametrów typu
    with pytest.raises(ast.InterpreterError, match="bez parametrów typu"):
        parse_struct_only("Rezultat to Wynik z elementem albo Błąd\n")


def test_parse_union_def_double_albo_raises(parse_struct_only):
    with pytest.raises(ast.InterpreterError, match="nieoczekiwany token"):
        parse_struct_only("Rezultat to Wynik albo albo Błąd\n")


def test_parse_assignment_without_albo_not_union(parse_struct_only):
    m = parse_struct_only("rzecz to pięć\n")
    assert isinstance(m.body[0], ast.Assignment)


# ---------- Typy wariantowe: `X jest:` (match) ----------


_MATCH_SRC = (
    _UNION_STRUCTS
    + "Rezultat to Wynik albo Błąd\n"
    "\n"
    "aby działać:\n"
    "    rezultat jest:\n"
    "        Błędem z opisem:\n"
    "            x to jeden\n"
    "        Wynikiem z wynikiem:\n"
    "            x to dwa\n"
    "            y to trzy\n"
)


def test_parse_match_structure(parse_struct_only):
    m = parse_struct_only(_MATCH_SRC)
    match = m.body[3].body[0]
    assert isinstance(match, ast.Match)
    assert isinstance(match.subject, ast.Phrase)
    assert len(match.branches) == 2
    b_err, b_wyn = match.branches
    assert b_err.type_name == ("Błąd",)
    assert [f.surface for f in b_err.fields] == [("opisem",)]
    assert len(b_err.body) == 1
    assert b_wyn.type_name == ("Wynik",)
    assert [f.surface for f in b_wyn.fields] == [("wynikiem",)]
    assert len(b_wyn.body) == 2


def test_parse_match_branch_without_fields(parse_struct_only):
    src = (
        _UNION_STRUCTS
        + "aby działać:\n"
        "    rezultat jest:\n"
        "        Błędem:\n"
        "            x to jeden\n"
    )
    match = parse_struct_only(src).body[2].body[0]
    assert match.branches[0].fields == []


def test_parse_match_branch_requires_instrumental(parse_struct_only):
    # nazwa wariantu w mianowniku zamiast narzędnika ("jest Błąd") — błąd
    src = (
        "aby działać:\n"
        "    rezultat jest:\n"
        "        Błąd z opisem:\n"
        "            x to jeden\n"
    )
    with pytest.raises(ast.InterpreterError, match="musi być w narzędniku"):
        parse_struct_only(src)


def test_parse_match_requires_subject(parse_struct_only):
    # samo `jest:` bez wyrażenia przed — błąd
    src = (
        "aby działać:\n"
        "    jest:\n"
        "        Błędem z opisem:\n"
        "            x to jeden\n"
    )
    with pytest.raises(ast.InterpreterError, match="wymaga wyrażenia przed 'jest'"):
        parse_struct_only(src)


def test_parse_match_fields_require_z(parse_struct_only):
    src = (
        "aby działać:\n"
        "    rezultat jest:\n"
        "        Błędem o opisie:\n"
        "            x to jeden\n"
    )
    with pytest.raises(ast.InterpreterError, match="wprowadza 'z'"):
        parse_struct_only(src)


def test_parse_jest_without_colon_is_plain_phrase(parse_struct_only):
    # `jest` bez `:` po frazie nie wyzwala match-a — pozostaje frazą
    m = parse_struct_only("wynik jest\n")
    assert isinstance(m.body[0], ast.Phrase)


# ---------- Guard: pusta fraza na pozycji statementu (dawniej pętla ∞) ----------


def test_stray_colon_statement_raises(parse_struct_only):
    with pytest.raises(ast.InterpreterError, match="nieoczekiwany token"):
        parse_struct_only("x to pięć\n:\n")


def test_stray_overindented_block_raises(parse_struct_only):
    # przed guardem parser kręcił się w nieskończoność na INDENT
    src = (
        "aby działać:\n"
        "    x to pięć\n"
        "        y to dwa\n"
    )
    with pytest.raises(ast.InterpreterError, match="nieoczekiwany token"):
        parse_struct_only(src)


# ---------- Lexer: token QUESTION (wywołania z obsługą błędu) ----------


def test_lex_question_mark_token():
    toks = lexer.lex("wybrałbyś zero z części?\n")
    kinds = [t[0] for t in toks]
    assert lexer.Token.QUESTION in kinds
    # `?` rozcina od sąsiedniego słowa
    words = [t[1] for t in toks if t[0] is lexer.Token.WORD]
    assert ("części",) in words


def test_lex_question_mark_inside_string_is_text():
    toks = lexer.lex('x to "czy na pewno?"\n')
    kinds = [t[0] for t in toks]
    assert lexer.Token.QUESTION not in kinds
    text_values = [t[1] for t in toks if t[0] is lexer.Token.TEXT]
    assert text_values == ["czy na pewno?"]


# ---------- Gerundia: re-lematyzacja do formy cytowanej ----------


def _ident_for(db, word):
    from morph_anal import analyze
    from identifier import make_identifier
    toks = list(lexer.lex(word))
    word_tok = next(t for t in toks if t[0] is lexer.Token.WORD)
    return make_identifier(analyze([word_tok], db)[0])


def test_gerund_lemmatizes_to_citation_form(db):
    """`polubieniem` → lemma `polubienie` (nie `polubić`); pełny wariant
    rzeczownikowy: sg, nijaki, narzędnik."""
    ident = _ident_for(db, "polubieniem")
    keys = {(v.lemmas, v.number, v.gender) for v in ident.variants}
    assert (("polubienie",), "sg", "n") in keys
    assert all(v.lemmas == ("polubienie",) for v in ident.variants)
    assert any("inst" in v.case for v in ident.variants)


def test_gerund_inflection_shares_lemma(db):
    """Formy `polubienia` (gen sg / nom pl) dzielą lemmę `polubienie` —
    deklaracja pola i referencje spotykają się w jednej lemmie."""
    ident = _ident_for(db, "polubienia")
    assert all(v.lemmas == ("polubienie",) for v in ident.variants)
    numbers = {(v.number, "nom" in v.case) for v in ident.variants}
    assert ("pl", True) in numbers   # nom pl — deklaracja pola
    assert ("sg", False) in numbers  # gen sg — chain


def test_gerund_and_subst_homograph_merge(db):
    """`mieszkanie` ma czytanie subst ORAZ ger (od `mieszkać`) — po
    re-lematyzacji obie ścieżki dają lemmę `mieszkanie` i sklejają się
    w jeden wariant (bez sztucznej niejednoznaczności)."""
    ident = _ident_for(db, "mieszkanie")
    keys = {(v.lemmas, v.number, v.gender) for v in ident.variants}
    assert keys == {(("mieszkanie",), "sg", "n")}


def test_gerund_field_no_longer_conflicts_with_verb(parse):
    """Pole-gerundium `polubienia` i funkcja `polubić` współistnieją —
    przed re-lematyzacją pole dziedziczyło lemmę czasownika i wywalało
    'konflikt nazw: pole i funkcja'."""
    src = (
        "definicja Postu:\n"
        "    polubienia (Lista)\n"
        "\n"
        "definicja Węzła z elementem:\n"
        "    głowa (element)\n"
        "\n"
        "definicja PustejListy:\n"
        "    znacznik (Liczba)\n"
        "\n"
        "Lista to Węzeł albo PustaLista\n"
        "\n"
        "aby polubić post:\n"
        "    zwróć post\n"
        "\n"
        "aby działać post:\n"
        "    polubienia posta to PustaLista o znaczniku zero\n"
        "    suma to polubienia posta\n"
    )
    m = parse(src)
    # zapis do pola (chain LHS) i odczyt chainem — gerundium z pełną fleksją
    asn = m.body[5].body[0]
    assert isinstance(asn.target.resolved, ast.GetterChain)


# =====================================================================
# Gerundium: czasownik bazowy w analizach + rezerwacja `zastosować`
# =====================================================================


def test_gerund_analysis_carries_base_verb(db):
    """Re-lematyzacja podmienia lemat na formę cytowaną, ale `base`
    zachowuje czasownik — referencje gerundialne potrzebują obu."""
    gers = [a for a in db.get("rozbieraniem", []) if a.pos == "ger"]
    assert gers
    assert all(a.lemma == "rozbieranie" for a in gers)
    assert all(a.base == "rozbierać" for a in gers)


def test_non_gerund_analyses_have_no_base(db):
    assert all(a.base is None for a in db.get("kotem", []))
    assert all(a.base is None for a in db.get("wybrałbyś", []))
    # imiesłowy też przechodzą re-lematyzację, ale base dostają tylko ger
    assert all(a.base is None for a in db.get("obserwującego", []))


def test_zastosować_reserved_in_aby(parse):
    src = (
        "aby zastosować maść:\n"
        "    zwróć maść\n"
    )
    with pytest.raises(ast.InterpreterError, match="wbudowanym czasownikiem"):
        parse(src)


def test_zastosować_reserved_in_można(parse):
    src = "można zastosować maść (Tekst) -> Tekst\n"
    with pytest.raises(ast.InterpreterError, match="wbudowanym czasownikiem"):
        parse(src)


def test_zastosować_multiseg_not_reserved(parse):
    """Rezerwacja dotyczy tylko singletonu — `zastosować_filtr` to inna
    funkcja i nie koliduje z dyspozycją apply."""
    src = (
        "aby zastosować_filtr obraz:\n"
        "    zwróć obraz\n"
    )
    parse(src)  # nie rzuca
