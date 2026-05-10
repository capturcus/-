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
    assert expr.operand.segments == ("inny", "zmienny")


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
    assert fc.name.segments == ("pisać",)
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
    assert fc.name.segments == ("wywołać", "funkcja")
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
    assert expr.left.name.segments == ("wziąć", "wiek", "z", "baza")
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
    assert chain.chain[0].segments == ("autor",)
    assert chain.chain[1].segments == ("post",)


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
    assert sc.type_name == ("użytkownik",)
    assert len(sc.args) == 1
    assert sc.args[0].field_name == ("nazwa",)
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
    wiek_arg = next(a for a in sc.args if a.field_name == ("wiek",))
    assert isinstance(wiek_arg.value, ast.BinOp) and wiek_arg.value.op == "+"
    assert isinstance(wiek_arg.value.left, ast.FunctionCall)
    assert wiek_arg.value.right == ast.IntLit(7)
    # Drugie — nazwa = "Anna"
    nazwa_arg = next(a for a in sc.args if a.field_name == ("nazwa",))
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
    assert {a.field_name for a in sc.args} == {("nazwa",), ("wiek",)}


# ---------- Identifier reference ----------

def test_bare_identifier_single_letter(parse):
    src = "aby działać:\n    x to y\n"
    m = parse(src)
    expr = m.body[0].body[0].value.resolved
    assert isinstance(expr, ast.Identifier)
    assert expr.segments == ("y",)


def test_bare_identifier_multiseg_no_verb(parse):
    """Multi-segment bez czasownika → identifier_ref (nie próba fcall)."""
    src = "aby działać:\n    x to wielki_kot\n"
    m = parse(src)
    expr = m.body[0].body[0].value.resolved
    assert isinstance(expr, ast.Identifier)
    assert expr.segments == ("wielki", "kot")


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
    assert fc.name.segments == ("pisać",)


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
    seg_options = {segs for segs, _ in ident.variants}
    assert ("część", "mowa") in seg_options
    assert ("częsty", "mowa") in seg_options


def test_default_segments_pick_largest_case_set(db):
    """Tiebreak: domyślne `Identifier.segments` to wariant z największym
    case-set (subst-prefix `("część","mowa")` ma case={gen,dat,loc,nom,acc,voc},
    adj-prefix `("częsty","mowa")` ma case={nom,voc})."""
    ident = _make_ident(db, "części_mowy")
    assert ident.segments == ("część", "mowa")
    # Sanity: union case = wszystkie z obu wariantów
    assert "gen" in ident.case
    assert "loc" in ident.case
    assert "nom" in ident.case


def test_single_variant_when_no_ambiguity(db):
    """`część` w nominativie ma TYLKO subst reading (brak adj `częsty:nom:f`)
    — Identifier ma tylko 1 wariant."""
    ident = _make_ident(db, "część")
    assert len(ident.variants) == 1
    segs, case = ident.variants[0]
    assert segs == ("część",)


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
    seg_options = {segs for segs, _ in head.variants}
    assert ("część", "mowa") in seg_options
    assert ("częsty", "mowa") in seg_options


def test_struct_arg_loc_picks_subst_variant(parse):
    """`nowe Słowo o częściach_mowy ...` — dispatcher struct arg wymaga loc.
    Subst-prefix `("część","mowa")` ma loc w {dat,loc} pl, adj-prefix
    `("częsty","mowa")` nie ma loc. Wybierz subst-variant."""
    src = (
        "definicja Słowa:\n    część_mowy (Tekst)\n"
        "aby działać:\n    s to nowe Słowo o częściach_mowy \"czasownik\"\n"
    )
    m = parse(src)
    sc = m.body[1].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assert sc.type_name == ("słowo",)
    assert len(sc.args) == 1
    assert sc.args[0].field_name == ("część", "mowa")
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


def test_struct_arg_field_name_disambiguated_by_case(parse):
    """Identyfikator pola identyczny w obu kontekstach — sprawdzamy że
    `o trybie` (loc) i `o aspekcie` (loc) trafiają w różne pola, każde
    z odrębnym lematem subst-variant."""
    src = (
        "definicja Słowa:\n"
        "    część_mowy (Tekst)\n"
        "    tryb (Tekst)\n"
        "aby działać:\n"
        "    s to nowe Słowo o częściach_mowy \"v\" o trybie \"oznajmujący\"\n"
    )
    m = parse(src)
    sc = m.body[1].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assigned = {a.field_name for a in sc.args}
    assert ("część", "mowa") in assigned
    assert ("tryb",) in assigned
