"""Testy semantyki Pass 2: ekspresion + dispatch primary.

Sprawdzają jak `ExpressionParser` rozkłada `Phrase.tokens` na BinOp/UnaryOp/
And/Or/Not/FunctionCall/GetterChain/StructCreation/Identifier/IntLit/StrLit.
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
    def _parse(text):
        morphs = preprocess.preprocess(morph_anal.analyze(lexer.lex(text), db))
        module = parser_mod.parse(morphs, preps)
        expression.resolve_module(module, preps)
        return module
    return _parse


# ---------- Helpery ----------

def _value_of_first_assignment(module):
    """Bierze body pierwszej funkcji, pierwszy stmt jako Assignment, zwraca .value.resolved."""
    return module.body[0].body[0].value.resolved


def _wrap(rhs_expr):
    """Wzorzec: aby działać:\n    wynik to <expr>"""
    return f"aby działać:\n    wynik to {rhs_expr}\n"


# ---------- Liczby słowne (literały) ----------

@pytest.mark.parametrize("src,expected", [
    ("zero", 0),
    ("jeden", 1),
    ("pięć", 5),
    ("dwadzieścia trzy", 23),
    ("sto dwadzieścia trzy", 123),
    ("czterysta dwadzieścia pięć tysięcy czterysta trzydzieści pięć", 425435),
])
def test_int_literal_words(parse, src, expected):
    module = parse(_wrap(src))
    assert _value_of_first_assignment(module) == ast.IntLit(expected)


# ---------- Arytmetyka ----------

def test_add(parse):
    expr = _value_of_first_assignment(parse(_wrap("dwa plus trzy")))
    assert expr == ast.BinOp("+", ast.IntLit(2), ast.IntLit(3))


def test_sub(parse):
    expr = _value_of_first_assignment(parse(_wrap("pięć minus dwa")))
    assert expr == ast.BinOp("-", ast.IntLit(5), ast.IntLit(2))


def test_mul(parse):
    expr = _value_of_first_assignment(parse(_wrap("dwa razy trzy")))
    assert expr == ast.BinOp("*", ast.IntLit(2), ast.IntLit(3))


def test_precedence_mul_over_add(parse):
    # dwa plus trzy razy pięć -> BinOp(+, 2, BinOp(*, 3, 5))
    expr = _value_of_first_assignment(parse(_wrap("dwa plus trzy razy pięć")))
    assert expr == ast.BinOp(
        "+", ast.IntLit(2),
        ast.BinOp("*", ast.IntLit(3), ast.IntLit(5)),
    )


def test_left_associativity_of_subtraction(parse):
    expr = _value_of_first_assignment(parse(_wrap("dziesięć minus trzy minus dwa")))
    # ((10 - 3) - 2)
    assert expr == ast.BinOp(
        "-",
        ast.BinOp("-", ast.IntLit(10), ast.IntLit(3)),
        ast.IntLit(2),
    )


def test_parens_override_precedence(parse):
    # (dwa plus trzy) razy cztery -> BinOp(*, BinOp(+, 2, 3), 4)
    expr = _value_of_first_assignment(parse(_wrap("(dwa plus trzy) razy cztery")))
    assert expr == ast.BinOp(
        "*",
        ast.BinOp("+", ast.IntLit(2), ast.IntLit(3)),
        ast.IntLit(4),
    )


def test_unary_minus(parse):
    expr = _value_of_first_assignment(parse(_wrap("minus pięć")))
    assert expr == ast.UnaryOp("-", ast.IntLit(5))


def test_unary_plus(parse):
    expr = _value_of_first_assignment(parse(_wrap("plus pięć")))
    assert expr == ast.UnaryOp("+", ast.IntLit(5))


# ---------- Porównania ----------

@pytest.mark.parametrize("src,op", [
    ("dwa mniejsze od trzy", "<"),
    ("dwa większe od trzy", ">"),
    ("dwa mniejsze równe trzy", "<="),
    ("dwa większe równe trzy", ">="),
    ("dwa równe trzy", "="),
    ("dwa nierówne trzy", "!="),
])
def test_comparison_ops(parse, src, op):
    expr = _value_of_first_assignment(parse(_wrap(src)))
    assert expr == ast.BinOp(op, ast.IntLit(2), ast.IntLit(3))


def test_comparison_lower_precedence_than_arith(parse):
    # jeden plus dwa mniejsze od trzy plus cztery
    expr = _value_of_first_assignment(parse(_wrap(
        "jeden plus dwa mniejsze od trzy plus cztery"
    )))
    assert isinstance(expr, ast.BinOp) and expr.op == "<"
    assert isinstance(expr.left, ast.BinOp) and expr.left.op == "+"
    assert isinstance(expr.right, ast.BinOp) and expr.right.op == "+"


# ---------- Logika ----------

def test_not_with_phrase(parse):
    # `nie inna_zmienna` → Not(Identifier(inna_zmienna))
    expr = _value_of_first_assignment(parse(_wrap("nie inna_zmienna")))
    assert isinstance(expr, ast.Not)
    assert isinstance(expr.operand, ast.Identifier)
    assert ("inny", "zmienny") in expr.operand.lemmas_set


def test_not_lower_precedence_than_comparison(parse):
    # `nie dwa większe od trzy` → Not(BinOp(>, 2, 3))
    expr = _value_of_first_assignment(parse(_wrap("nie dwa większe od trzy")))
    assert isinstance(expr, ast.Not)
    assert isinstance(expr.operand, ast.BinOp) and expr.operand.op == ">"


def test_and(parse):
    expr = _value_of_first_assignment(parse(_wrap("warunek i inny_warunek")))
    assert isinstance(expr, ast.And)
    assert isinstance(expr.left, ast.Identifier)
    assert isinstance(expr.right, ast.Identifier)


def test_or(parse):
    expr = _value_of_first_assignment(parse(_wrap("warunek lub inny_warunek")))
    assert isinstance(expr, ast.Or)


def test_or_lower_precedence_than_and(parse):
    # `a i b lub c` → Or(And(a, b), c)
    expr = _value_of_first_assignment(parse(_wrap("a i b lub c")))
    assert isinstance(expr, ast.Or)
    assert isinstance(expr.left, ast.And)


# ---------- Function calls ----------

def test_simple_function_call(parse):
    src = (
        "aby pisać x:\n    zwrócić\n"
        "aby działać:\n    pisz \"hej\"\n"
    )
    m = parse(src)
    fc = m.body[1].body[0].resolved
    assert isinstance(fc, ast.FunctionCall)
    assert ("pisać",) in fc.name.lemmas_set
    assert len(fc.params) == 1
    assert isinstance(fc.params[0], ast.Word)
    assert fc.params[0].value == ast.StrLit("hej")


def test_function_call_arg_with_prep(parse):
    src = (
        "aby wywołać_funkcję z liczbą:\n    zwrócić\n"
        "aby działać:\n    wywołaj_funkcję z dwa\n"
    )
    m = parse(src)
    fc = m.body[1].body[0].resolved
    assert isinstance(fc, ast.FunctionCall)
    assert ("wywołać", "funkcja") in fc.name.lemmas_set
    assert fc.params[0].prep == ("z",)
    assert fc.params[0].value == ast.IntLit(2)


def test_function_call_followed_by_binop_left_binding(parse):
    """`weź_wiek_z_bazy dla identyfikatora plus siedem` →
    BinOp(+, FCall(weź_wiek_z_bazy, [identyfikator]), IntLit(7))."""
    src = (
        "aby weź_wiek_z_bazy dla identyfikatora:\n    zwrócić\n"
        "aby działać:\n    wynik to weź_wiek_z_bazy dla identyfikatora plus siedem\n"
    )
    m = parse(src)
    expr = m.body[1].body[0].value.resolved
    assert isinstance(expr, ast.BinOp) and expr.op == "+"
    assert isinstance(expr.left, ast.FunctionCall)
    assert ("wziąć", "wiek", "z", "baza") in expr.left.name.lemmas_set
    assert expr.right == ast.IntLit(7)


def test_top_level_fcall_with_arith_arg_is_binop(parse):
    """`wywołaj_funkcję z dwa plus trzy` na top-level →
    BinOp(+, FCall(wywołać_funkcja, [Word(z, 2)]), IntLit(3)).
    Lewostronne wiązanie: fcall zżera tylko primary, plus na zewnątrz."""
    src = (
        "aby wywołać_funkcję z liczbą:\n    zwrócić\n"
        "wywołaj_funkcję z dwa plus trzy\n"
    )
    m = parse(src)
    expr = m.body[1].resolved  # top-level expression statement
    assert isinstance(expr, ast.BinOp) and expr.op == "+"
    assert isinstance(expr.left, ast.FunctionCall)
    assert expr.right == ast.IntLit(3)


def test_function_call_with_paren_arith_arg(parse):
    """`wywołaj_funkcję z (dwa plus trzy)` → fcall arg = BinOp(+, 2, 3)."""
    src = (
        "aby wywołać_funkcję z liczbą:\n    zwrócić\n"
        "wywołaj_funkcję z (dwa plus trzy)\n"
    )
    m = parse(src)
    expr = m.body[1].resolved
    assert isinstance(expr, ast.FunctionCall)
    assert isinstance(expr.params[0].value, ast.BinOp)


# ---------- Getter chain ----------

def test_simple_chain(parse):
    src = (
        "definicja Postu:\n    autor (Tekst)\n    treść (Tekst)\n"
        "aby działać:\n    wynik to autor postu\n"
    )
    m = parse(src)
    chain = m.body[1].body[0].value.resolved
    assert isinstance(chain, ast.GetterChain)
    assert len(chain.chain) == 2
    assert ("autor",) in chain.chain[0].lemmas_set
    assert ("post",) in chain.chain[1].lemmas_set


def test_chain_with_arith_left_binding(parse):
    """`liczba_polubień posta plus dwadzieścia osiem` →
    BinOp(+, GetterChain([liczba_polubień, post]), IntLit(28))."""
    src = (
        "definicja Postu:\n    liczba_polubień (Liczba)\n"
        "aby działać:\n    wynik to liczba_polubień posta plus dwadzieścia osiem\n"
    )
    m = parse(src)
    expr = m.body[1].body[0].value.resolved
    assert isinstance(expr, ast.BinOp) and expr.op == "+"
    assert isinstance(expr.left, ast.GetterChain)
    assert expr.right == ast.IntLit(28)


# ---------- Struct creation ----------

def test_struct_creation_basic(parse):
    src = (
        "definicja Użytkownika:\n    nazwa (Tekst)\n"
        "aby działać:\n    wynik to nowy Użytkownik o nazwie \"Anna\"\n"
    )
    m = parse(src)
    sc = m.body[1].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assert sc.type_name == ("Użytkownik",)
    assert len(sc.args) == 1
    assert sc.args[0].field_name == (("nazwa",), "sg", "f")
    assert sc.args[0].value == ast.StrLit("Anna")


def test_struct_creation_field_value_is_full_expr(parse):
    """Wartość pola to PEŁNE wyrażenie (BinOp/FCall/itp.)."""
    src = (
        "aby weź_wiek_z_bazy dla identyfikatora:\n    zwrócić\n"
        "definicja Użytkownika:\n    wiek (Liczba)\n    nazwa (Tekst)\n"
        "aby działać:\n"
        "    wynik to nowy Użytkownik o wieku weź_wiek_z_bazy dla identyfikatora plus siedem o nazwie \"Anna\"\n"
    )
    m = parse(src)
    sc = m.body[2].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    # Pierwsze pole — wiek = BinOp(+, FCall, 7)
    wiek_arg = next(a for a in sc.args if a.field_name == (("wiek",), "sg", "m"))
    assert isinstance(wiek_arg.value, ast.BinOp) and wiek_arg.value.op == "+"
    assert isinstance(wiek_arg.value.left, ast.FunctionCall)
    assert wiek_arg.value.right == ast.IntLit(7)
    # Drugie — nazwa = "Anna"
    nazwa_arg = next(a for a in sc.args if a.field_name == (("nazwa",), "sg", "f"))
    assert nazwa_arg.value == ast.StrLit("Anna")


def test_struct_creation_shorthand(parse):
    src = (
        "definicja Użytkownika:\n    nazwa (Tekst)\n    wiek (Liczba)\n"
        "aby działać:\n    u to nowy Użytkownik z nazwą z wiekiem\n"
    )
    m = parse(src)
    sc = m.body[1].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assert len(sc.args) == 2
    assert all(a.value is None for a in sc.args)
    assert {a.field_name for a in sc.args} == {
        (("nazwa",), "sg", "f"), (("wiek",), "sg", "m"),
    }


# ---------- Identifier reference ----------

def test_bare_identifier_single_letter(parse):
    src = "aby działać:\n    x to y\n"
    m = parse(src)
    expr = m.body[0].body[0].value.resolved
    assert isinstance(expr, ast.Identifier)
    assert ("y",) in expr.lemmas_set


def test_bare_identifier_multiseg_no_verb(parse):
    """Multi-segment bez czasownika → identifier_ref (nie próba fcall)."""
    src = "aby działać:\n    x to wielki_kot\n"
    m = parse(src)
    expr = m.body[0].body[0].value.resolved
    assert isinstance(expr, ast.Identifier)
    assert ("wielki", "kot") in expr.lemmas_set


# ---------- Two-pass: forward references działają ----------

def test_function_can_be_called_before_definition(parse):
    """Sygnatury są zbierane w pierwszym przebiegu — call przed def jest OK."""
    src = (
        "aby działać:\n    pisz \"hej\"\n"
        "aby pisać x:\n    zwrócić\n"
    )
    m = parse(src)
    fc = m.body[0].body[0].resolved
    assert isinstance(fc, ast.FunctionCall)
    assert ("pisać",) in fc.name.lemmas_set


# ---------- Identifier variants (subst vs adj-prefix) ----------

def _make_ident(db, surface_text):
    """Pomocnik: make_identifier dla pojedynczego słowa."""
    import identifier as ident_mod
    toks = morph_anal.analyze(lexer.lex(surface_text + "\n"), db)
    word = next(t for t in toks if t[0] is lexer.Token.WORD)
    return ident_mod.make_identifier(word)


def test_identifier_has_multiple_variants_when_segment_ambiguous(db):
    """`części_mowy` ma w SGJP dwa odczyty: subst+subst (`część` gen.dat.loc
    + `mowa`) i adj+subst (`częsty` adj:m1.pl.nom.voc + `mowa`). Identifier
    musi nieść oba warianty, żeby dispatcher kontekstowy mógł wybrać."""
    ident = _make_ident(db, "części_mowy")
    seg_options = {v.lemmas for v in ident.variants}
    assert ("część", "mowa") in seg_options
    assert ("częsty", "mowa") in seg_options


def test_default_segments_pick_largest_case_set(db):
    """Po refaktorze: `Identifier.segments` (heurystyka max case-set)
    została usunięta. Identyfikator niesie WSZYSTKIE warianty; weryfikujemy
    że zarówno subst-prefix jak i adj-prefix są dostępne, oraz że `case`
    to union casów wszystkich wariantów."""
    ident = _make_ident(db, "części_mowy")
    assert ("część", "mowa") in ident.lemmas_set
    assert ("częsty", "mowa") in ident.lemmas_set
    # Sanity: union case = wszystkie z obu wariantów
    assert "gen" in ident.case
    assert "loc" in ident.case
    assert "nom" in ident.case


def test_single_variant_when_no_ambiguity(db):
    """`część` w nominativie ma TYLKO subst reading (brak adj `częsty:nom:f`)
    — Identifier ma tylko 1 wariant."""
    ident = _make_ident(db, "część")
    assert len(ident.variants) == 1
    v = ident.variants[0]
    assert v.lemmas == ("część",)


def test_chain_head_subst_variant_when_adj_variant_exists(parse):
    """Pole `("część","mowa")` jest field-em. Mimo że identyfikator
    `części_mowy` ma TAKŻE adj-variant `("częsty","mowa")` który NIE jest
    field-em, dispatcher znajduje subst-variant i startuje chain."""
    src = (
        "definicja Słowa:\n    część_mowy (Tekst)\n"
        "aby działać:\n    wynik to części_mowy słowa\n"
    )
    m = parse(src)
    expr = m.body[1].body[0].value.resolved
    assert isinstance(expr, ast.GetterChain)
    assert len(expr.chain) == 2
    head = expr.chain[0]
    # Head niesie oba warianty
    seg_options = {v.lemmas for v in head.variants}
    assert ("część", "mowa") in seg_options
    assert ("częsty", "mowa") in seg_options


def test_struct_arg_loc_picks_subst_variant(parse):
    """`nowe Słowo o części_mowy ...` — dispatcher struct arg wymaga loc.
    Subst-prefix `("część","mowa")` ma loc, adj-prefix `("częsty","mowa")`
    nie ma loc. Wybierz subst-variant. (Field decl jest sg-f, więc reference
    też musi być sg dla pełnego klucza match.)"""
    src = (
        "definicja Słowa:\n    część_mowy (Tekst)\n"
        "aby działać:\n    s to nowe Słowo o części_mowy \"czasownik\"\n"
    )
    m = parse(src)
    sc = m.body[1].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assert sc.type_name == ("Słowo",)
    assert len(sc.args) == 1
    assert sc.args[0].field_name == (("część", "mowa"), "sg", "f")
    assert sc.args[0].value == ast.StrLit("czasownik")


def test_struct_creation_no_match_leaves_tokens(parse):
    """`o pole` które nie matchuje żadnego pola w typie → struct args
    kończą się bez args. Pozostałe tokeny prowadzą do ResolveError
    (nie są ignorowane). Brak match nie jest błędem dispatchera, ale
    tokeny dalej muszą się sparsować."""
    src = (
        "definicja Punktu:\n    x (Liczba)\n"
        "aby działać:\n    p to nowy Punkt o nazwie \"A\"\n"
    )
    with pytest.raises(ast.ResolveError):
        parse(src)


# ---------- Diagnostyka leftover tokenów ----------


def test_diag_leftover_after_chain_unfollowable(parse):
    """Chain `autor postu` zjada 2 tokeny; `komentarza` jest gen-word ale
    `postu` nie jest polem (lemmat = `post` to nie field) — chain nie może
    iść dalej. Diagnostyka mówi: 'autor postu' rozpoznane jako chain, oraz
    że `komentarza` wygląda jak rozszerzenie ale `postu` nie jest polem."""
    src = (
        "definicja Posta:\n    autor (Tekst)\n"
        "aby działać:\n    wynik to autor postu komentarza\n"
    )
    with pytest.raises(ast.ResolveError, match="chain.*autor postu") as ei:
        parse(src)
    msg = str(ei.value)
    assert "nie jest polem" in msg
    assert "komentarza" in msg


def test_diag_leftover_after_ident_undeclared(parse):
    """`nieznana_zmienna posta` — `nieznana_zmienna` nie jest niczym
    znanym (zmienną/funkcją/polem/typem). Diagnostyka sugeruje literówkę
    lub brakującą deklarację."""
    src = (
        "aby działać:\n    x to nieznana_zmienna posta\n"
    )
    with pytest.raises(ast.ResolveError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "nieznana_zmienna" in msg
    assert "literówka" in msg or "brakująca deklaracja" in msg


def test_diag_leftover_after_struct_field_missing(parse):
    """`nowy Punkt o nazwie ...` — pole `nazwa` nie istnieje w typie `Punkt`
    (dostępne tylko `x`). Diagnostyka mówi nazwę struct'a i listę dostępnych
    pól."""
    src = (
        "definicja Punktu:\n    x (Liczba)\n"
        "aby działać:\n    p to nowy Punkt o nazwie \"A\"\n"
    )
    with pytest.raises(ast.ResolveError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "Punkt" in msg
    assert "Dostępne pola" in msg
    assert "x" in msg


def test_diag_leftover_after_fcall_extra_tokens(parse):
    """fcall `weź "hello"` zjada 1 argument; `leftover` po nim. Diagnostyka
    mówi że funkcja wzięła N argument(ów) i nic więcej nie spodziewała."""
    src = (
        "aby weź x (Tekst):\n    zwróć x\n"
        "aby działać:\n    wynik to weź \"hello\" leftover\n"
    )
    with pytest.raises(ast.ResolveError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "weź" in msg
    assert "argument" in msg


def test_diag_leftover_after_literal(parse):
    """Po literacie tekstowym nieoczekiwany token — komunikat o oczekiwaniu
    operatora."""
    src = (
        "aby działać:\n    x to \"hello\" nieoczekiwane\n"
    )
    with pytest.raises(ast.ResolveError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "operatora" in msg


# ---------- Subscript ----------

def test_subscript_atom_int_index(parse):
    """`lista pod jeden` → Subscript(Identifier(lista), IntLit(1))."""
    expr = _value_of_first_assignment(parse(_wrap("lista pod jeden")))
    assert isinstance(expr, ast.Subscript)
    assert isinstance(expr.target, ast.Identifier)
    assert ("lista",) in expr.target.lemmas_set
    assert expr.index == ast.IntLit(1)


def test_subscript_atom_ident_index(parse):
    """`lista pod indeksem` → Subscript(Identifier, Identifier)."""
    expr = _value_of_first_assignment(parse(_wrap("lista pod indeksem")))
    assert isinstance(expr, ast.Subscript)
    assert isinstance(expr.target, ast.Identifier)
    assert ("lista",) in expr.target.lemmas_set
    assert isinstance(expr.index, ast.Identifier)
    assert ("indeks",) in expr.index.lemmas_set


def test_subscript_left_associative(parse):
    """`lista pod jeden pod dwa` → Subscript(Subscript(lista, 1), 2).
    Iteracja jak w arith — kolejne `pod` rozszerzają tylko lewy operand."""
    expr = _value_of_first_assignment(parse(_wrap("lista pod jeden pod dwa")))
    assert isinstance(expr, ast.Subscript)
    assert expr.index == ast.IntLit(2)
    assert isinstance(expr.target, ast.Subscript)
    assert expr.target.index == ast.IntLit(1)
    assert isinstance(expr.target.target, ast.Identifier)
    assert ("lista",) in expr.target.target.lemmas_set


def test_subscript_lower_precedence_than_arith(parse):
    """`lista pod indeksem plus jeden` → BinOp(+, Subscript(...), 1).
    Subscript w `factor`, plus w `arith`."""
    expr = _value_of_first_assignment(parse(_wrap("lista pod indeksem plus jeden")))
    assert isinstance(expr, ast.BinOp) and expr.op == "+"
    assert isinstance(expr.left, ast.Subscript)
    assert expr.right == ast.IntLit(1)


def test_subscript_inside_arith_via_parens(parse):
    """`lista pod (indeksem plus jeden)` → Subscript(lista, BinOp(+, indeksem, 1))."""
    expr = _value_of_first_assignment(parse(_wrap("lista pod (indeksem plus jeden)")))
    assert isinstance(expr, ast.Subscript)
    assert isinstance(expr.index, ast.BinOp) and expr.index.op == "+"


def test_subscript_lower_precedence_than_not(parse):
    """`nie lista pod indeksem` → Not(Subscript(...))."""
    expr = _value_of_first_assignment(parse(_wrap("nie lista pod indeksem")))
    assert isinstance(expr, ast.Not)
    assert isinstance(expr.operand, ast.Subscript)


def test_subscript_on_fcall_result(parse):
    """`weź dla numeru pod indeksem` (1-arg fcall) → Subscript(FCall, indeksem).
    Subscript wisi na WYNIKU fcall, nie na argumencie — bo argumenty
    fcall używają `primary`, nie `subscript`."""
    src = (
        "aby weź dla numeru:\n    zwrócić\n"
        "aby działać:\n    wynik to weź dla numeru pod indeksem\n"
    )
    m = parse(src)
    expr = m.body[1].body[0].value.resolved
    assert isinstance(expr, ast.Subscript)
    assert isinstance(expr.target, ast.FunctionCall)
    assert ("wziąć",) in expr.target.name.lemmas_set
    assert isinstance(expr.index, ast.Identifier)
    assert ("indeks",) in expr.index.lemmas_set


def test_subscript_inside_fcall_arg_via_parens(parse):
    """`weź dla (numeru pod indeksem)` → FCall(weź, [Subscript(numer, indeks)])."""
    src = (
        "aby weź dla numeru:\n    zwrócić\n"
        "aby działać:\n    wynik to weź dla (numeru pod indeksem)\n"
    )
    m = parse(src)
    expr = m.body[1].body[0].value.resolved
    assert isinstance(expr, ast.FunctionCall)
    assert ("wziąć",) in expr.name.lemmas_set
    assert len(expr.params) == 1
    assert isinstance(expr.params[0].value, ast.Subscript)


def test_subscript_chain_as_index(parse):
    """`lista pod numerem autora` (numer = field) →
    Subscript(lista, GetterChain(numer, autor)).
    Prawy operand `pod` to primary, więc chain wewnątrz indeksu działa."""
    src = (
        "definicja Wpisu:\n    numer (Liczba)\n"
        "aby działać:\n    wynik to lista pod numerem autora\n"
    )
    m = parse(src)
    expr = m.body[1].body[0].value.resolved
    assert isinstance(expr, ast.Subscript)
    assert isinstance(expr.target, ast.Identifier)
    assert ("lista",) in expr.target.lemmas_set
    assert isinstance(expr.index, ast.GetterChain)
    assert len(expr.index.chain) == 2
    assert ("numer",) in expr.index.chain[0].lemmas_set
    assert ("autor",) in expr.index.chain[1].lemmas_set


def test_subscript_as_assignment_target(parse):
    """`lista pod indeksem to jeden` — LHS przypisania to Subscript."""
    src = "aby działać:\n    lista pod indeksem to jeden\n"
    m = parse(src)
    asn = m.body[0].body[0]
    assert isinstance(asn, ast.Assignment)
    assert isinstance(asn.target.resolved, ast.Subscript)
    assert ("lista",) in asn.target.resolved.target.lemmas_set
    assert ("indeks",) in asn.target.resolved.index.lemmas_set
    assert asn.value.resolved == ast.IntLit(1)


def test_subscript_in_struct_field_value(parse):
    """`nowe Pudełko o wartości lista pod jeden` — value pola = Subscript.
    Wartość pola w struct_creation parsuje się przez `parse_phrase`,
    więc subscript naturalnie się stosuje."""
    src = (
        "definicja Pudełka:\n    wartość (Liczba)\n"
        "aby działać:\n    p to nowe Pudełko o wartości lista pod jeden\n"
    )
    m = parse(src)
    sc = m.body[1].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assert sc.type_name == ("Pudełko",)
    assert len(sc.args) == 1
    assert sc.args[0].field_name == (("wartość",), "sg", "f")
    assert isinstance(sc.args[0].value, ast.Subscript)
    assert sc.args[0].value.index == ast.IntLit(1)


def test_subscript_after_fcall_with_two_args(parse):
    """`weź_z_bazy autora po listą pod indeksem` (2-arg fcall) →
    Subscript(FCall(z dwoma args), indeks)."""
    src = (
        "aby weź_z_bazy autora po listą:\n    zwrócić\n"
        "aby działać:\n"
        "    wynik to weź_z_bazy autora po listą pod indeksem\n"
    )
    m = parse(src)
    expr = m.body[1].body[0].value.resolved
    assert isinstance(expr, ast.Subscript)
    assert isinstance(expr.target, ast.FunctionCall)
    assert len(expr.target.params) == 2
    assert isinstance(expr.index, ast.Identifier)
    assert ("indeks",) in expr.index.lemmas_set


def test_subscript_full_composition(parse):
    """Pełny przykład 5 użytkownika: chain pod fcall to nowy Post o treści Subscript."""
    src = (
        "definicja Postu:\n    treść (Tekst)\n"
        "definicja Autora:\n    lista_postów (Tekst)\n"
        "aby policz_index od liczby:\n    zwrócić\n"
        "aby działać:\n"
        "    lista_postów autora pod policz_index od liczby "
        "to nowy Post o treści lista_treści pod indeksem\n"
    )
    m = parse(src)
    asn = m.body[3].body[0]
    assert isinstance(asn, ast.Assignment)
    # LHS: Subscript(GetterChain(lista_postów, autor), FCall(policz_index, [liczba]))
    lhs = asn.target.resolved
    assert isinstance(lhs, ast.Subscript)
    assert isinstance(lhs.target, ast.GetterChain)
    assert len(lhs.target.chain) == 2
    assert isinstance(lhs.index, ast.FunctionCall)
    # RHS: StructCreation(Post, [(treść, Subscript(lista_treści, indeksem))])
    rhs = asn.value.resolved
    assert isinstance(rhs, ast.StructCreation)
    assert rhs.type_name == ("Post",)
    assert len(rhs.args) == 1
    assert rhs.args[0].field_name == (("treść",), "sg", "f")
    assert isinstance(rhs.args[0].value, ast.Subscript)


def test_subscript_missing_right_operand(parse):
    """`lista pod` (bez indeksu) → ResolveError."""
    with pytest.raises(ast.ResolveError):
        parse(_wrap("lista pod"))


# ---------- For (foreach) ----------

def test_for_basic(parse):
    """`dla użytkownika w liście:` — podstawowa pętla."""
    src = (
        "aby działać:\n"
        "    dla użytkownika w liście:\n"
        "        wynik to użytkownik\n"
    )
    m = parse(src)
    for_node = m.body[0].body[0]
    assert isinstance(for_node, ast.For)
    assert isinstance(for_node.var, ast.Identifier)
    assert ("użytkownik",) in for_node.var.lemmas_set
    # collection: Phrase z resolved=Identifier(lista)
    assert ("lista",) in for_node.collection.resolved.lemmas_set
    assert len(for_node.body) == 1


def test_for_var_multiseg_adj_subst(parse):
    """Var w foreach traktowany jak każdy identyfikator: adj+subst.
    `wielkiego_użytkownika` (gen sg masc) → segments ('wielki', 'użytkownik')."""
    src = (
        "aby działać:\n"
        "    dla wielkiego_użytkownika w liście:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[0].body[0]
    assert isinstance(for_node, ast.For)
    assert ("wielki", "użytkownik") in for_node.var.lemmas_set


def test_for_body_with_stop(parse):
    """Body może zawierać `stop` (break)."""
    src = (
        "aby działać:\n"
        "    dla x w liście:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[0].body[0]
    assert isinstance(for_node, ast.For)
    assert len(for_node.body) == 1
    assert isinstance(for_node.body[0], ast.Break)


def test_for_nested(parse):
    """Zagnieżdżone foreach."""
    src = (
        "aby wypisać x:\n    zwrócić\n"
        "aby działać:\n"
        "    dla x w listy:\n"
        "        dla y w x:\n"
        "            wypisz y\n"
    )
    m = parse(src)
    outer = m.body[1].body[0]
    assert isinstance(outer, ast.For)
    assert ("x",) in outer.var.lemmas_set
    inner = outer.body[0]
    assert isinstance(inner, ast.For)
    assert ("y",) in inner.var.lemmas_set
    # Inner collection refers to outer var
    assert ("x",) in inner.collection.resolved.lemmas_set


def test_for_collection_is_subscript(parse):
    """Złożona kolekcja: subscript `lista pod jeden`."""
    src = (
        "aby działać:\n"
        "    dla x w lista pod jeden:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[0].body[0]
    assert isinstance(for_node, ast.For)
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.Subscript)
    assert ("lista",) in coll.target.lemmas_set
    assert coll.index == ast.IntLit(1)


def test_for_collection_is_function_call(parse):
    """Złożona kolekcja: function call."""
    src = (
        "aby weź_listę dla nazwy:\n    zwrócić\n"
        "aby działać:\n"
        "    dla element w weź_listę dla nazwy:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[1].body[0]
    assert isinstance(for_node, ast.For)
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.FunctionCall)
    assert ("wziąć", "lista") in coll.name.lemmas_set
    assert len(coll.params) == 1


def test_for_collection_is_getter_chain(parse):
    """Złożona kolekcja: getter chain `lista_postów autora`."""
    src = (
        "definicja Autora:\n    lista_postów (Tekst)\n"
        "aby działać:\n"
        "    dla post w liście_postów autora:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[1].body[0]
    assert isinstance(for_node, ast.For)
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.GetterChain)
    assert len(coll.chain) == 2


def test_for_collection_composite_subscript_on_fcall(parse):
    """Bardzo złożone: subscript po fcall (`weź_listę dla nazwy pod jeden`)."""
    src = (
        "aby weź_listę dla nazwy:\n    zwrócić\n"
        "aby działać:\n"
        "    dla x w weź_listę dla nazwy pod jeden:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[1].body[0]
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.Subscript)
    assert isinstance(coll.target, ast.FunctionCall)
    assert coll.index == ast.IntLit(1)


def test_for_collection_chain_with_subscript_index(parse):
    """Subscript z chainem jako indeksem w kolekcji."""
    src = (
        "definicja Wpisu:\n    numer (Liczba)\n"
        "aby działać:\n"
        "    dla x w lista pod numerem autora:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[1].body[0]
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.Subscript)
    assert ("lista",) in coll.target.lemmas_set
    assert isinstance(coll.index, ast.GetterChain)


def test_for_collection_with_arith(parse):
    """Kolekcja z arytmetyką: `lista pod (indeksem plus jeden)`."""
    src = (
        "aby działać:\n"
        "    dla x w lista pod (indeksem plus jeden):\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[0].body[0]
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.Subscript)
    assert isinstance(coll.index, ast.BinOp) and coll.index.op == "+"


def test_for_dla_as_prep_in_fcall_unchanged(parse):
    """`dla` jako prep w argumencie fcall (NIE jako start statementu) pozostaje
    przyimkiem. RHS przypisania `wynik to weź_wiek dla użytkownika` parsuje się
    jako FunctionCall(weź_wiek, [Word(dla, użytkownik)]) — bez foreach."""
    src = (
        "aby weź_wiek dla użytkownika:\n    zwrócić\n"
        "aby działać:\n"
        "    wynik to weź_wiek dla użytkownika\n"
    )
    m = parse(src)
    asn = m.body[1].body[0]
    assert isinstance(asn, ast.Assignment)
    rhs = asn.value.resolved
    assert isinstance(rhs, ast.FunctionCall)
    assert rhs.params[0].prep == ("dla",)


def test_for_dla_as_prep_in_collection(parse):
    """`dla` jako prep wewnątrz wyrażenia kolekcji (po `w`) — działa
    normalnie jako prep, bo to wewnątrz phrase."""
    src = (
        "aby weź_listę dla nazwy:\n    zwrócić\n"
        "aby działać:\n"
        "    dla x w weź_listę dla nazwy:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[1].body[0]
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.FunctionCall)
    assert coll.params[0].prep == ("dla",)


def test_for_missing_w_raises(parse):
    """`dla X` bez `w` → SyntaxError."""
    src = (
        "aby działać:\n"
        "    dla x z lista:\n"
        "        stop\n"
    )
    with pytest.raises(SyntaxError):
        parse(src)


def test_for_missing_colon_raises(parse):
    """`dla X w Y` bez `:` → SyntaxError."""
    src = (
        "aby działać:\n"
        "    dla x w lista\n"
        "        stop\n"
    )
    with pytest.raises(SyntaxError):
        parse(src)


def test_for_var_referenced_in_body_by_segments(parse):
    """Zmienna zadeklarowana w gen (`użytkownika` po `dla`) jest tym samym
    identyfikatorem co `użytkownik` (nom) w body — match po segments."""
    src = (
        "aby działać:\n"
        "    dla użytkownika w lista:\n"
        "        nazwa to użytkownik\n"
    )
    m = parse(src)
    for_node = m.body[0].body[0]
    # Var: declared as 'użytkownika' (gen sg) → segments=("użytkownik",)
    assert ("użytkownik",) in for_node.var.lemmas_set
    # Body reference: 'użytkownik' (nom sg) → segments=("użytkownik",)
    body_ref = for_node.body[0].value.resolved
    assert isinstance(body_ref, ast.Identifier)
    assert body_ref.lemmas_set & for_node.var.lemmas_set  # wspólna lemma


def test_for_collection_with_logical_op(parse):
    """Kolekcja z logical op (jak każda phrase) — `lista_a lub lista_b`."""
    src = (
        "aby działać:\n"
        "    dla x w lista_a lub lista_b:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[0].body[0]
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.Or)


def test_struct_arg_field_name_disambiguated_by_case(parse):
    """Identyfikator pola identyczny w obu kontekstach — sprawdzamy że
    `o części_mowy` (loc sg) i `o trybie` (loc) trafiają w różne pola,
    każde z odrębnym pełnym kluczem (lemmas, number, gender)."""
    src = (
        "definicja Słowa:\n"
        "    część_mowy (Tekst)\n"
        "    tryb (Tekst)\n"
        "aby działać:\n"
        "    s to nowe Słowo o części_mowy \"v\" o trybie \"oznajmujący\"\n"
    )
    m = parse(src)
    sc = m.body[1].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assigned = {a.field_name for a in sc.args}
    assert (("część", "mowa"), "sg", "f") in assigned
    assert (("tryb",), "sg", "m") in assigned


# ---------- Scope-aware narrowing wariantów ----------

def test_narrow_to_module_scope_var(parse):
    """`lista` zadeklarowana na module-level; `liście` w foreach narrowed
    do wariantu `("lista",)` (loc sg). Inne lemmy wariantów `liście` (liść,
    liście-neutrum) NIE są w scope, więc są odfiltrowane."""
    src = (
        "lista to coś\n"
        "aby działać:\n"
        "    dla użytkownika w liście:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[1].body[0]
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.Identifier)
    # Po narrowingu: tylko `("lista",)` w lemmas_set (jedyny wariant w scope).
    assert coll.lemmas_set == frozenset({("lista",)})


def test_narrow_to_function_local_var(parse):
    """Var zadeklarowana lokalnie w funkcji — narrowing też działa."""
    src = (
        "aby działać:\n"
        "    lista to coś\n"
        "    dla użytkownika w liście:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[0].body[1]
    coll = for_node.collection.resolved
    assert coll.lemmas_set == frozenset({("lista",)})


def test_narrow_to_function_param(parse):
    """Var w scope poprzez parametr funkcji. Param `listy` ma scope-keys
    {(lista, pl, f), (lista, sg, f, gen), (list, pl, m)}. Reference `liście`
    ma scope-keys {(lista, sg, f), (list, sg, m), (liść, pl, m), (liście, sg, n)}.
    Po narrowing zostaje tylko (lista, sg, f) — pozostałe nie matchują scope
    pełnym kluczem (list pl m ≠ list sg m itp.)."""
    src = (
        "aby działać_dla listy:\n"
        "    dla użytkownika w liście:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[0].body[0]
    coll = for_node.collection.resolved
    assert ("lista",) in coll.lemmas_set
    assert ("list",) not in coll.lemmas_set  # (list, sg, m) ≠ (list, pl, m) w scope
    assert ("liść",) not in coll.lemmas_set
    assert ("liście",) not in coll.lemmas_set


def test_narrow_keeps_multiple_when_multiple_in_scope():
    """Gdy więcej niż jeden wariant pasuje do scope, narrowing zostawia
    WSZYSTKIE matchujące (NIE wybiera 'lepszego' heurystyką). Disambiguację
    zostawia późniejszemu kontekstowi (fcall slot, type checker)."""
    from expression import ExpressionParser, _Ctx, _Scope
    ident = ast.Identifier(
        surface=("test",),
        analyses=(),
        variants=(
            ast.Variant(("a",), frozenset({"nom"}), "sg", "f", 0),
            ast.Variant(("b",), frozenset({"nom", "gen"}), "sg", "f", 0),
            ast.Variant(("c",), frozenset({"nom", "acc", "dat"}), "sg", "f", 0),
        ),
    )
    scope = _Scope()
    scope.variables = {
        (("a",), "sg", "f"),
        (("b",), "sg", "f"),
    }  # `c` NIE w scope
    ctx = _Ctx(function_defs={}, types=set(), fields_by_type={}, field_lemmas=set())
    parser = ExpressionParser(tokens=[], ctx=ctx, preps={}, scope=scope)
    narrowed = parser._narrow_to_variable(ident)
    seg_options = {v.lemmas for v in narrowed.variants}
    assert ("a",) in seg_options
    assert ("b",) in seg_options
    assert ("c",) not in seg_options  # odfiltrowane bo nie w scope


def test_no_narrowing_when_var_not_in_scope(parse):
    """Gdy odpowiednia zmienna nie jest zadeklarowana, narrowing jest no-op
    — zostają wszystkie warianty oryginalnego identyfikatora."""
    src = (
        "aby działać:\n"
        "    dla x w liście:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[0].body[0]
    coll = for_node.collection.resolved
    # Brak `lista`/`liść`/`liście` w scope → narrowing no-op, wszystkie warianty.
    assert ("lista",) in coll.lemmas_set
    assert ("liść",) in coll.lemmas_set
    assert ("liście",) in coll.lemmas_set


def test_for_var_visible_in_nested_collection(parse):
    """For-var widoczna w body inner-for (jako enclosing scope dla inner's
    collection). `dla y w x:` w outer-for body — `x` widoczne."""
    src = (
        "aby działać:\n"
        "    dla x w listy:\n"
        "        dla y w x:\n"
        "            stop\n"
    )
    m = parse(src)
    outer = m.body[0].body[0]
    inner = outer.body[0]
    # Inner collection: `x` (atom) resolved jako reference do outer for-var.
    coll = inner.collection.resolved
    assert isinstance(coll, ast.Identifier)
    assert ("x",) in coll.lemmas_set


def test_for_body_assignment_leaks_to_outer(parse):
    """Body for'a może mutować zmienne z outer scope (Python-like).
    `znalezione` zadeklarowane przed pętlą — przypisanie w body referuje
    OUTER `znalezione`, nie tworzy for-lokalnej kopii."""
    src = (
        "aby działać:\n"
        "    znaleziony to pusta\n"
        "    dla x w lista:\n"
        "        znaleziony to x\n"
        "    wynik to znaleziony\n"
    )
    m = parse(src)
    fn_body = m.body[0].body
    # body[0] = znaleziony to pusta
    # body[1] = for x in lista
    # body[2] = wynik to znaleziony
    znaleziony_ref = fn_body[2].value.resolved
    assert isinstance(znaleziony_ref, ast.Identifier)
    assert ("znaleziony",) in znaleziony_ref.lemmas_set


def test_field_write_does_not_register_as_var(parse):
    """Chain LHS (`autor postu to "X"`) jest field write — `autor` NIE staje
    się zadeklarowaną zmienną. Późniejsze użycie `autor postu` dalej resolwuje
    jako chain (field interpretation)."""
    src = (
        "definicja Postu:\n    autor (Tekst)\n"
        "aby działać:\n"
        "    autor postu to \"X\"\n"
        "    wynik to autor postu\n"
    )
    m = parse(src)
    fn_body = m.body[1].body
    # Drugie wystąpienie autor postu jako chain.
    chain = fn_body[1].value.resolved
    assert isinstance(chain, ast.GetterChain)


def test_field_lemmas_filtered_by_nom(parse):
    """Pole zadeklarowane `lista` (nom sg). Tylko wariant z nom (= ("lista",))
    trafia do field_names. Wariant ("lista",) z innym case'm nie istnieje
    (lista nom-only), ale dla wielowariantowych pól (jak `liście`) filtr
    odrzuca warianty bez nom."""
    src = (
        "definicja Boxu:\n    lista (Tekst)\n"
        "aby działać:\n    wartość to lista pudełka\n"
    )
    m = parse(src)
    chain = m.body[1].body[0].value.resolved
    assert isinstance(chain, ast.GetterChain)
    assert ("lista",) in chain.chain[0].lemmas_set


def test_find_in_set_ambiguity_error():
    """Gdy `_find_in_set` po filtrach ma > 1 matchów — ResolveError.
    Test syntetyczny: konstruujemy Identifier z dwoma matchującymi
    wariantami i sprawdzamy że error się rzuca."""
    # Konstrukcja ręczna identyfikatora z dwoma wariantami pasującymi do
    # target_set bez `required_case` (rzadko spotykane w praktyce, ale możliwe).
    from expression import ExpressionParser, _Ctx, _Scope
    target_set = {("a",), ("b",)}
    ident = ast.Identifier(
        surface=("x",),
        analyses=(),
        variants=(
            ast.Variant(("a",), frozenset({"nom"}), "sg", "f", 0),
            ast.Variant(("b",), frozenset({"nom"}), "sg", "f", 0),
        ),
    )
    ctx = _Ctx(function_defs={}, types=set(), fields_by_type={}, field_lemmas=target_set)
    parser = ExpressionParser(tokens=[], ctx=ctx, preps={}, scope=_Scope())
    with pytest.raises(ast.ResolveError, match="niejednoznaczny"):
        parser._find_in_set(ident, target_set)


def test_field_canonical_lemma_picks_min_rest_for_adj_noun(parse):
    """Pole `pierwsze_pole` ma kilka wariantów morfologicznych:
    [adj `pierwszy` + subst `pole`] (rest=0) oraz [subst `pierwsze`/`pierwsza`/
    `pierwszy:S` + rest `pole`] (rest=1). Kanoniczna forma to (pierwszy, pole)
    z rest=0. Następnie użycie `o pierwszym polu` (loc) musi się rozwiązać
    do tego samego pola — adj+subst (rest=0) bije gałąź subst+rest (rest=1)
    nawet gdy obie dają `segs=(pierwszy, pole)`."""
    src = (
        "definicja Struktury:\n"
        "    pierwsze_pole (Tekst)\n"
        "    drugie_pole (Tekst)\n"
        "aby działać:\n"
        "    s to nowa Struktura o pierwszym_polu \"v\"\n"
    )
    m = parse(src)
    sc = m.body[1].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assert len(sc.args) == 1
    assert sc.args[0].field_name == (("pierwszy", "pole"), "sg", "n")


def test_field_canonical_lemma_ambiguous_after_min_rest():
    """Gdy po filtrze `nom` + min-rest wciąż zostaje >1 unikalnych segs,
    `_field_canonical_lemma` rzuca ResolveError z listą opcji.
    Test syntetyczny: konstruujemy Identifier z dwoma wariantami w nom
    o tej samej długości reszty (rest=0) i różnych segs."""
    from expression import _field_canonical_lemma
    field_name = ast.Identifier(
        surface=("foo",),
        analyses=(),
        variants=(
            ast.Variant(("a",), frozenset({"nom"}), "sg", "f", 0),
            ast.Variant(("b",), frozenset({"nom"}), "sg", "f", 0),
        ),
    )
    with pytest.raises(ast.ResolveError, match="niejednoznaczna"):
        _field_canonical_lemma(field_name)


def test_field_canonical_lemma_requires_nom():
    """Deklaracja pola w formie innej niż nom (np. tylko gen/dat) → ResolveError."""
    from expression import _field_canonical_lemma
    field_name = ast.Identifier(
        surface=("foo",),
        analyses=(),
        variants=(
            ast.Variant(("foo",), frozenset({"gen", "dat"}), "sg", "f", 0),
        ),
    )
    with pytest.raises(ast.ResolveError, match="mianownik"):
        _field_canonical_lemma(field_name)


def test_strlit_carries_unescaped_value(parse):
    """End-to-end: lexer rozwija escape'y, parser opakowuje w StrLit. Wartość
    StrLit zawiera prawdziwe znaki kontrolne (newline, tab), nie literalne
    sekwencje backslash."""
    src = 'aby działać:\n    x to "linia\\nkolumna\\ttab"\n'
    m = parse(src)
    asn = m.body[0].body[0]
    assert isinstance(asn, ast.Assignment)
    assert asn.value.resolved == ast.StrLit("linia\nkolumna\ttab")


# ---------- Sufiks typu (type annotation) ----------

_TYPE_PREAMBLE = (
    "definicja Tekstu:\n    znak (Tekst)\n"
    "definicja Liczby:\n    wartość (Liczba)\n"
)


def test_type_suffix_on_str_lit(parse):
    src = _TYPE_PREAMBLE + 'aby działać:\n    wynik to "abc" (Tekst)\n'
    m = parse(src)
    val = m.body[2].body[0].value.resolved
    assert val == ast.Typed(expr=ast.StrLit("abc"), type=("Tekst",), line=val.line)


def test_type_suffix_on_int_lit(parse):
    src = _TYPE_PREAMBLE + "aby działać:\n    wynik to pięć (Liczba)\n"
    m = parse(src)
    val = m.body[2].body[0].value.resolved
    assert isinstance(val, ast.Typed)
    assert val.type == ("Liczba",)
    assert val.expr == ast.IntLit(5)


def test_type_suffix_on_identifier(parse):
    src = (
        _TYPE_PREAMBLE
        + 'aby działać:\n    zmienna to "abc"\n    wynik to zmienna (Tekst)\n'
    )
    m = parse(src)
    val = m.body[2].body[1].value.resolved
    assert isinstance(val, ast.Typed)
    assert val.type == ("Tekst",)
    assert isinstance(val.expr, ast.Identifier)
    assert ("zmienna",) in val.expr.lemmas_set


def test_type_suffix_on_lhs_assignment(parse):
    src = _TYPE_PREAMBLE + 'aby działać:\n    wynik (Tekst) to "abc"\n'
    m = parse(src)
    asn = m.body[2].body[0]
    target = asn.target.resolved
    assert isinstance(target, ast.Typed)
    assert target.type == ("Tekst",)
    assert isinstance(target.expr, ast.Identifier)
    assert ("wynik",) in target.expr.lemmas_set
    assert asn.value.resolved == ast.StrLit("abc")


def test_type_suffix_on_both_sides(parse):
    src = (
        _TYPE_PREAMBLE
        + 'aby działać:\n    zmienna to "abc"\n'
        + "    wynik (Tekst) to zmienna (Tekst)\n"
    )
    m = parse(src)
    asn = m.body[2].body[1]
    assert isinstance(asn.target.resolved, ast.Typed)
    assert asn.target.resolved.type == ("Tekst",)
    assert isinstance(asn.value.resolved, ast.Typed)
    assert asn.value.resolved.type == ("Tekst",)


def test_type_suffix_binds_to_atom_not_call(parse):
    """`f od x (Tekst)` → Typed otacza `x` (atom argumentu), nie cały fcall."""
    src = (
        _TYPE_PREAMBLE
        + "można wziąć od x (Tekst) -> Tekst\n"
        + 'aby działać:\n    x to "abc"\n    wynik to weź od x (Tekst)\n'
    )
    m = parse(src)
    val = m.body[3].body[1].value.resolved
    assert isinstance(val, ast.FunctionCall)
    assert len(val.params) == 1
    arg_value = val.params[0].value
    assert isinstance(arg_value, ast.Typed)
    assert arg_value.type == ("Tekst",)


def test_type_suffix_on_parens_expr_wraps_whole(parse):
    """`(f od x) (Tekst)` → Typed otacza cały FunctionCall."""
    src = (
        _TYPE_PREAMBLE
        + "można wziąć od x (Tekst) -> Tekst\n"
        + 'aby działać:\n    x to "abc"\n    wynik to (weź od x) (Tekst)\n'
    )
    m = parse(src)
    val = m.body[3].body[1].value.resolved
    assert isinstance(val, ast.Typed)
    assert val.type == ("Tekst",)
    assert isinstance(val.expr, ast.FunctionCall)


def test_type_suffix_on_subscript_index(parse):
    """`lista pod indeksem (Liczba)` → Subscript(lista, Typed(indeksem, Liczba))."""
    src = (
        _TYPE_PREAMBLE
        + 'aby działać:\n    lista to "x"\n    indeks to "y"\n'
        + "    wynik to lista pod indeksem (Liczba)\n"
    )
    m = parse(src)
    val = m.body[2].body[2].value.resolved
    assert isinstance(val, ast.Subscript)
    assert isinstance(val.index, ast.Typed)
    assert val.index.type == ("Liczba",)
    assert isinstance(val.index.expr, ast.Identifier)
    assert ("indeks",) in val.index.expr.lemmas_set


def test_type_suffix_on_subscript_target_requires_parens(parse):
    """`(lista pod indeksem) (Liczba)` → Typed(Subscript(...), Liczba)."""
    src = (
        _TYPE_PREAMBLE
        + 'aby działać:\n    lista to "x"\n    indeks to "y"\n'
        + "    wynik to (lista pod indeksem) (Liczba)\n"
    )
    m = parse(src)
    val = m.body[2].body[2].value.resolved
    assert isinstance(val, ast.Typed)
    assert val.type == ("Liczba",)
    assert isinstance(val.expr, ast.Subscript)


def test_type_suffix_on_getter_chain(parse):
    """`autor postu (Tekst)` → Typed(GetterChain([...]), Tekst)."""
    src = (
        _TYPE_PREAMBLE
        + "definicja Postu:\n    autor (Tekst)\n"
        + "aby działać:\n    wynik to autor postu (Tekst)\n"
    )
    m = parse(src)
    val = m.body[3].body[0].value.resolved
    assert isinstance(val, ast.Typed)
    assert val.type == ("Tekst",)
    assert isinstance(val.expr, ast.GetterChain)


def test_type_suffix_unknown_type_errors(parse):
    src = _TYPE_PREAMBLE + 'aby działać:\n    wynik to "abc" (Bzdura)\n'
    with pytest.raises(ast.ResolveError) as exc:
        parse(src)
    assert "nieznanego typu" in str(exc.value)
    assert "Bzdura" in str(exc.value)
    assert "Tekst" in str(exc.value)  # znane typy w hincie


def test_lowercase_paren_word_not_type_suffix(parse):
    """`"abc" (jakiś)` — lowercase WORD w nawiasach nie konsumowany jako
    sufiks-typ. Następnie outer parser rzuca leftover error."""
    src = _TYPE_PREAMBLE + 'aby działać:\n    wynik to "abc" (jakiś)\n'
    with pytest.raises(ast.ResolveError) as exc:
        parse(src)
    # leftover-diagnostic dla literału, nie type_suffix
    assert "type_suffix" not in str(exc.value)


def test_type_suffix_multi_segment_type(parse):
    """Multi-segment typ canonicalizuje się do tuple wielu lemm."""
    src = (
        _TYPE_PREAMBLE
        + "definicja Numeru_Telefonu:\n    cyfra (Liczba)\n"
        + 'aby działać:\n    wynik to "x" (Numer_Telefon)\n'
    )
    m = parse(src)
    val = m.body[3].body[0].value.resolved
    assert isinstance(val, ast.Typed)
    assert val.type == ("Numer", "Telefon")


def test_type_suffix_pretty_print(parse, capsys):
    """Golden snapshot: Typed renderuje się jako `Typed : <typ>` z child."""
    import pretty
    src = _TYPE_PREAMBLE + 'aby działać:\n    wynik to "abc" (Tekst)\n'
    m = parse(src)
    pretty.pretty(m.body[2].body[0].value.resolved)
    out = capsys.readouterr().out
    assert "Typed : Tekst" in out
    assert "StrLit 'abc'" in out


def test_parens_grouping_regression(parse):
    """Regression: `(dwa plus trzy) razy cztery` nadal produkuje BinOp,
    nie zostaje owinięty w Typed (bo `razy` to nie LPAREN po grupowaniu)."""
    expr = _value_of_first_assignment(parse(_wrap("(dwa plus trzy) razy cztery")))
    assert expr == ast.BinOp(
        "*", ast.BinOp("+", ast.IntLit(2), ast.IntLit(3)), ast.IntLit(4)
    )
