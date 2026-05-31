"""Testy typecheckera (Hindley–Milner) — `typechecker.py`.

Plik celowo NIE rusza istniejących testów (`test_gćć.py`,
`test_expression.py`, …) — to osobny zestaw skupiony wyłącznie na
inferencji typów: union-find (`find_type`/`unify_types`), instancjonowaniu
schematów funkcji (`instantiate`) i — co najważniejsze — polimorficznych
wywołaniach funkcji (ten sam schemat użyty w wielu miejscach z różnymi
typami konkretnymi nie powoduje kolizji).

Dwa poziomy:
- testy jednostkowe budujące AST ręcznie (bez SGJP, szybkie),
- testy integracyjne przez pełny pipeline (lex → morph → parse → resolve →
  typecheck) na realnym źródle Ć — wymagają załadowania SGJP (session
  fixture).

Typechecker trzyma stan w globalach modułu (`last_type`, `all_types`,
`fun_decls`), więc autouse-fixture `_reset_typechecker` izoluje każdy test.

Kontrakty utrwalone tutaj odzwierciedlają OBECNE zachowanie (m.in. to, że
kolizja typów jest sygnalizowana `RuntimeError` przez `raise` bez aktywnego
wyjątku w `unify_types`, oraz że parametry funkcji nie są wiązane do scope
ciała). To testy charakteryzacyjne istniejącej funkcjonalności, nie
specyfikacja docelowa.
"""

import os

import pytest

import lexer
import morph_anal
import preprocess
import parser as parser_mod
import expression
import ast_nodes as ast
import typechecker


# ---------- fixtures: izolacja stanu globalnego ----------

@pytest.fixture(autouse=True)
def _reset_typechecker():
    """Każdy test startuje z czystym licznikiem typów i pustymi tablicami."""
    typechecker.last_type = 0
    typechecker.all_types = {}
    typechecker.fun_decls = []
    yield
    typechecker.last_type = 0
    typechecker.all_types = {}
    typechecker.fun_decls = []


# ---------- helpery do budowy AST ----------

def make_ident(lemma, number="sg", gender="m"):
    """Identyfikator nie-funkcyjny z jednym wariantem (subst-głowa)."""
    v = ast.Variant(
        lemmas=(lemma,),
        case=frozenset({"nom"}),
        number=number,
        gender=gender,
        rest_length=0,
    )
    return ast.Identifier(surface=(lemma,), variants=(v,))


def make_fid(lemma):
    """Identyfikator funkcji o jednej kanonicznej interpretacji lemma."""
    return ast.FunctionIdentifier(
        lemmas_set=frozenset({(lemma,)}),
        surface=(lemma,),
    )


def phrase(resolved):
    return ast.Phrase(tokens=[], resolved=resolved)


# =====================================================================
# new_type / find_type — union-find
# =====================================================================

def test_new_type_is_fresh_and_sequential():
    a = typechecker.new_type()
    b = typechecker.new_type()
    assert a == "t0"
    assert b == "t1"
    assert a != b
    assert typechecker.type_regex.match(a)


def test_find_type_concrete_is_identity():
    # Typ konkretny (nie pasujący do tNN) zwracany bez zmian.
    assert typechecker.find_type("Liczba") == "Liczba"
    assert typechecker.find_type("UżytkownikSerwis") == "UżytkownikSerwis"


def test_find_type_fresh_var_registers_itself():
    t = typechecker.new_type()
    assert typechecker.find_type(t) == t
    # po pierwszym find_type zmienna wskazuje na siebie
    assert typechecker.all_types[t] == t


def test_find_type_follows_union_chain():
    a, b, c = typechecker.new_type(), typechecker.new_type(), typechecker.new_type()
    # ręcznie zbudowany łańcuch a -> b -> c
    typechecker.all_types[a] = b
    typechecker.all_types[b] = c
    typechecker.all_types[c] = c
    assert typechecker.find_type(a) == c
    assert typechecker.find_type(b) == c


# =====================================================================
# unify_types
# =====================================================================

def test_unify_two_abstract_links_them():
    a, b = typechecker.new_type(), typechecker.new_type()
    typechecker.unify_types(a, b)
    assert typechecker.find_type(a) == typechecker.find_type(b)


def test_unify_abstract_with_concrete_resolves_to_concrete():
    a = typechecker.new_type()
    result = typechecker.unify_types(a, "Liczba")
    assert result == "Liczba"
    assert typechecker.find_type(a) == "Liczba"


def test_unify_concrete_with_abstract_order_independent():
    a = typechecker.new_type()
    result = typechecker.unify_types("Tekst", a)
    assert result == "Tekst"
    assert typechecker.find_type(a) == "Tekst"


def test_unify_equal_concrete_returns_concrete():
    assert typechecker.unify_types("Liczba", "Liczba") == "Liczba"


def test_unify_conflicting_concrete_raises():
    # kolizja konkretów: print + bare `raise` → RuntimeError
    with pytest.raises(RuntimeError):
        typechecker.unify_types("Liczba", "Tekst")


def test_unify_is_transitive_through_var():
    a, b = typechecker.new_type(), typechecker.new_type()
    typechecker.unify_types(a, b)
    typechecker.unify_types(b, "Liczba")
    # a powiązane z b, b z Liczba → a też Liczba
    assert typechecker.find_type(a) == "Liczba"
    assert typechecker.find_type(b) == "Liczba"


def test_unify_propagates_to_already_linked_vars():
    a, b, c = (typechecker.new_type() for _ in range(3))
    typechecker.unify_types(a, b)
    typechecker.unify_types(b, c)
    typechecker.unify_types(c, "Tekst")
    assert typechecker.find_type(a) == "Tekst"
    assert typechecker.find_type(b) == "Tekst"
    assert typechecker.find_type(c) == "Tekst"


# =====================================================================
# instantiate — świeże kopie schematu (rdzeń polimorfizmu)
# =====================================================================

def test_instantiate_freshens_type_vars():
    t0 = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=make_fid("robić"), arg_types=[t0], ret_type=t0)
    args, ret = typechecker.instantiate(fdt)
    # świeże zmienne — różne od oryginału schematu
    assert args[0] != t0
    assert ret != t0
    assert typechecker.type_regex.match(args[0])


def test_instantiate_shares_vars_within_one_instance():
    # ta sama zmienna w schemacie → ta sama świeża zmienna po instancjonowaniu
    t0 = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=make_fid("robić"), arg_types=[t0, t0], ret_type=t0)
    args, ret = typechecker.instantiate(fdt)
    assert args[0] == args[1] == ret


def test_instantiate_keeps_concrete_types():
    t0 = typechecker.new_type()
    fdt = typechecker.FunDefTypes(
        name=make_fid("robić"), arg_types=["Liczba", t0], ret_type="Tekst"
    )
    args, ret = typechecker.instantiate(fdt)
    assert args[0] == "Liczba"
    assert ret == "Tekst"
    assert args[1] != t0  # zmienna nadal świeżona


def test_instantiate_two_calls_are_independent():
    t0 = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=make_fid("robić"), arg_types=[t0], ret_type=t0)
    a1, _ = typechecker.instantiate(fdt)
    a2, _ = typechecker.instantiate(fdt)
    assert a1[0] != a2[0]  # każde wywołanie dostaje własne zmienne


# =====================================================================
# Scope.get_type
# =====================================================================

def test_scope_same_lemma_returns_same_type():
    scope = typechecker.Scope()
    t1 = scope.get_type(make_ident("rzecz"))
    t2 = scope.get_type(make_ident("rzecz"))
    assert t1 == t2


def test_scope_different_lemmas_get_distinct_types():
    scope = typechecker.Scope()
    t1 = scope.get_type(make_ident("rzecz"))
    t2 = scope.get_type(make_ident("wynik"))
    assert t1 != t2


def test_scope_overlapping_lemma_variants_match():
    # identyfikator z wieloma wariantami matchuje istniejący po przecięciu lemm
    scope = typechecker.Scope()
    t1 = scope.get_type(make_ident("rzecz"))
    multi = ast.Identifier(
        surface=("rzecz",),
        variants=(
            ast.Variant(lemmas=("rzecz",), case=frozenset({"nom"}),
                        number="sg", gender="f", rest_length=0),
            ast.Variant(lemmas=("rzec",), case=frozenset({"nom"}),
                        number="sg", gender="m", rest_length=0),
        ),
    )
    assert scope.get_type(multi) == t1


# =====================================================================
# find_fdt
# =====================================================================

def test_find_fdt_matches_by_lemma_overlap():
    fid = make_fid("robić")
    fdt = typechecker.FunDefTypes(name=fid, arg_types=[], ret_type=typechecker.new_type())
    typechecker.fun_decls.append((fid, fdt))
    # wywołanie z inną powierzchnią ale tą samą lemmą (np. tryb rozkazujący)
    call_name = ast.FunctionIdentifier(lemmas_set=frozenset({("robić",)}), surface=("rób",))
    assert typechecker.find_fdt(call_name) is fdt


def test_find_fdt_returns_none_when_no_match():
    fid = make_fid("robić")
    typechecker.fun_decls.append(
        (fid, typechecker.FunDefTypes(name=fid, arg_types=[], ret_type=typechecker.new_type()))
    )
    other = make_fid("liczyć")
    assert typechecker.find_fdt(other) is None


# =====================================================================
# resolve_expression — literały, Typed, opakowania
# =====================================================================

def test_resolve_int_literal():
    assert typechecker.resolve_expression(ast.IntLit(5), typechecker.Scope()) == "Liczba"


def test_resolve_str_literal():
    assert typechecker.resolve_expression(ast.StrLit("x"), typechecker.Scope()) == "Tekst"


def test_resolve_unwraps_phrase_and_word():
    inner = ast.Word(prep=(), value=ast.IntLit(1), case="nom")
    node = phrase(inner)
    assert typechecker.resolve_expression(node, typechecker.Scope()) == "Liczba"


def test_resolve_typed_unifies_matching():
    node = ast.Typed(expr=ast.IntLit(1), type=("Liczba",))
    assert typechecker.resolve_expression(node, typechecker.Scope()) == "Liczba"


def test_resolve_typed_conflict_raises():
    node = ast.Typed(expr=ast.IntLit(1), type=("Tekst",))
    with pytest.raises(RuntimeError):
        typechecker.resolve_expression(node, typechecker.Scope())


# =====================================================================
# resolve_assignment / resolve_return
# =====================================================================

def test_assignment_unifies_target_with_value():
    scope = typechecker.Scope()
    target = make_ident("rzecz")
    node = ast.Assignment(target=phrase(target), value=phrase(ast.IntLit(1)))
    typechecker.resolve_assignment(node, scope)
    assert typechecker.find_type(scope.get_type(target)) == "Liczba"


def test_assignment_conflict_raises():
    scope = typechecker.Scope()
    target = make_ident("rzecz")
    typechecker.resolve_assignment(
        ast.Assignment(target=phrase(target), value=phrase(ast.IntLit(1))), scope
    )
    with pytest.raises(RuntimeError):
        typechecker.resolve_assignment(
            ast.Assignment(target=phrase(target), value=phrase(ast.StrLit("x"))), scope
        )


def test_return_unifies_ret_type_with_value():
    scope = typechecker.Scope()
    scope.root_fdt = typechecker.FunDefTypes(
        name=make_fid("robić"), arg_types=[], ret_type=typechecker.new_type()
    )
    typechecker.resolve_return(ast.Return(value=ast.IntLit(5)), scope)
    assert typechecker.find_type(scope.root_fdt.ret_type) == "Liczba"


def test_return_without_value_is_nic():
    scope = typechecker.Scope()
    scope.root_fdt = typechecker.FunDefTypes(
        name=make_fid("robić"), arg_types=[], ret_type=typechecker.new_type()
    )
    typechecker.resolve_return(ast.Return(value=None), scope)
    assert typechecker.find_type(scope.root_fdt.ret_type) == "Nic"


# =====================================================================
# resolve_function_call — POLIMORFIZM
# =====================================================================

def _register_identity_like():
    """Schemat funkcji dla x: zwróć x  (arg_types=[t], ret_type=t)."""
    fid = make_fid("robić")
    t = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=fid, arg_types=[t], ret_type=t)
    typechecker.fun_decls.append((fid, fdt))
    return fid, fdt, t


def test_function_call_propagates_arg_type_to_return():
    fid, fdt, t = _register_identity_like()
    call = ast.FunctionCall(name=fid, params=[ast.IntLit(1)])
    ret = typechecker.resolve_function_call(call, typechecker.Scope())
    assert typechecker.find_type(ret) == "Liczba"


def test_polymorphic_calls_do_not_interfere():
    """Sedno polimorfizmu: ten sam schemat wywołany z Liczba i z Tekst —
    oba wywołania udane, bo `instantiate` daje świeże zmienne. Bez
    instancjonowania drugie wywołanie skolidowałoby z pierwszym."""
    fid, fdt, t = _register_identity_like()
    scope = typechecker.Scope()

    r1 = typechecker.resolve_function_call(
        ast.FunctionCall(name=fid, params=[ast.IntLit(1)]), scope
    )
    r2 = typechecker.resolve_function_call(
        ast.FunctionCall(name=fid, params=[ast.StrLit("x")]), scope
    )

    assert typechecker.find_type(r1) == "Liczba"
    assert typechecker.find_type(r2) == "Tekst"
    # schemat (generalizacja) NIE jest skażony przez żadne wywołanie
    assert typechecker.find_type(fdt.ret_type) == t


def test_shared_type_var_enforced_within_single_call():
    """Dwa parametry dzielące zmienną w schemacie muszą mieć ten sam typ
    w obrębie jednego wywołania → konflikt Liczba/Tekst rzuca."""
    fid = make_fid("robić")
    t = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=fid, arg_types=[t, t], ret_type=t)
    typechecker.fun_decls.append((fid, fdt))
    call = ast.FunctionCall(name=fid, params=[ast.IntLit(1), ast.StrLit("x")])
    with pytest.raises(RuntimeError):
        typechecker.resolve_function_call(call, typechecker.Scope())


def test_same_var_two_matching_args_ok():
    fid = make_fid("robić")
    t = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=fid, arg_types=[t, t], ret_type=t)
    typechecker.fun_decls.append((fid, fdt))
    call = ast.FunctionCall(name=fid, params=[ast.IntLit(1), ast.IntLit(2)])
    ret = typechecker.resolve_function_call(call, typechecker.Scope())
    assert typechecker.find_type(ret) == "Liczba"


# =====================================================================
# resolve_struct_creation
# =====================================================================

def test_struct_creation_returns_type_name():
    node = ast.StructCreation(type_name=("Użytkownik", "Serwis"), args=[])
    result = typechecker.resolve_struct_creation(node, typechecker.Scope())
    assert result == "UżytkownikSerwis"


# =====================================================================
# Integracja: pełny pipeline (wymaga SGJP)
# =====================================================================

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


@pytest.fixture
def parse(db, preps):
    """Źródło Ć → zresolvowany Module (gotowy dla typecheckera)."""
    def _parse(text):
        morphs = preprocess.preprocess(morph_anal.analyze(lexer.lex(text), db))
        module = parser_mod.parse(morphs, preps)
        expression.resolve_module(module, preps)
        return module
    return _parse


@pytest.mark.integration
def test_module_typechecks_polymorphic_program(parse, capsys):
    """Funkcja z nietypowanym parametrem wołana raz z liczbą, raz z tekstem.
    Polimorfizm pozwala obu wywołaniom przejść; w scope `liczba` ma typ
    Liczba, a `słowo` typ Tekst (dwa różne typy konkretne współistnieją)."""
    src = (
        "aby przetwarzać dla x:\n"
        "    zwróć jeden\n"
        "\n"
        "aby działać:\n"
        "    liczba to jeden\n"
        "    słowo to \"tekst\"\n"
        "    a to przetwarzać dla liczby\n"
        "    b to przetwarzać dla słowa\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)  # nie rzuca = polimorfizm działa
    out = capsys.readouterr().out
    assert "Liczba" in out
    assert "Tekst" in out


@pytest.mark.integration
def test_module_detects_type_conflict(parse):
    """Przypisanie liczby a potem tekstu do tej samej zmiennej → kolizja."""
    src = (
        "aby działać:\n"
        "    rzecz to jeden\n"
        "    rzecz to \"tekst\"\n"
    )
    module = parse(src)
    with pytest.raises(RuntimeError):
        typechecker.resolve_module(module)


@pytest.mark.integration
def test_module_infers_return_type_through_call(parse, capsys):
    """`wynik` dostaje typ Liczba z typu zwracanego wołanej funkcji."""
    src = (
        "aby liczyć dla x (Liczba):\n"
        "    zwróć pięć\n"
        "\n"
        "aby działać:\n"
        "    rzecz to jeden\n"
        "    wynik to licz dla rzeczy\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)
    out = capsys.readouterr().out
    # zarówno argument jak i wynik powinny być Liczba
    assert "Liczba" in out


@pytest.mark.integration
def test_module_struct_creation_infers_struct_type(parse, capsys):
    """Tworzenie struktury nadaje zmiennej typ nazwy struktury."""
    src = (
        "definicja UżytkownikaSerwisu:\n"
        "    imię (Tekst)\n"
        "    identyfikator (Liczba)\n"
        "\n"
        "aby działać:\n"
        "    użytkownik to nowy UżytkownikSerwis o imieniu \"Marcin\"\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)
    out = capsys.readouterr().out
    assert "UżytkownikSerwis" in out
