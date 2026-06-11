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


# SGJP (db) i preps pochodzą ze współdzielonej fixturki w conftest.py.


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


def _wrap(rhs_expr, params=""):
    """Wzorzec: aby działać [PARAMS]:\n    wynik to <expr>.

    `params` deklaruje zmienne używane w wyrażeniu (block scoping wymaga
    deklaracji przed użyciem; parametry nie przesuwają indeksów w body)."""
    sig = f" {params}" if params else ""
    return f"aby działać{sig}:\n    wynik to {rhs_expr}\n"


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
    expr = _value_of_first_assignment(parse(_wrap("nie inna_zmienna", "inna_zmienna")))
    assert isinstance(expr, ast.Not)
    assert isinstance(expr.operand, ast.Identifier)
    assert ("inny", "zmienny") in expr.operand.lemmas_set


def test_not_lower_precedence_than_comparison(parse):
    # `nie dwa większe od trzy` → Not(BinOp(>, 2, 3))
    expr = _value_of_first_assignment(parse(_wrap("nie dwa większe od trzy")))
    assert isinstance(expr, ast.Not)
    assert isinstance(expr.operand, ast.BinOp) and expr.operand.op == ">"


def test_and(parse):
    expr = _value_of_first_assignment(parse(_wrap("warunek i inny_warunek", "warunek inny_warunek")))
    assert isinstance(expr, ast.And)
    assert isinstance(expr.left, ast.Identifier)
    assert isinstance(expr.right, ast.Identifier)


def test_or(parse):
    expr = _value_of_first_assignment(parse(_wrap("warunek lub inny_warunek", "warunek inny_warunek")))
    assert isinstance(expr, ast.Or)


def test_or_lower_precedence_than_and(parse):
    # `a i b lub c` → Or(And(a, b), c)
    expr = _value_of_first_assignment(parse(_wrap("p i q lub r", "p q r")))
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
        "aby działać identyfikator:\n    wynik to weź_wiek_z_bazy dla identyfikatora plus siedem\n"
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


# ---------- Dopasowanie argumentów do slotów (przypadek + przyimek) ----------
#
# `testować_funkcję` ma 3 parametry o ROZRÓŻNIALNYCH przypadkach:
#   1. `pierwszemu_argumentowi`  — celownik (dat), bez przyimka
#   2. `drugiego_argumentu`      — dopełniacz (gen), bez przyimka
#   3. `z trzecim_argumentem`    — przyimek `z` + narzędnik (inst)
# Dzięki temu argumenty można podać w dowolnej kolejności — fleksja je
# dezambiguuje. `stworzyć_wartość` / `też_stworzyć_wartość` to funkcje
# bezargumentowe używane jako argumenty zagnieżdżone (nie mają przypadku).

_ARGMATCH_DECLS = (
    "aby testować_funkcję pierwszemu_argumentowi drugiego_argumentu"
    " z trzecim_argumentem:\n    zwróć\n"
    "aby stworzyć_wartość:\n    zwróć jeden\n"
    "aby też_stworzyć_wartość:\n    zwróć dwa\n"
)


def _argmatch_call(parse, call_line):
    """Parsuje deklaracje + jedno wywołanie `testuj_funkcję ...` w ciele
    `działać`; zwraca rozwiązany FunctionCall (3 sloty w kolejności sygnatury)."""
    src = _ARGMATCH_DECLS + "aby działać domek samochód pies:\n    " + call_line + "\n"
    fc = parse(src).body[-1].body[0].resolved
    assert isinstance(fc, ast.FunctionCall)
    assert ("testować", "funkcja") in fc.name.lemmas_set
    assert len(fc.params) == 3
    return fc


def _is_ident(word, lemma):
    return isinstance(word.value, ast.Identifier) and lemma in word.value.lemmas_set


def _is_call(word, lemma):
    return (isinstance(word.value, ast.FunctionCall)
            and lemma in word.value.name.lemmas_set)


def test_args_in_signature_order(parse):
    """Argumenty w kolejności sygnatury: celownik / dopełniacz / `z` + narzędnik
    → `testuj_funkcję(domek, samochód, pies)`."""
    fc = _argmatch_call(parse, "testuj_funkcję domkowi samochodu z psem")
    assert _is_ident(fc.params[0], ("domek",))
    assert _is_ident(fc.params[1], ("samochód",))
    assert _is_ident(fc.params[2], ("pies",))
    assert fc.params[2].prep == ("z",)


def test_args_reordered_by_case_and_prep(parse):
    """Argumenty w INNEJ kolejności niż sygnatura — rozróżnione po przypadku
    i przyimku. `domku` (dopełniacz) → slot 2, `z psem` → slot 3,
    `samochodowi` (celownik) → slot 1 ⇒ `testuj_funkcję(samochód, domek, pies)`."""
    fc = _argmatch_call(parse, "testuj_funkcję domku z psem samochodowi")
    assert _is_ident(fc.params[0], ("samochód",))
    assert _is_ident(fc.params[1], ("domek",))
    assert _is_ident(fc.params[2], ("pies",))
    assert fc.params[2].prep == ("z",)


def test_nested_fcall_fills_remaining_slot_positionally(parse):
    """Wywołanie zagnieżdżone (`stwórz_wartość`) nie ma przypadku z fleksji.
    `samochodowi`→slot 1 (cel.), `z psem`→slot 3, więc `stwórz_wartość`
    trafia do jedynego wolnego slotu 2 ⇒
    `testuj_funkcję(samochód, stwórz_wartość(), pies)`."""
    fc = _argmatch_call(parse, "testuj_funkcję stwórz_wartość z psem samochodowi")
    assert _is_ident(fc.params[0], ("samochód",))
    assert _is_call(fc.params[1], ("stworzyć", "wartość"))
    assert _is_ident(fc.params[2], ("pies",))


def test_nested_fcall_with_prep_picks_slot_by_prep(parse):
    """Zagnieżdżone wywołanie poprzedzone przyimkiem dezambiguuje się PO
    PRZYIMKU mimo braku przypadku: `z stwórz_wartość`→slot 3 (`z`),
    `domku`→slot 2, `samochodowi`→slot 1 ⇒
    `testuj_funkcję(samochód, domek, stwórz_wartość())`."""
    fc = _argmatch_call(parse, "testuj_funkcję z stwórz_wartość domku samochodowi")
    assert _is_ident(fc.params[0], ("samochód",))
    assert _is_ident(fc.params[1], ("domek",))
    assert _is_call(fc.params[2], ("stworzyć", "wartość"))
    assert fc.params[2].prep == ("z",)


def test_indistinguishable_args_fall_back_to_positional(parse):
    """Poza jednoznacznie dopasowanym po przyimku (`z psem`→slot 3), dwa
    nierozróżnialne wywołania zagnieżdżone wpadają POZYCYJNIE w kolejności
    zapisu do wolnych slotów 1 i 2 ⇒
    `testuj_funkcję(stwórz_wartość(), też_stwórz_wartość(), pies)`."""
    fc = _argmatch_call(parse, "testuj_funkcję z psem stwórz_wartość też_stwórz_wartość")
    assert _is_call(fc.params[0], ("stworzyć", "wartość"))
    assert _is_call(fc.params[1], ("tenże", "stworzyć", "wartość"))
    assert _is_ident(fc.params[2], ("pies",))
    assert fc.params[2].prep == ("z",)


def test_missing_argument_fails(parse):
    """Wszystkie argumenty muszą być obecne — brak choćby jednego (tu 2 z 3)
    przerywa wywołanie błędem, niezależnie od dezambiguacji."""
    with pytest.raises(ast.ResolveError, match="3 argument"):
        _argmatch_call(parse, "testuj_funkcję domkowi z psem")


# ---------- Getter chain ----------

def test_simple_chain(parse):
    src = (
        "definicja Postu:\n    autor (Tekst)\n    treść (Tekst)\n"
        "aby działać post:\n    wynik to autor postu\n"
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
        "aby działać post:\n    wynik to liczba_polubień posta plus dwadzieścia osiem\n"
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
        "aby działać:\n    wynik to Użytkownik o nazwie \"Anna\"\n"
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
        "aby działać identyfikator:\n"
        "    wynik to Użytkownik o wieku weź_wiek_z_bazy dla identyfikatora plus siedem o nazwie \"Anna\"\n"
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
        "aby działać nazwa wiek:\n    u to Użytkownik z nazwą z wiekiem\n"
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
    src = "aby działać y:\n    x to y\n"
    m = parse(src)
    expr = m.body[0].body[0].value.resolved
    assert isinstance(expr, ast.Identifier)
    assert ("y",) in expr.lemmas_set


def test_bare_identifier_multiseg_no_verb(parse):
    """Multi-segment bez czasownika → identifier_ref (nie próba fcall)."""
    src = "aby działać wielki_kot:\n    x to wielki_kot\n"
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
        "aby działać słowo:\n    wynik to części_mowy słowa\n"
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
    """`Słowo o części_mowy ...` — dispatcher struct arg wymaga loc.
    Subst-prefix `("część","mowa")` ma loc, adj-prefix `("częsty","mowa")`
    nie ma loc. Wybierz subst-variant. (Field decl jest sg-f, więc reference
    też musi być sg dla pełnego klucza match.)"""
    src = (
        "definicja Słowa:\n    część_mowy (Tekst)\n"
        "aby działać:\n    s to Słowo o części_mowy \"czasownik\"\n"
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
        "aby działać:\n    p to Punkt o nazwie \"A\"\n"
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
        "aby działać post:\n    wynik to autor postu komentarza\n"
    )
    with pytest.raises(ast.ResolveError, match="chain.*autor postu") as ei:
        parse(src)
    msg = str(ei.value)
    assert "nie jest polem" in msg
    assert "komentarza" in msg


def test_undeclared_identifier_reference_raises(parse):
    """Block scoping: referencja do niezadeklarowanej zmiennej to błąd
    rezolucji (nie ciche tolerowanie jak dawniej)."""
    src = (
        "aby działać:\n    x to nieznana_zmienna posta\n"
    )
    with pytest.raises(ast.ResolveError) as ei:
        parse(src)
    msg = str(ei.value)
    assert "nieznana_zmienna" in msg
    assert "nie jest zadeklarowaną zmienną" in msg


def test_diag_leftover_after_struct_field_missing(parse):
    """`Punkt o nazwie ...` — pole `nazwa` nie istnieje w typie `Punkt`
    (dostępne tylko `x`). Diagnostyka mówi nazwę struct'a i listę dostępnych
    pól."""
    src = (
        "definicja Punktu:\n    x (Liczba)\n"
        "aby działać:\n    p to Punkt o nazwie \"A\"\n"
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


# ---------- For (foreach) ----------

def test_for_basic(parse):
    """`dla użytkownika w liście:` — podstawowa pętla."""
    src = (
        "aby działać lista:\n"
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
        "aby działać lista:\n"
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
        "aby działać lista:\n"
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
        "aby działać listy:\n"
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


def test_for_collection_is_function_call(parse):
    """Złożona kolekcja: function call."""
    src = (
        "aby weź_listę dla nazwy:\n    zwrócić\n"
        "aby działać nazwa:\n"
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
        "aby działać autor:\n"
        "    dla post w liście_postów autora:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[1].body[0]
    assert isinstance(for_node, ast.For)
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.GetterChain)
    assert len(coll.chain) == 2


def test_for_collection_with_arith(parse):
    """Kolekcja z arytmetyką: `weź_listę dla nazwy plus jeden` — pełna phrase."""
    src = (
        "aby weź_listę dla nazwy:\n    zwrócić\n"
        "aby działać nazwa:\n"
        "    dla x w weź_listę dla nazwy plus jeden:\n"
        "        stop\n"
    )
    m = parse(src)
    for_node = m.body[1].body[0]
    coll = for_node.collection.resolved
    assert isinstance(coll, ast.BinOp) and coll.op == "+"
    assert isinstance(coll.left, ast.FunctionCall)


def test_for_dla_as_prep_in_fcall_unchanged(parse):
    """`dla` jako prep w argumencie fcall (NIE jako start statementu) pozostaje
    przyimkiem. RHS przypisania `wynik to weź_wiek dla użytkownika` parsuje się
    jako FunctionCall(weź_wiek, [Word(dla, użytkownik)]) — bez foreach."""
    src = (
        "aby weź_wiek dla użytkownika:\n    zwrócić\n"
        "aby działać użytkownik:\n"
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
        "aby działać nazwa:\n"
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
        "aby działać lista:\n"
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
        "aby działać lista_a lista_b:\n"
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
        "    s to Słowo o części_mowy \"v\" o trybie \"oznajmujący\"\n"
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
        "lista to zero\n"
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
        "    lista to zero\n"
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


def test_undeclared_collection_raises(parse):
    """Block scoping: kolekcja pętli odwołująca się do niezadeklarowanej
    zmiennej to błąd rezolucji (dawniej: tolerowana, wszystkie warianty)."""
    src = (
        "aby działać:\n"
        "    dla x w liście:\n"
        "        stop\n"
    )
    with pytest.raises(ast.ResolveError, match="nie jest zadeklarowaną zmienną"):
        parse(src)


def test_for_var_visible_in_nested_collection(parse):
    """For-var widoczna w body inner-for (jako enclosing scope dla inner's
    collection). `dla y w x:` w outer-for body — `x` widoczne."""
    src = (
        "aby działać listy:\n"
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


def test_for_body_reassigns_outer_var(parse):
    """Przypisanie w body pętli do zmiennej zadeklarowanej PRZED pętlą to
    reasignacja zewnętrznej zmiennej (nie nowa, pętlowo-lokalna) — więc
    `znaleziony` jest widoczny po pętli."""
    src = (
        "aby działać lista:\n"
        "    znaleziony to zero\n"
        "    dla x w lista:\n"
        "        znaleziony to x\n"
        "    wynik to znaleziony\n"
    )
    m = parse(src)
    fn_body = m.body[0].body
    # body[0] = znaleziony to zero
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
        "aby działać post:\n"
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
        "aby działać pudełko:\n    wartość to lista pudełka\n"
    )
    m = parse(src)
    chain = m.body[1].body[0].value.resolved
    assert isinstance(chain, ast.GetterChain)
    assert ("lista",) in chain.chain[0].lemmas_set


def test_find_in_set_ambiguity_error():
    """Gdy `find_in_set` po filtrach ma > 1 matchów — ResolveError.
    Test syntetyczny: konstruujemy Identifier z dwoma matchującymi
    wariantami i sprawdzamy że error się rzuca."""
    # Konstrukcja ręczna identyfikatora z dwoma wariantami pasującymi do
    # target_set bez `required_case` (rzadko spotykane w praktyce, ale możliwe).
    from expression import find_in_set
    target_set = {("a",), ("b",)}
    ident = ast.Identifier(
        surface=("x",),
        analyses=(),
        variants=(
            ast.Variant(("a",), frozenset({"nom"}), "sg", "f", 0),
            ast.Variant(("b",), frozenset({"nom"}), "sg", "f", 0),
        ),
    )
    with pytest.raises(ast.ResolveError, match="niejednoznaczny"):
        find_in_set(ident, target_set)


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
        "    s to Struktura o pierwszym_polu \"v\"\n"
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
    assert isinstance(val, ast.Typed)
    assert val.expr == ast.StrLit("abc")
    assert val.type.head == ("Tekst",)
    assert val.type.head == ("Tekst",) and val.type.args == []


def test_type_suffix_on_int_lit(parse):
    src = _TYPE_PREAMBLE + "aby działać:\n    wynik to pięć (Liczba)\n"
    m = parse(src)
    val = m.body[2].body[0].value.resolved
    assert isinstance(val, ast.Typed)
    assert val.type.head == ("Liczba",)
    assert val.expr == ast.IntLit(5)


def test_type_suffix_on_identifier(parse):
    src = (
        _TYPE_PREAMBLE
        + 'aby działać:\n    zmienna to "abc"\n    wynik to zmienna (Tekst)\n'
    )
    m = parse(src)
    val = m.body[2].body[1].value.resolved
    assert isinstance(val, ast.Typed)
    assert val.type.head == ("Tekst",)
    assert isinstance(val.expr, ast.Identifier)
    assert ("zmienna",) in val.expr.lemmas_set


def test_type_suffix_on_lhs_assignment(parse):
    src = _TYPE_PREAMBLE + 'aby działać:\n    wynik (Tekst) to "abc"\n'
    m = parse(src)
    asn = m.body[2].body[0]
    target = asn.target.resolved
    assert isinstance(target, ast.Typed)
    assert target.type.head == ("Tekst",)
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
    assert asn.target.resolved.type.head == ("Tekst",)
    assert isinstance(asn.value.resolved, ast.Typed)
    assert asn.value.resolved.type.head == ("Tekst",)


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
    assert arg_value.type.head == ("Tekst",)


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
    assert val.type.head == ("Tekst",)
    assert isinstance(val.expr, ast.FunctionCall)


def test_type_suffix_on_getter_chain(parse):
    """`autor postu (Tekst)` → Typed(GetterChain([...]), Tekst)."""
    src = (
        _TYPE_PREAMBLE
        + "definicja Postu:\n    autor (Tekst)\n"
        + "aby działać post:\n    wynik to autor postu (Tekst)\n"
    )
    m = parse(src)
    val = m.body[3].body[0].value.resolved
    assert isinstance(val, ast.Typed)
    assert val.type.head == ("Tekst",)
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
    assert val.type.head == ("Numer", "Telefon")


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


# ---------- Typy parametryzowane (parser) ----------

def _struct_by_name(m, head):
    return next(n for n in m.body if isinstance(n, ast.StructDef) and n.name == head)


def test_param_struct_header_binders(parse):
    """Nagłówek `definicja Mapy z klucza na wartość:` — głowa w dopełniaczu,
    bindery po przyimkach w dowolnym przypadku (silnik parametrów funkcji)."""
    m = parse("definicja Mapy z klucza na wartość:\n    klucz (klucz)\n    wartość (wartość)\n")
    sd = _struct_by_name(m, ("Mapa",))
    assert [(p.prep, p.name.surface) for p in sd.params] == [
        (("z",), ("klucza",)), (("na",), ("wartość",))
    ]


def test_param_field_type_case_agnostic(parse):
    """Pole `następnik (Lista z elementem)` — `type` to goła głowa (typechecker),
    a `type` niesie argument bezprzypadkowo (`elementem` → lemma `element`)."""
    m = parse("definicja Listy z elementem:\n    wartość (element)\n    następnik (Lista z elementem)\n")
    sd = _struct_by_name(m, ("Lista",))
    nast = next(f for f in sd.fields if f.name.surface == ("następnik",))
    assert nast.type.head == ("Lista",)                      # głowa — czyta ją typechecker
    assert nast.type.head == ("Lista",)
    assert len(nast.type.args) == 1
    arg = nast.type.args[0]
    assert arg.prep == ("z",)
    assert arg.type.head == ("element",) and arg.type.args == []


def test_param_func_param_annotation(parse):
    """Parametr funkcji z typem parametryzowanym: `do kolejki (Lista z elementem)`."""
    m = parse(
        "definicja Listy z elementem:\n    wartość (element)\n"
        "aby dodać do kolejki (Lista z elementem) element:\n    zwróć element\n"
    )
    fn = next(n for n in m.body if isinstance(n, ast.FunctionDef))
    kolejka = fn.params[0]
    assert kolejka.prep == ("do",)
    assert kolejka.type.head == ("Lista",) and kolejka.type.head == ("Lista",)
    assert kolejka.type.args[0].type.head == ("element",)


def test_param_nested_type_annotation(parse):
    """Zagnieżdżony typ w adnotacji wyrażenia: `(Lista z (Mapa z klucza na wartość))`."""
    src = (
        "definicja Listy z elementem:\n    wartość (element)\n"
        "definicja Mapy z klucza na wartość:\n    klucz (klucz)\n    wartość (wartość)\n"
        "aby działać:\n    x (Lista z (Mapa z klucza na wartość)) to Lista\n"
    )
    m = parse(src)
    fn = next(n for n in m.body if isinstance(n, ast.FunctionDef))
    typed = fn.body[0].target.resolved
    assert isinstance(typed, ast.Typed)
    assert typed.type.head == ("Lista",)                     # głowa
    inner = typed.type.args[0].type               # zagnieżdżony Mapa
    assert inner.head == ("Mapa",)
    assert [a.prep for a in inner.args] == [("z",), ("na",)]


# =====================================================================
# Typy wariantowe — walidacja deklaracji unii (_build_ctx)
# =====================================================================

_UNION_BASE = (
    "definicja Błędu:\n"
    "    opis (Tekst)\n"
    "\n"
    "definicja Wyniku z elementem:\n"
    "    wynik (element)\n"
    "\n"
)


def test_union_registers_as_type(parse):
    # nazwa unii działa jako adnotacja typu (sufiks `(Rezultat)`)
    src = (
        _UNION_BASE
        + "Rezultat to Wynik albo Błąd\n"
        "\n"
        "aby działać:\n"
        "    rzecz (Rezultat) to Wynik o wyniku zero\n"
    )
    m = parse(src)
    typed = m.body[3].body[0].target.resolved
    assert isinstance(typed, ast.Typed)
    assert typed.type.head == ("Rezultat",)


def test_union_unknown_member_raises(parse):
    src = _UNION_BASE + "Rezultat to Wynik albo Zguba\n"
    with pytest.raises(ast.ResolveError, match="nie jest zdefiniowaną strukturą"):
        parse(src)


def test_union_builtin_member_raises(parse):
    src = _UNION_BASE + "Rezultat to Wynik albo Liczba\n"
    with pytest.raises(ast.ResolveError, match="nie jest zdefiniowaną strukturą"):
        parse(src)


def test_union_member_being_union_raises(parse):
    src = (
        _UNION_BASE
        + "definicja Pustki:\n    nic (Liczba)\n\n"
        "Rezultat to Wynik albo Błąd\n"
        "Wszystko to Rezultat albo Pustka\n"
    )
    with pytest.raises(ast.ResolveError, match="zagnieżdżanie unii"):
        parse(src)


def test_union_duplicate_member_raises(parse):
    src = _UNION_BASE + "Rezultat to Wynik albo Wynik\n"
    with pytest.raises(ast.ResolveError, match="powtórzony"):
        parse(src)


def test_union_declared_twice_raises(parse):
    src = (
        _UNION_BASE
        + "Rezultat to Wynik albo Błąd\n"
        "Rezultat to Błąd albo Wynik\n"
    )
    with pytest.raises(ast.ResolveError, match="dwukrotnie"):
        parse(src)


def test_union_name_colliding_with_struct_raises(parse):
    src = _UNION_BASE + "Błąd to Wynik albo Błąd\n"
    with pytest.raises(ast.ResolveError, match="koliduje"):
        parse(src)


def test_union_order_independent(parse):
    # unia może być zadeklarowana PRZED strukturami, które wymienia
    src = (
        "Rezultat to Wynik albo Błąd\n"
        "\n" + _UNION_BASE
    )
    m = parse(src)
    assert isinstance(m.body[0], ast.UnionDef)


def test_union_inside_function_body_raises(parse):
    src = (
        _UNION_BASE
        + "aby działać:\n"
        "    Rezultat to Wynik albo Błąd\n"
    )
    with pytest.raises(ast.ResolveError, match="poziomie modułu"):
        parse(src)


# =====================================================================
# Typy wariantowe — rezolucja dopasowania `X jest:` (match)
# =====================================================================

_MATCH_BASE = (
    _UNION_BASE
    + "Rezultat to Wynik albo Błąd\n"
    "\n"
)


def test_match_binds_branch_fields(parse):
    src = (
        _MATCH_BASE
        + "aby działać:\n"
        "    rezultat to Wynik o wyniku zero\n"
        "    rezultat jest:\n"
        "        Błędem z opisem:\n"
        "            x to opis\n"
        "        Wynikiem z wynikiem:\n"
        "            y to wynik\n"
    )
    m = parse(src)
    match = m.body[3].body[1]
    b_err, b_wyn = match.branches
    # pole związane → referencja w body rezolwuje się do Identifier
    x_value = b_err.body[0].value.resolved
    assert isinstance(x_value, ast.Identifier)
    assert ("opis",) in x_value.lemmas_set
    # identyfikator pola zawężony do jednego klucza (lemmas, number, gender)
    assert len({(v.lemmas, v.number, v.gender) for v in b_err.fields[0].variants}) == 1
    assert b_err.fields[0].variants[0].lemmas == ("opis",)
    assert isinstance(b_wyn.body[0].value.resolved, ast.Identifier)


def test_match_branch_unknown_struct_raises(parse):
    src = (
        _MATCH_BASE
        + "aby działać rezultat:\n"
        "    rezultat jest:\n"
        "        Zgubą z opisem:\n"
        "            x to jeden\n"
    )
    with pytest.raises(ast.ResolveError, match="nie jest zdefiniowaną strukturą"):
        parse(src)


def test_match_field_not_in_struct_raises(parse):
    src = (
        _MATCH_BASE
        + "aby działać rezultat:\n"
        "    rezultat jest:\n"
        "        Błędem z wynikiem:\n"
        "            x to jeden\n"
    )
    with pytest.raises(ast.ResolveError, match="nie pasuje do żadnego wolnego pola"):
        parse(src)


def test_match_field_requires_inst_raises(parse):
    # `z opis` — mianownik zamiast narzędnika
    src = (
        _MATCH_BASE
        + "aby działać rezultat:\n"
        "    rezultat jest:\n"
        "        Błędem z opis:\n"
        "            x to jeden\n"
    )
    with pytest.raises(ast.ResolveError, match="narzędnik"):
        parse(src)


def test_match_field_bound_twice_raises(parse):
    src = (
        _MATCH_BASE
        + "aby działać rezultat:\n"
        "    rezultat jest:\n"
        "        Błędem z opisem z opisem:\n"
        "            x to jeden\n"
    )
    with pytest.raises(ast.ResolveError, match="nie pasuje do żadnego wolnego pola"):
        parse(src)


def test_match_branch_assignment_not_visible_after(parse):
    """Block scoping: zmienna zadeklarowana w gałęzi dopasowania `jest:` jest
    lokalna dla gałęzi — użycie po matchu to błąd rezolucji."""
    src = (
        _MATCH_BASE
        + "aby działać rezultat:\n"
        "    rezultat jest:\n"
        "        Błędem z opisem:\n"
        "            x to jeden\n"
        "        Wynikiem z wynikiem:\n"
        "            x to dwa\n"
        "    y to x\n"
    )
    with pytest.raises(ast.ResolveError, match="nie jest zadeklarowaną zmienną"):
        parse(src)


# =====================================================================
# Block scoping — zmienna widoczna od przypisania do końca bloku
# =====================================================================


def test_use_before_assignment_raises(parse):
    src = (
        "aby działać:\n"
        "    wynik to licznik\n"
        "    licznik to pięć\n"
    )
    with pytest.raises(ast.ResolveError, match="nie jest zadeklarowaną zmienną"):
        parse(src)


def test_self_referential_first_assignment_raises(parse):
    # RHS rezolwowany przed deklaracją LHS — `rzecz to rzecz` bez
    # wcześniejszej `rzeczy` to użycie przed przypisaniem
    src = "aby działać:\n    rzecz to rzecz\n"
    with pytest.raises(ast.ResolveError, match="nie jest zadeklarowaną zmienną"):
        parse(src)


def test_module_level_use_before_assignment_raises(parse):
    src = (
        "wynik to rzecz\n"
        "rzecz to pięć\n"
    )
    with pytest.raises(ast.ResolveError, match="nie jest zadeklarowaną zmienną"):
        parse(src)


def test_if_branch_assignment_not_visible_after(parse):
    src = (
        "aby działać flaga:\n"
        "    jeśli flaga równe jeden:\n"
        "        licznik to pięć\n"
        "    wynik to licznik\n"
    )
    with pytest.raises(ast.ResolveError, match="nie jest zadeklarowaną zmienną"):
        parse(src)


def test_then_assignment_not_visible_in_else(parse):
    src = (
        "aby działać flaga:\n"
        "    jeśli flaga równe jeden:\n"
        "        licznik to pięć\n"
        "    inaczej:\n"
        "        wynik to licznik\n"
    )
    with pytest.raises(ast.ResolveError, match="nie jest zadeklarowaną zmienną"):
        parse(src)


def test_while_body_assignment_not_visible_after(parse):
    src = (
        "aby działać flaga:\n"
        "    dopóki flaga równe jeden:\n"
        "        licznik to pięć\n"
        "    wynik to licznik\n"
    )
    with pytest.raises(ast.ResolveError, match="nie jest zadeklarowaną zmienną"):
        parse(src)


def test_for_var_not_visible_after_loop(parse):
    src = (
        "aby działać lista:\n"
        "    dla element w liście:\n"
        "        stop\n"
        "    wynik to element\n"
    )
    with pytest.raises(ast.ResolveError, match="nie jest zadeklarowaną zmienną"):
        parse(src)


def test_branch_reassigns_outer_var(parse):
    """Zmienna zadeklarowana PRZED blokiem — przypisanie w gałęzi to
    reasignacja zewnętrznej zmiennej, więc jest widoczna po bloku."""
    src = (
        "aby działać flaga:\n"
        "    licznik to zero\n"
        "    jeśli flaga równe jeden:\n"
        "        licznik to pięć\n"
        "    inaczej:\n"
        "        licznik to dziesięć\n"
        "    wynik to licznik\n"
    )
    m = parse(src)
    ref = m.body[0].body[2].value.resolved
    assert isinstance(ref, ast.Identifier)
    assert ("licznik",) in ref.lemmas_set


def test_same_name_independent_in_sibling_branches(parse):
    """Ta sama nazwa zadeklarowana niezależnie w `then` i `else` — dwie
    lokalne zmienne, żadna nie wycieka."""
    src = (
        "aby działać flaga:\n"
        "    jeśli flaga równe jeden:\n"
        "        rzecz to pięć\n"
        "        wynik to rzecz\n"
        "    inaczej:\n"
        "        rzecz to \"tekst\"\n"
        "        słowo to rzecz\n"
    )
    parse(src)  # bez błędu


def test_chain_base_must_be_declared(parse):
    src = (
        "definicja Postu:\n    autor (Tekst)\n"
        "aby działać:\n    wynik to autor postu\n"
    )
    with pytest.raises(ast.ResolveError, match="podstawa łańcucha"):
        parse(src)


def test_struct_shorthand_requires_declared_var(parse):
    src = (
        "definicja Użytkownika:\n    nazwa (Tekst)\n"
        "aby działać:\n    u to Użytkownik z nazwą\n"
    )
    with pytest.raises(ast.ResolveError, match="wymaga zadeklarowanej zmiennej"):
        parse(src)


# =====================================================================
# Konstruktor po wielkiej literze (bez słowa kluczowego `nowy`)
# =====================================================================


def test_struct_creation_without_keyword(parse):
    """Konstrukcja struktury to sama nazwa typu — bez `nowy`."""
    src = (
        "definicja Użytkownika:\n    nazwa (Tekst)\n"
        "aby działać:\n    u to Użytkownik o nazwie \"Anna\"\n"
    )
    m = parse(src)
    sc = m.body[1].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assert sc.type_name == ("Użytkownik",)
    assert len(sc.args) == 1


def test_nowy_is_ordinary_word(parse):
    """`nowy` to zwykłe słowo — może być zmienną."""
    src = (
        "aby działać:\n"
        "    nowy to pięć\n"
        "    wynik to nowy plus jeden\n"
    )
    m = parse(src)
    expr = m.body[0].body[1].value.resolved
    assert isinstance(expr, ast.BinOp) and expr.op == "+"
    assert isinstance(expr.left, ast.Identifier)
    assert ("nowy",) in expr.left.lemmas_set


def test_old_nowy_syntax_raises(parse):
    """Stara składnia `nowy Typ` — `nowy` jest teraz niezadeklarowaną zmienną."""
    src = (
        "definicja Użytkownika:\n    nazwa (Tekst)\n"
        "aby działać:\n    u to nowy Użytkownik o nazwie \"Anna\"\n"
    )
    with pytest.raises(ast.ResolveError, match="'nowy' nie jest zadeklarowaną"):
        parse(src)


def test_capitalization_separates_type_from_variable(parse):
    """Zmienna `lista` (mała litera) i typ `Lista` współistnieją — wielka
    litera w lemmie jednoznacznie wskazuje konstruktor."""
    src = (
        "definicja Listy z elementem:\n    wartość (element)\n"
        "aby działać:\n"
        "    lista to pięć\n"
        "    pojemnik to Lista o wartości lista\n"
        "    wynik to lista plus jeden\n"
    )
    m = parse(src)
    sc = m.body[1].body[1].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assert sc.type_name == ("Lista",)
    assert isinstance(sc.args[0].value, ast.Identifier)
    ref = m.body[1].body[2].value.resolved
    assert isinstance(ref.left, ast.Identifier)


def test_nested_creation_as_field_value(parse):
    """Zagnieżdżona konstrukcja jako wartość pola — bez `nowy`."""
    src = (
        "definicja Autora:\n    imię (Tekst)\n"
        "definicja Komentarza:\n    autor (Autor)\n"
        "aby działać:\n"
        "    komentarz to Komentarz o autorze Autor o imieniu \"Anna\"\n"
    )
    m = parse(src)
    sc = m.body[2].body[0].value.resolved
    assert isinstance(sc, ast.StructCreation)
    assert sc.type_name == ("Komentarz",)
    inner = sc.args[0].value
    assert isinstance(inner, ast.StructCreation)
    assert inner.type_name == ("Autor",)


# ---------- `pod` jako zwykły przyimek (po usunięciu subskryptu) ----------


def test_pod_as_preposition_in_params_and_args(parse):
    """`pod` to zwykły przyimek — działa w parametrach i argumentach
    wywołań (dawniej zarezerwowane przez operator subskryptu)."""
    src = (
        "aby chować skarb pod ziemią:\n    zwrócić\n"
        "aby działać skarb ziemia:\n"
        "    chowaj skarb pod ziemią\n"
    )
    m = parse(src)
    call = m.body[1].body[0].resolved
    assert isinstance(call, ast.FunctionCall)
    preps = [p.prep for p in call.params]
    assert ("pod",) in preps


# =====================================================================
# Wbudowane `Nic` w uniach — walidacja Pass 2
# =====================================================================

_NIC_UNION_BASE = (
    "definicja Czegoś z elementem:\n"
    "    wartość (element)\n"
    "\n"
)


def test_union_with_nic_member_resolves(parse):
    m = parse(_NIC_UNION_BASE + "Rezultat to Coś albo Nic\n")
    ud = m.body[1]
    assert isinstance(ud, ast.UnionDef)
    assert ud.members == [("Coś",), ("Nic",)]


def test_union_other_builtin_member_still_raises(parse):
    # wyjątek dotyczy TYLKO Nic — pozostałe builtiny nie są wariantami
    src = _NIC_UNION_BASE + "Rezultat to Coś albo Liczba\n"
    with pytest.raises(ast.ResolveError, match="nie jest zdefiniowaną strukturą"):
        parse(src)


def test_match_nic_branch_cannot_bind_fields(parse):
    src = (
        _NIC_UNION_BASE
        + "Rezultat to Coś albo Nic\n"
        "\n"
        "aby działać rezultat:\n"
        "    rezultat jest:\n"
        "        Czymś z wartością:\n"
        "            x to wartość\n"
        "        Niczym z wartością:\n"
        "            x to wartość\n"
    )
    with pytest.raises(ast.ResolveError, match="nie pasuje do żadnego wolnego pola"):
        parse(src)
