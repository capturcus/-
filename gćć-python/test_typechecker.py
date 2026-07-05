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

Reprezentacja typów: union-find po obiektach. `new_type()` daje `TypeVar`
(wolna zmienna), konkrety/warianty to `VariantVar(variants=set(nazw))`,
połączone wskaźnikiem `next`. `find_type` zwraca reprezentanta (obiekt, nie
string), a `unify_types` przecina warianty; pusty wynik → `TypeCheckError`.
Helper `ty(t)` renderuje zresolwowany typ jako '?' (wolna zmienna) lub
'A|B' (posortowane warianty) do wygodnych asercji.

Typechecker trzyma stan w globalach modułu (`last_type`, `fun_decls`), więc
autouse-fixture `_reset_typechecker` izoluje każdy test.
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
    """Każdy test startuje z czystym licznikiem typów i pustym fun_decls.
    Stan union-find żyje w obiektach TypeVar/VariantVar (per test świeże),
    więc nie ma globalnej tablicy do czyszczenia."""
    typechecker.last_type = 0
    typechecker.fun_decls = []
    typechecker.fun_scopes = []
    typechecker.module = None
    yield
    typechecker.last_type = 0
    typechecker.fun_decls = []
    typechecker.fun_scopes = []
    typechecker.module = None


# ---------- helpery ----------

def ty(t):
    """Zresolwowany typ jako wartość porównywalna: '?' dla wolnej zmiennej,
    'A|B' (posortowane warianty) dla konkretu/wariantu."""
    r = typechecker.find_type(t)
    if isinstance(r, typechecker.TypeVar):
        return "?"
    return "|".join(sorted(a.head for a in r.variants))


def conc(*names):
    """Konkret/wariant z podanych nazw (skrót na typechecker.variant)."""
    return typechecker.variant(set(names))


def _var_types():
    """Typy zmiennych po ostatnim resolve_module: {powierzchnia: ty(t)}
    ze wszystkich scope'ów (funkcje + bloki) w typechecker.fun_scopes."""
    pairs = {}
    for _decl, scope in typechecker.fun_scopes:
        for s in scope.walk():
            for v, t in s.types:
                pairs["_".join(v.surface)] = ty(t)
    return pairs


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
    assert a.number == 0
    assert b.number == 1
    assert a is not b
    assert isinstance(a, typechecker.TypeVar)


def test_find_type_concrete_is_identity():
    # Konkret (VariantVar bez next) zwracany bez zmian.
    c = conc("Liczba")
    assert typechecker.find_type(c) is c
    assert ty(c) == "Liczba"


def test_find_type_fresh_var_is_its_own_representative():
    t = typechecker.new_type()
    assert typechecker.find_type(t) is t
    # świeża zmienna nie wskazuje na nic
    assert t.next is None


def test_find_type_follows_union_chain():
    a, b, c = typechecker.new_type(), typechecker.new_type(), typechecker.new_type()
    # ręcznie zbudowany łańcuch a -> b -> c
    a.next = b
    b.next = c
    assert typechecker.find_type(a) is c
    assert typechecker.find_type(b) is c


# =====================================================================
# unify_types
# =====================================================================

def test_unify_two_abstract_links_them():
    a, b = typechecker.new_type(), typechecker.new_type()
    typechecker.unify_types(a, b)
    assert typechecker.find_type(a) is typechecker.find_type(b)


def test_unify_abstract_with_concrete_resolves_to_concrete():
    a = typechecker.new_type()
    result = typechecker.unify_types(a, conc("Liczba"))
    assert ty(result) == "Liczba"
    assert ty(a) == "Liczba"


def test_unify_concrete_with_abstract_order_independent():
    a = typechecker.new_type()
    result = typechecker.unify_types(conc("Tekst"), a)
    assert ty(result) == "Tekst"
    assert ty(a) == "Tekst"


def test_unify_equal_concrete_returns_concrete():
    assert ty(typechecker.unify_types(conc("Liczba"), conc("Liczba"))) == "Liczba"


def test_unify_conflicting_concrete_raises():
    # kolizja konkretów: puste przecięcie wariantów → TypeCheckError
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.unify_types(conc("Liczba"), conc("Tekst"))


def test_unify_is_transitive_through_var():
    a, b = typechecker.new_type(), typechecker.new_type()
    typechecker.unify_types(a, b)
    typechecker.unify_types(b, conc("Liczba"))
    # a powiązane z b, b z Liczba → a też Liczba
    assert ty(a) == "Liczba"
    assert ty(b) == "Liczba"


def test_unify_propagates_to_already_linked_vars():
    a, b, c = (typechecker.new_type() for _ in range(3))
    typechecker.unify_types(a, b)
    typechecker.unify_types(b, c)
    typechecker.unify_types(c, conc("Tekst"))
    assert ty(a) == "Tekst"
    assert ty(b) == "Tekst"
    assert ty(c) == "Tekst"


# =====================================================================
# Generyki: strukturalna unifikacja AppliedType, occurs-check, deep-fresh
# =====================================================================

def _applied(head, *args):
    """VariantVar z jednym AppliedType(head, args) — args to węzły typów."""
    return typechecker.VariantVar(variants={typechecker.AppliedType(head, tuple(args))})


def test_unify_applied_links_args():
    # Lista[a] z Lista[b] → a ≡ b (strukturalna unifikacja argumentów).
    a, b = typechecker.new_type(), typechecker.new_type()
    typechecker.unify_types(_applied("Lista", a), _applied("Lista", b))
    assert typechecker.find_type(a) is typechecker.find_type(b)


def test_unify_applied_propagates_concrete_to_arg():
    # Lista[a] z Lista[Liczba] → a := Liczba.
    a = typechecker.new_type()
    typechecker.unify_types(_applied("Lista", a), _applied("Lista", conc("Liczba")))
    assert ty(a) == "Liczba"


def test_unify_applied_head_mismatch_raises():
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.unify_types(_applied("Lista", typechecker.new_type()),
                                _applied("Mapa", typechecker.new_type()))


def test_unify_applied_arity_mismatch_raises():
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.unify_types(_applied("Para", typechecker.new_type()),
                                _applied("Para", typechecker.new_type(), typechecker.new_type()))


def test_occurs_check_raises():
    # a = Lista[a] → nieskończony typ → odrzucone.
    a = typechecker.new_type()
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.unify_types(a, _applied("Lista", a))


def test_instantiate_deep_fresh_args():
    # Schemat (Lista[W], W); instancjonowanie ma: dzielić W w obrębie instancji,
    # ale dawać niezależne W między instancjami (rdzeń polimorfizmu generyków).
    w = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=make_fid("robić"),
                                  arg_types=[_applied("Lista", w)], ret_type=w)
    (a1,), r1 = typechecker.instantiate(fdt)
    (a2,), r2 = typechecker.instantiate(fdt)
    e1 = next(iter(typechecker.find_type(a1).variants)).args[0]
    e2 = next(iter(typechecker.find_type(a2).variants)).args[0]
    assert typechecker.find_type(e1) is typechecker.find_type(r1)        # współdzielone w instancji
    assert typechecker.find_type(e1) is not typechecker.find_type(e2)    # niezależne między instancjami


# =====================================================================
# instantiate — świeże kopie schematu (rdzeń polimorfizmu)
# =====================================================================

def test_instantiate_freshens_type_vars():
    t0 = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=make_fid("robić"), arg_types=[t0], ret_type=t0)
    args, ret = typechecker.instantiate(fdt)
    # świeże zmienne — różne obiekty niż oryginał schematu
    assert args[0] is not t0
    assert ret is not t0
    assert isinstance(args[0], typechecker.TypeVar)


def test_instantiate_shares_vars_within_one_instance():
    # ta sama zmienna w schemacie → ta sama świeża zmienna po instancjonowaniu
    t0 = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=make_fid("robić"), arg_types=[t0, t0], ret_type=t0)
    args, ret = typechecker.instantiate(fdt)
    assert args[0] is args[1] is ret


def test_instantiate_keeps_concrete_types():
    t0 = typechecker.new_type()
    fdt = typechecker.FunDefTypes(
        name=make_fid("robić"), arg_types=[conc("Liczba"), t0], ret_type=conc("Tekst")
    )
    args, ret = typechecker.instantiate(fdt)
    assert ty(args[0]) == "Liczba"
    assert ty(ret) == "Tekst"
    assert args[1] is not t0  # zmienna nadal świeżona


def test_instantiate_two_calls_are_independent():
    t0 = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=make_fid("robić"), arg_types=[t0], ret_type=t0)
    a1, _ = typechecker.instantiate(fdt)
    a2, _ = typechecker.instantiate(fdt)
    assert a1[0] is not a2[0]  # każde wywołanie dostaje własne zmienne


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


def test_scope_matches_on_shared_full_key():
    # identyfikator z wieloma wariantami matchuje istniejący, gdy któryś
    # wariant dzieli PEŁNY klucz scope (lemma, number, gender) — kanoniczna
    # semantyka, ta sama co w expression._Scope.
    scope = typechecker.Scope()
    t1 = scope.get_type(make_ident("rzecz"))  # (rzecz, sg, m)
    multi = ast.Identifier(
        surface=("rzecz",),
        variants=(
            ast.Variant(lemmas=("rzecz",), case=frozenset({"nom"}),
                        number="sg", gender="m", rest_length=0),  # ten sam klucz
            ast.Variant(lemmas=("rzec",), case=frozenset({"nom"}),
                        number="sg", gender="f", rest_length=0),
        ),
    )
    assert scope.get_type(multi) == t1


def test_scope_distinguishes_by_gender():
    # rozjazd rodzaju przy tej samej lemmie → osobne zmienne (np. kotek m vs
    # kotka f). Spójne z rozróżnieniem w expression._Scope.
    scope = typechecker.Scope()
    t_m = scope.get_type(make_ident("kotek", gender="m"))
    t_f = scope.get_type(make_ident("kotek", gender="f"))
    assert t_m != t_f


# =====================================================================
# scope_key_matches — kanoniczny predykat (ast_nodes), reużywany przez
# resolver i typechecker (single source of truth)
# =====================================================================

def test_scope_key_matches_identical():
    k = (("rzecz",), "sg", "f")
    assert ast.scope_key_matches(k, k)


def test_scope_key_matches_atom_against_full_either_direction():
    atom = (("x",), None, None)
    full = (("x",), "sg", "m")
    assert ast.scope_key_matches(atom, full)
    assert ast.scope_key_matches(full, atom)


def test_scope_key_matches_rejects_gender_mismatch():
    assert not ast.scope_key_matches((("kotek",), "sg", "m"),
                                     (("kotek",), "sg", "f"))


def test_scope_key_matches_rejects_lemma_mismatch():
    assert not ast.scope_key_matches((("rzecz",), None, None),
                                     (("wynik",), None, None))


# =====================================================================
# atomy (single-letter) w scope — jądro buga A
# =====================================================================

def atom_ident(letter):
    """Atom: single-letter, brak analiz → variants=(), scope_keys via fallback."""
    return ast.Identifier(surface=(letter,), analyses=((),))


def test_scope_atom_get_type_is_stable():
    # przed fixem: atomy nigdy się nie matchowały (variants=() → pusty zbiór),
    # więc każde get_type zwracało NOWĄ zmienną. Teraz scope_keys daje
    # (letter, None, None) i atomy się sklejają.
    scope = typechecker.Scope()
    t1 = scope.get_type(atom_ident("x"))
    t2 = scope.get_type(atom_ident("x"))
    assert t1 == t2


def test_scope_declare_binds_atom():
    scope = typechecker.Scope()
    scope.declare(atom_ident("x"), conc("Liczba"))
    assert ty(scope.get_type(atom_ident("x"))) == "Liczba"


def test_scope_declare_is_idempotent():
    scope = typechecker.Scope()
    scope.declare(atom_ident("x"), conc("Liczba"))
    scope.declare(atom_ident("x"), conc("Tekst"))  # już zadeklarowane → ignorowane
    assert ty(scope.get_type(atom_ident("x"))) == "Liczba"


# =====================================================================
# resolve_function_def — seed parametrów do scope
# =====================================================================

def test_resolve_function_def_binds_param_type():
    # param 'x' (atom, nietypowany w AST) związany z arg_types[0]=Liczba;
    # użycie x w ciele (przypisanie do wynik) musi dać wynik:Liczba.
    scope = typechecker.Scope()
    scope.root_fdt = typechecker.FunDefTypes(
        name=make_fid("przetwarzać"), arg_types=[conc("Liczba")], ret_type=typechecker.new_type()
    )
    x = atom_ident("x")
    param = ast.Param(prep=None, name=x, case=frozenset({"nom"}))
    body = [ast.Assignment(target=phrase(make_ident("wynik")), value=phrase(x))]
    node = ast.FunctionDef(name=make_fid("przetwarzać"), params=[param], body=body)
    typechecker.resolve_function_def(node, scope)
    assert ty(scope.get_type(x)) == "Liczba"
    assert ty(scope.get_type(make_ident("wynik"))) == "Liczba"


def test_resolve_function_def_param_usage_constrains_signature():
    # param nietypowany; użycie w ciele (przypisanie liczby) wpływa NA
    # sygnaturę, bo param i arg_types[0] to ta sama zmienna.
    scope = typechecker.Scope()
    arg = typechecker.new_type()
    scope.root_fdt = typechecker.FunDefTypes(
        name=make_fid("przetwarzać"), arg_types=[arg], ret_type=typechecker.new_type()
    )
    x = atom_ident("x")
    param = ast.Param(prep=None, name=x, case=frozenset({"nom"}))
    body = [ast.Assignment(target=phrase(x), value=phrase(ast.IntLit(1)))]
    node = ast.FunctionDef(name=make_fid("przetwarzać"), params=[param], body=body)
    typechecker.resolve_function_def(node, scope)
    assert ty(arg) == "Liczba"  # sygnatura nauczyła się z ciała


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
    assert ty(typechecker.resolve_expression(ast.IntLit(5), typechecker.Scope())) == "Liczba"


def test_resolve_str_literal():
    assert ty(typechecker.resolve_expression(ast.StrLit("x"), typechecker.Scope())) == "Tekst"


def test_resolve_unwraps_phrase_and_word():
    inner = ast.Word(prep=(), value=ast.IntLit(1), case="nom")
    node = phrase(inner)
    assert ty(typechecker.resolve_expression(node, typechecker.Scope())) == "Liczba"


def test_resolve_typed_unifies_matching():
    node = ast.Typed(expr=ast.IntLit(1), type=ast.TypeRef(head=("Liczba",)))
    assert ty(typechecker.resolve_expression(node, typechecker.Scope())) == "Liczba"


def test_resolve_typed_conflict_raises():
    node = ast.Typed(expr=ast.IntLit(1), type=ast.TypeRef(head=("Tekst",)))
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_expression(node, typechecker.Scope())


# =====================================================================
# resolve_assignment / resolve_return
# =====================================================================

def test_assignment_unifies_target_with_value():
    scope = typechecker.Scope()
    target = make_ident("rzecz")
    node = ast.Assignment(target=phrase(target), value=phrase(ast.IntLit(1)))
    typechecker.resolve_assignment(node, scope)
    assert ty(scope.get_type(target)) == "Liczba"


def test_assignment_conflict_raises():
    scope = typechecker.Scope()
    target = make_ident("rzecz")
    typechecker.resolve_assignment(
        ast.Assignment(target=phrase(target), value=phrase(ast.IntLit(1))), scope
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_assignment(
            ast.Assignment(target=phrase(target), value=phrase(ast.StrLit("x"))), scope
        )


def test_return_unifies_ret_type_with_value():
    scope = typechecker.Scope()
    scope.root_fdt = typechecker.FunDefTypes(
        name=make_fid("robić"), arg_types=[], ret_type=typechecker.new_type()
    )
    typechecker.resolve_return(ast.Return(value=ast.IntLit(5)), scope)
    assert ty(scope.root_fdt.ret_type) == "Liczba"


def test_return_without_value_is_nic():
    scope = typechecker.Scope()
    scope.root_fdt = typechecker.FunDefTypes(
        name=make_fid("robić"), arg_types=[], ret_type=typechecker.new_type()
    )
    typechecker.resolve_return(ast.Return(value=None), scope)
    assert ty(scope.root_fdt.ret_type) == "Nic"


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
    assert ty(ret) == "Liczba"


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

    assert ty(r1) == "Liczba"
    assert ty(r2) == "Tekst"
    # schemat (generalizacja) NIE jest skażony przez żadne wywołanie
    assert typechecker.find_type(fdt.ret_type) is t


def test_shared_type_var_enforced_within_single_call():
    """Dwa parametry dzielące zmienną w schemacie muszą mieć ten sam typ
    w obrębie jednego wywołania → konflikt Liczba/Tekst rzuca."""
    fid = make_fid("robić")
    t = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=fid, arg_types=[t, t], ret_type=t)
    typechecker.fun_decls.append((fid, fdt))
    call = ast.FunctionCall(name=fid, params=[ast.IntLit(1), ast.StrLit("x")])
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_function_call(call, typechecker.Scope())


def test_same_var_two_matching_args_ok():
    fid = make_fid("robić")
    t = typechecker.new_type()
    fdt = typechecker.FunDefTypes(name=fid, arg_types=[t, t], ret_type=t)
    typechecker.fun_decls.append((fid, fdt))
    call = ast.FunctionCall(name=fid, params=[ast.IntLit(1), ast.IntLit(2)])
    ret = typechecker.resolve_function_call(call, typechecker.Scope())
    assert ty(ret) == "Liczba"


# =====================================================================
# resolve_struct_creation
# =====================================================================

def test_struct_creation_returns_type_name():
    node = ast.StructCreation(type_name=("Użytkownik", "Serwis"), args=[])
    result = typechecker.resolve_struct_creation(node, typechecker.Scope())
    assert ty(result) == "UżytkownikSerwis"


# =====================================================================
# Integracja: pełny pipeline (wymaga SGJP)
# =====================================================================

# SGJP (db) i preps pochodzą ze współdzielonej fixturki w conftest.py.


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
def test_module_typechecks_polymorphic_program(parse):
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
    types = _var_types()
    assert types["liczba"] == "Liczba"
    assert types["słowo"] == "Tekst"


@pytest.mark.integration
def test_module_detects_type_conflict(parse):
    """Przypisanie liczby a potem tekstu do tej samej zmiennej → kolizja."""
    src = (
        "aby działać:\n"
        "    rzecz to jeden\n"
        "    rzecz to \"tekst\"\n"
    )
    module = parse(src)
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(module)


@pytest.mark.integration
def test_module_infers_return_type_through_call(parse):
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
    # zarówno argument jak i wynik powinny być Liczba
    types = _var_types()
    assert types["rzecz"] == "Liczba"
    assert types["wynik"] == "Liczba"


@pytest.mark.integration
def test_module_struct_creation_infers_struct_type(parse):
    """Tworzenie struktury nadaje zmiennej typ nazwy struktury."""
    src = (
        "definicja UżytkownikaSerwisu:\n"
        "    imię (Tekst)\n"
        "    identyfikator (Liczba)\n"
        "\n"
        "aby działać:\n"
        "    użytkownik to UżytkownikSerwis o imieniu \"Marcin\" "
        "o identyfikatorze siedem\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)
    assert _var_types()["użytkownik"] == "UżytkownikSerwis"


def _fdt_by_surface(surface):
    """Znajduje FunDefTypes po powierzchni nazwy w globalnym fun_decls."""
    for (name, fdt) in typechecker.fun_decls:
        if name.surface == surface:
            return fdt
    return None


@pytest.mark.integration
def test_explicit_param_type_reaches_body(parse):
    """A1: jawny typ parametru (Liczba) dociera do ciała — `wynik = x` jest
    Liczbą, więc zwracany typ funkcji to Liczba (przed fixem: wolna zmienna)."""
    src = (
        "aby przetwarzać dla x (Liczba):\n"
        "    wynik to x\n"
        "    zwróć wynik\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)
    fdt = _fdt_by_surface(("przetwarzać",))
    assert ty(fdt.ret_type) == "Liczba"


@pytest.mark.integration
def test_param_usage_constrains_signature(parse):
    """A2 (positive): użycie parametru w ciele (przekazanie do funkcji
    wymagającej Liczby) wnioskuje typ argumentu W SYGNATURZE."""
    src = (
        "aby wymagać_liczby dla n (Liczba):\n"
        "    zwróć n\n"
        "\n"
        "aby opakować dla x:\n"
        "    zwróć wymagać_liczby dla x\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)
    fdt = _fdt_by_surface(("opakować",))
    assert ty(fdt.arg_types[0]) == "Liczba"


@pytest.mark.integration
def test_bad_call_after_inferred_param_raises(parse):
    """A2 (negative): skoro `opakować` ma teraz sygnaturę Liczba→…, wywołanie
    go na tekście jest błędem typu (przed fixem: cicho akceptowane)."""
    src = (
        "aby wymagać_liczby dla n (Liczba):\n"
        "    zwróć n\n"
        "\n"
        "aby opakować dla x:\n"
        "    zwróć wymagać_liczby dla x\n"
        "\n"
        "aby działać:\n"
        "    wynik to opakuj dla \"tekst\"\n"
    )
    module = parse(src)
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(module)


# =====================================================================
# Fixpoint — inferencja ciał iterowana do zbieżności (Problem B, część)
# =====================================================================

@pytest.mark.integration
def test_fixpoint_resolves_forward_reference(parse):
    """`przygotować` woła `generować` zdefiniowane NIŻEJ. Pojedynczy przebieg
    łapałby kopię wolnego ret-typu; iteracja domyka go do Liczby."""
    src = (
        "aby przygotować dla x:\n"
        "    zwróć generować dla x\n"
        "\n"
        "aby generować dla y:\n"
        "    zwróć pięć\n"
        "\n"
        "aby działać:\n"
        "    a to przygotuj dla jeden\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)
    assert ty(_fdt_by_surface(("przygotować",)).ret_type) == "Liczba"
    assert ty(_fdt_by_surface(("generować",)).ret_type) == "Liczba"


@pytest.mark.integration
def test_fixpoint_propagates_through_chain(parse):
    """Łańcuch przygotować→generować→produkować→pięć. Single-pass rozwiązałby
    tylko ostatnią; fixpoint propaguje Liczbę przez cały łańcuch (≥3 przebiegi)."""
    src = (
        "aby przygotować dla x:\n"
        "    zwróć generować dla x\n"
        "\n"
        "aby generować dla y:\n"
        "    zwróć produkować dla y\n"
        "\n"
        "aby produkować dla z:\n"
        "    zwróć pięć\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)
    for surface in (("przygotować",), ("generować",), ("produkować",)):
        assert ty(_fdt_by_surface(surface).ret_type) == "Liczba"


@pytest.mark.integration
def test_fixpoint_preserves_polymorphism_and_terminates(parse):
    """Funkcja generyczna wołana raz na liczbie, raz na tekście. resolve_module
    kończy bez zawieszenia (fixpoint), a argument zostaje WOLNY — czyli nadal
    polimorficzny, nie sklejony do jednego typu przez iterację."""
    src = (
        "aby przetwarzać dla x:\n"
        "    zwróć x\n"
        "\n"
        "aby działać:\n"
        "    a to przetwarzać dla jeden\n"
        "    b to przetwarzać dla \"tekst\"\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)  # nie zawiesza się
    arg = typechecker.find_type(_fdt_by_surface(("przetwarzać",)).arg_types[0])
    assert isinstance(arg, typechecker.TypeVar)  # wciąż wolna zmienna = polimorfizm


@pytest.mark.integration
def test_fixpoint_is_deterministic(parse):
    """Dwa przebiegi (z resetem stanu) dają tę samą konkretyzację schematów."""
    src = (
        "aby przygotować dla x:\n"
        "    zwróć generować dla x\n"
        "\n"
        "aby generować dla y:\n"
        "    zwróć pięć\n"
    )

    def run():
        typechecker.last_type = 0
        typechecker.fun_decls = []
        typechecker.resolve_module(parse(src))
        return (ty(_fdt_by_surface(("przygotować",)).ret_type),
                ty(_fdt_by_surface(("generować",)).ret_type))

    assert run() == run() == ("Liczba", "Liczba")


# =====================================================================
# Typecheck struct creation — wyszukiwanie pól + unifikacja typu pola
# =====================================================================

def test_find_struct_def_by_name():
    sd = ast.StructDef(
        name=("Użytkownik",),
        fields=[
            ast.Field(name=make_ident("imię", gender="n"), type=ast.TypeRef(head=("Tekst",))),
            ast.Field(name=make_ident("wiek"), type=ast.TypeRef(head=("Liczba",))),
        ],
    )
    typechecker.module = ast.Module(body=[sd])
    assert typechecker.find_struct_def(("Użytkownik",)) is sd
    assert typechecker.find_struct_def(("Nieznany",)) is None


def test_find_field_by_key_and_type():
    sd = ast.StructDef(
        name=("Użytkownik",),
        fields=[
            ast.Field(name=make_ident("imię", gender="n"), type=ast.TypeRef(head=("Tekst",))),
            ast.Field(name=make_ident("wiek"), type=ast.TypeRef(head=("Liczba",))),
        ],
    )
    imie = typechecker.find_field(sd, (("imię",), "sg", "n"))
    assert imie is not None and "".join(imie.type.head) == "Tekst"
    wiek = typechecker.find_field(sd, (("wiek",), "sg", "m"))
    assert wiek is not None and "".join(wiek.type.head) == "Liczba"
    assert typechecker.find_field(sd, (("brak",), "sg", "m")) is None


_STRUCT_DEF = (
    "definicja UżytkownikaSerwisu:\n"
    "    imię (Tekst)\n"
    "    identyfikator (Liczba)\n"
    "\n"
)


@pytest.mark.integration
def test_struct_explicit_values_typecheck(parse):
    src = _STRUCT_DEF + (
        "aby działać:\n"
        "    u to UżytkownikSerwisu o imieniu \"Marcin\" o identyfikatorze cztery\n"
    )
    typechecker.resolve_module(parse(src))  # bez błędu


@pytest.mark.integration
def test_struct_out_of_order_typechecks(parse):
    # odwrócona kolejność pól: gdyby match był pozycyjny, imię dostałoby Liczbę
    # → błąd. Brak błędu dowodzi dopasowania po nazwie i unifikacji per pole.
    src = _STRUCT_DEF + (
        "aby działać:\n"
        "    u to UżytkownikSerwisu o identyfikatorze cztery o imieniu \"Marcin\"\n"
    )
    typechecker.resolve_module(parse(src))  # bez błędu


@pytest.mark.integration
def test_struct_field_type_mismatch_raises(parse):
    src = _STRUCT_DEF + (
        "aby działać:\n"
        "    u to UżytkownikSerwisu o imieniu cztery "
        "o identyfikatorze pięć\n"  # Liczba w pole Tekst
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_struct_shorthand_typechecks(parse):
    # odwzorowanie test_typów.ć: pole imię:Tekst wypełniane zmienną imię:Tekst
    src = _STRUCT_DEF + (
        "aby działać:\n"
        "    imię to \"Marcin\"\n"
        "    użytkownik to UżytkownikSerwisu z imieniem o identyfikatorze dwa\n"
    )
    typechecker.resolve_module(parse(src))  # bez błędu


@pytest.mark.integration
def test_struct_shorthand_type_mismatch_raises(parse):
    # zmienna imię:Liczba vs pole imię:Tekst → konflikt
    src = _STRUCT_DEF + (
        "aby działać:\n"
        "    imię to pięć\n"
        "    użytkownik to UżytkownikSerwisu z imieniem o identyfikatorze dwa\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Typy wariantowe — widening (struktura < unia) w unifikacji
# =====================================================================

def _install_unions(*decls):
    """Moduł z samymi UnionDef — wystarczy dla _widening_union/find_union_def.
    `decls` to pary (nazwa, członkowie)."""
    body = [
        ast.UnionDef(name=(name,), members=[(m,) for m in members])
        for name, members in decls
    ]
    typechecker.module = ast.Module(body=body)


def test_unify_two_variants_widens_to_union():
    _install_unions(("Rezultat", ["Wynik", "Błąd"]))
    result = typechecker.unify_types(conc("Wynik"), conc("Błąd"), widen=True)
    assert ty(result) == "Rezultat"


def test_unify_without_widen_flag_raises():
    # widening tylko na pozycjach top-level — domyślna unifikacja jest ścisła
    _install_unions(("Rezultat", ["Wynik", "Błąd"]))
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.unify_types(conc("Wynik"), conc("Błąd"))


def test_unify_struct_with_union_widens():
    _install_unions(("Rezultat", ["Wynik", "Błąd"]))
    result = typechecker.unify_types(conc("Wynik"), conc("Rezultat"), widen=True)
    assert ty(result) == "Rezultat"


def test_unify_widen_without_covering_union_raises():
    _install_unions(("Rezultat", ["Wynik", "Błąd"]))
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.unify_types(conc("Wynik"), conc("Tekst"), widen=True)


def test_unify_two_unions_raises():
    # brak relacji unia < unia
    _install_unions(("Rezultat", ["Wynik", "Błąd"]),
                    ("Pojemnik", ["Wynik", "Pudełko"]))
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.unify_types(conc("Rezultat"), conc("Pojemnik"), widen=True)


def test_widen_prefers_minimal_union():
    _install_unions(("Mała", ["A", "B"]), ("Duża", ["A", "B", "C"]))
    result = typechecker.unify_types(conc("A"), conc("B"), widen=True)
    assert ty(result) == "Mała"


def test_widen_ambiguous_tie_raises():
    _install_unions(("Pierwsza", ["A", "B"]), ("Druga", ["A", "B"]))
    with pytest.raises(typechecker.TypeCheckError, match="niejednoznaczne"):
        typechecker.unify_types(conc("A"), conc("B"), widen=True)


def test_widen_erases_type_arguments():
    # unia nie niesie parametrów — Wynik[Liczba] | Błąd → Rezultat (0-arg)
    _install_unions(("Rezultat", ["Wynik", "Błąd"]))
    result = typechecker.unify_types(
        _applied("Wynik", conc("Liczba")), conc("Błąd"), widen=True)
    r = typechecker.find_type(result)
    assert ty(r) == "Rezultat"
    assert next(iter(r.variants)).args == ()


def test_widen_does_not_apply_inside_type_arguments():
    # inwariancja typów parametryzowanych: Lista[Wynik] ≠ Lista[Rezultat]
    _install_unions(("Rezultat", ["Wynik", "Błąd"]))
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.unify_types(
            _applied("Lista", conc("Wynik")),
            _applied("Lista", conc("Rezultat")),
            widen=True,
        )


# =====================================================================
# Typy wariantowe — elaborate / struct creation
# =====================================================================

def test_elaborate_union_annotation_is_concrete_in_signature():
    # głowa-unia w sygnaturze NIE staje się niejawnym parametrem typu
    _install_unions(("Rezultat", ["Wynik", "Błąd"]))
    t = typechecker.elaborate(
        ast.TypeRef(head=("Rezultat",)), {}, fresh_unknown=True)
    assert ty(t) == "Rezultat"


def test_elaborate_union_with_type_args_raises():
    _install_unions(("Rezultat", ["Wynik", "Błąd"]))
    tref = ast.TypeRef(
        head=("Rezultat",),
        args=[ast.TypeArg(prep=None, type=ast.TypeRef(head=("Liczba",)))],
    )
    with pytest.raises(typechecker.TypeCheckError, match="nie przyjmuje argumentów"):
        typechecker.elaborate(tref, {})


def test_struct_creation_of_union_raises():
    _install_unions(("Rezultat", ["Wynik", "Błąd"]))
    node = ast.StructCreation(type_name=("Rezultat",), args=[])
    with pytest.raises(typechecker.TypeCheckError, match="nie można utworzyć"):
        typechecker.resolve_struct_creation(node, typechecker.Scope())


# =====================================================================
# Typy wariantowe — integracja (pełny pipeline)
# =====================================================================

_UNION_SRC = (
    "definicja Błędu:\n"
    "    opis (Tekst)\n"
    "\n"
    "definicja Wyniku z elementem:\n"
    "    wynik (element)\n"
    "\n"
    "Rezultat to Wynik albo Błąd\n"
    "\n"
)


@pytest.mark.integration
def test_function_returning_two_variants_gets_union_type(parse):
    """Gałęzie zwracające różne warianty jednej unii → funkcja otypowana unią."""
    src = _UNION_SRC + (
        "aby zapisywać tekst -> Rezultat:\n"
        "    jeśli tekst równe zero:\n"
        "        zwróć Wynik o wyniku zero\n"
        "    inaczej:\n"
        "        zwróć Błąd o opisie \"nie udało się\"\n"
    )
    typechecker.resolve_module(parse(src))
    assert ty(_fdt_by_surface(("zapisywać",)).ret_type) == "Rezultat"


@pytest.mark.integration
def test_function_returning_two_variants_infers_union_without_annotation(parse):
    """Ten sam program BEZ adnotacji `-> Rezultat` — unia wnioskowana."""
    src = _UNION_SRC + (
        "aby zapisywać tekst:\n"
        "    jeśli tekst równe zero:\n"
        "        zwróć Wynik o wyniku zero\n"
        "    inaczej:\n"
        "        zwróć Błąd o opisie \"nie udało się\"\n"
    )
    typechecker.resolve_module(parse(src))
    assert ty(_fdt_by_surface(("zapisywać",)).ret_type) == "Rezultat"


@pytest.mark.integration
def test_branches_returning_unrelated_types_raise(parse):
    """Gałęzie zwracające typy bez wspólnej unii → odrzucamy."""
    src = _UNION_SRC + (
        "aby zapisywać tekst:\n"
        "    jeśli tekst równe zero:\n"
        "        zwróć Wynik o wyniku zero\n"
        "    inaczej:\n"
        "        zwróć \"niepowiązany tekst\"\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_assigning_two_variants_widens_variable(parse, capsys):
    src = _UNION_SRC + (
        "aby przygotowywać dla x:\n"
        "    rzecz to Wynik o wyniku zero\n"
        "    rzecz to Błąd o opisie \"e\"\n"
        "    zwróć rzecz\n"
    )
    typechecker.resolve_module(parse(src))
    assert ty(_fdt_by_surface(("przygotowywać",)).ret_type) == "Rezultat"


@pytest.mark.integration
def test_match_exhaustive_typechecks_and_binds_field_types(parse):
    """Pełne dopasowanie `jest:`: pole `opis` związane jako Tekst (typ z deklaracji
    struktury), pole `wynik` (parametr `element`) konkretyzuje się przez
    użycie (`plus jeden` → Liczba)."""
    src = _UNION_SRC + (
        "aby działać:\n"
        "    rezultat (Rezultat) to Wynik o wyniku zero\n"
        "    rezultat jest:\n"
        "        Błędem z opisem:\n"
        "            wiadomość to opis\n"
        "        Wynikiem z wynikiem:\n"
        "            liczba to wynik plus jeden\n"
    )
    typechecker.resolve_module(parse(src))
    types = _var_types()
    assert types["wiadomość"] == "Tekst"
    assert types["liczba"] == "Liczba"


@pytest.mark.integration
def test_match_missing_branch_raises(parse):
    src = _UNION_SRC + (
        "aby działać:\n"
        "    rezultat (Rezultat) to Wynik o wyniku zero\n"
        "    rezultat jest:\n"
        "        Wynikiem z wynikiem:\n"
        "            liczba to wynik\n"
    )
    with pytest.raises(typechecker.TypeCheckError, match="brakuje gałęzi: Błąd"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_match_extra_branch_raises(parse):
    src = _UNION_SRC + (
        "definicja Pustki:\n"
        "    nic (Liczba)\n"
        "\n"
        "aby działać:\n"
        "    rezultat (Rezultat) to Wynik o wyniku zero\n"
        "    rezultat jest:\n"
        "        Wynikiem z wynikiem:\n"
        "            liczba to wynik\n"
        "        Błędem z opisem:\n"
        "            wiadomość to opis\n"
        "        Pustką:\n"
        "            x to jeden\n"
    )
    with pytest.raises(typechecker.TypeCheckError, match="spoza unii: Pustka"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_match_duplicate_branch_raises(parse):
    src = _UNION_SRC + (
        "aby działać:\n"
        "    rezultat (Rezultat) to Wynik o wyniku zero\n"
        "    rezultat jest:\n"
        "        Wynikiem z wynikiem:\n"
        "            liczba to wynik\n"
        "        Wynikiem:\n"
        "            x to jeden\n"
    )
    with pytest.raises(typechecker.TypeCheckError, match="powtórzona gałąź"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_match_on_non_union_subject_raises(parse):
    src = _UNION_SRC + (
        "aby działać:\n"
        "    rezultat to pięć\n"
        "    rezultat jest:\n"
        "        Wynikiem z wynikiem:\n"
        "            liczba to wynik\n"
        "        Błędem z opisem:\n"
        "            wiadomość to opis\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_match_infers_union_type_of_free_param(parse):
    """dopasowanie `jest:` na nieotypowanym parametrze — gałęzie wyznaczają unię,
    która trafia DO SYGNATURY funkcji; wspólny typ zwrotny gałęzi (element
    Wyniku unifikowany z `zero`) daje Liczbę."""
    src = _UNION_SRC + (
        "aby obsługiwać rezultat:\n"
        "    rezultat jest:\n"
        "        Wynikiem z wynikiem:\n"
        "            zwróć wynik\n"
        "        Błędem z opisem:\n"
        "            zwróć zero\n"
    )
    typechecker.resolve_module(parse(src))
    fdt = _fdt_by_surface(("obsługiwać",))
    assert ty(fdt.arg_types[0]) == "Rezultat"
    assert ty(fdt.ret_type) == "Liczba"


@pytest.mark.integration
def test_match_subject_widens_struct_to_union(parse):
    """Subject o typie konkretnego wariantu (Wynik) — match na unii rozszerza
    go do Rezultat i wymaga WSZYSTKICH gałęzi unii."""
    src = _UNION_SRC + (
        "aby działać:\n"
        "    rezultat to Wynik o wyniku zero\n"
        "    rezultat jest:\n"
        "        Wynikiem z wynikiem:\n"
        "            liczba to wynik plus jeden\n"
        "        Błędem z opisem:\n"
        "            wiadomość to opis\n"
    )
    typechecker.resolve_module(parse(src))  # bez błędu


@pytest.mark.integration
def test_passing_variant_to_union_param_typechecks(parse):
    src = _UNION_SRC + (
        "aby przyjmować rezultat (Rezultat) -> Liczba:\n"
        "    zwróć zero\n"
        "\n"
        "aby działać:\n"
        "    n to przyjmuj Błąd o opisie \"e\"\n"
    )
    typechecker.resolve_module(parse(src))  # bez błędu


@pytest.mark.integration
def test_union_in_struct_field_accepts_variant(parse):
    src = _UNION_SRC + (
        "definicja Pudełka:\n"
        "    zawartość (Rezultat)\n"
        "\n"
        "aby działać:\n"
        "    pudełko to Pudełko o zawartości Błąd o opisie \"e\"\n"
    )
    typechecker.resolve_module(parse(src))  # bez błędu


@pytest.mark.integration
def test_creating_union_value_directly_raises(parse):
    src = _UNION_SRC + (
        "aby działać:\n"
        "    rezultat to Rezultat\n"
    )
    with pytest.raises(typechecker.TypeCheckError, match="nie można utworzyć"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_parameterized_types_invariant_over_union(parse):
    """Lista z Wynikiem ≠ Lista z Rezultatem — kontenery są inwariantne."""
    src = _UNION_SRC + (
        "definicja Listy z elementem:\n"
        "    wartość (element)\n"
        "\n"
        "aby brać listę (Lista z (Rezultat)) -> Liczba:\n"
        "    zwróć zero\n"
        "\n"
        "aby działać:\n"
        "    lista (Lista z (Wynik)) to Lista o wartości (Wynik o wyniku zero)\n"
        "    n to bierz listę\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Block scoping — spójność resolvera i typecheckera
# =====================================================================


@pytest.mark.integration
def test_branch_reassignment_unifies_with_outer_var(parse):
    """Zmienna zadeklarowana przed `jeśli`, reasygnowana w gałęziach, użyta
    po bloku — resolver i typechecker widzą JEDNĄ zmienną, więc typ z gałęzi
    (Liczba) dociera do użycia po bloku i grounding `działać` przechodzi.
    (Dawniej: trzy rozłączne zmienne i błąd 'nie można wywnioskować typu'.)"""
    src = (
        "aby działać:\n"
        "    flaga to jeden\n"
        "    licznik to zero\n"
        "    jeśli flaga równe jeden:\n"
        "        licznik to pięć\n"
        "    inaczej:\n"
        "        licznik to dziesięć\n"
        "    wynik to licznik\n"
    )
    typechecker.resolve_module(parse(src))  # bez błędu — wynik ugruntowany


@pytest.mark.integration
def test_branch_reassignment_type_conflict_raises(parse):
    """Reasignacja w gałęzi unifikuje się z zewnętrzną zmienną — konflikt
    typów (Liczba vs Tekst) jest wykrywany. (Dawniej: gałęziowa zmienna była
    osobna, konflikt przechodził bez błędu.)"""
    src = (
        "aby działać:\n"
        "    flaga to jeden\n"
        "    licznik to zero\n"
        "    jeśli flaga równe jeden:\n"
        "        licznik to \"tekst\"\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_match_branch_reassignment_unifies_with_outer_var(parse):
    """Wzorzec 'zainicjalizuj przed matchem, przypisz w gałęziach' — jedna
    zmienna w obu modelach, typ z gałęzi widoczny po matchu."""
    src = (
        "definicja Błędu:\n"
        "    opis (Tekst)\n"
        "\n"
        "definicja Wyniku z elementem:\n"
        "    wynik (element)\n"
        "\n"
        "Rezultat to Wynik albo Błąd\n"
        "\n"
        "aby działać:\n"
        "    rezultat (Rezultat) to Wynik o wyniku zero\n"
        "    komunikat to \"\"\n"
        "    rezultat jest:\n"
        "        Błędem z opisem:\n"
        "            komunikat to opis\n"
        "        Wynikiem:\n"
        "            komunikat to \"ok\"\n"
        "    wiadomość to komunikat\n"
    )
    typechecker.resolve_module(parse(src))  # komunikat/wiadomość: Tekst


def _reset_typechecker_state():
    typechecker.last_type = 0
    typechecker.fun_decls = []
    typechecker.fun_scopes = []
    typechecker.module = None


@pytest.mark.integration
def test_intersection_of_union_bounds(parse):
    """Typechecker przecięciowy: parametr ograniczony DWIEMA uniami
    (≤ Domownik i ≤ Futrzak) zawęża się do wspólnego wariantu (Kot) —
    wywołanie z Kotem przechodzi, z Psem (tylko Domownik) odrzucane."""
    prelude = (
        "definicja Kota:\n    imię (Tekst)\n"
        "\n"
        "definicja Psa:\n    kość (Tekst)\n"
        "\n"
        "definicja Chomika:\n    futro (Tekst)\n"
        "\n"
        "Domownik to Kot albo Pies\n"
        "\n"
        "Futrzak to Kot albo Chomik\n"
        "\n"
        "można wypisać coś (Cokolwiek) -> Nic\n"
        "\n"
        "aby przygarnąć domownika (Domownik):\n"
        "    wypisz \"przygarnięty\"\n"
        "\n"
        "aby wyczesać futrzaka (Futrzak):\n"
        "    wypisz \"wyczesany\"\n"
        "\n"
        "aby doglądać pupila:\n"
        "    przygarnij pupila\n"
        "    wyczesz pupila\n"
        "\n"
    )
    typechecker.resolve_module(parse(
        prelude + "aby działać:\n    doglądaj Kot o imieniu \"Mruczek\"\n"))
    _reset_typechecker_state()
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(
            prelude + "aby działać:\n    doglądaj Pies o kości \"szynka\"\n"))


@pytest.mark.integration
def test_for_loop_is_loudly_rejected(parse):
    """Decyzja językowa: `dla ... w ...:` czeka na protokół iteracji
    (kolekcje są biblioteczne, nie wbudowane) — typechecker odmawia
    głośno zamiast cichego pomijania pętli w executorze."""
    src = (
        "aby działać lista:\n"
        "    dla elementu w liście:\n"
        "        wynik to element\n"
    )
    with pytest.raises(typechecker.TypeCheckError,
                       match="protokołu iteracji"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_join_of_two_free_params(parse):
    """Pełne więzy podtypowania: `zwróć kot` / `zwróć pies` to poszlaki
    dolne — parametry pozostają niezależne (bez sklejania równością),
    a ret jest ich kresem: Kot ⊔ Pies = Domownik w miejscu wywołania."""
    src = (
        "definicja Kota:\n    imię (Tekst)\n"
        "\n"
        "definicja Psa:\n    kość (Tekst)\n"
        "\n"
        "Domownik to Kot albo Pies\n"
        "\n"
        "aby wybrać flagę kota psa:\n"
        "    jeśli flaga:\n"
        "        zwróć kot\n"
        "    zwróć pies\n"
        "\n"
        "aby działać:\n"
        "    kot to Kot o imieniu \"Mruczek\"\n"
        "    pies to Pies o kości \"szynka\"\n"
        "    pupil to wybierz prawda kota psa\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["pupil"] == "Domownik"
    # parametry NIE splątane — każdy zachował własny konkret z wywołania
    assert _var_types()["kot"] == "Kot"
    assert _var_types()["pies"] == "Pies"


@pytest.mark.integration
def test_deferred_disjunction_resolves_by_join(parse):
    """Dysjunkcja typów pól z wielu kandydatów chaina rozstrzyga się
    przybyciem konkretu: przeżywa gałąź-unia absorbująca wariant
    (Węzeł ∈ Gałąź), kandydat Drzewo odpada."""
    src = (
        "definicja Drzewa dla rzeczy:\n"
        "    wartość (rzecz)\n"
        "    lewy_syn (Drzewo dla rzeczy)\n"
        "\n"
        "definicja Węzła z elementem:\n"
        "    wartość (element)\n"
        "    wysokość (Liczba)\n"
        "    lewy_syn (Gałąź)\n"
        "\n"
        "Gałąź to Węzeł albo Nic\n"
        "\n"
        "aby zbadać drzewo:\n"
        "    filar to lewy_syn drzewa\n"
        "    filar to Węzeł o wartości jeden o wysokości jeden o lewym_synu Nic\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["filar"] == "Gałąź"


@pytest.mark.integration
def test_union_value_into_variant_slot_raises(parse):
    """Bramkarz: wartość typu unii NIE przechodzi do parametru typu
    wariantu — wymagaj zawężenia przez `jest:` (dawne
    bad/unia_do_wariantu.ć typowało się i padało w runtime)."""
    src = (
        "definicja Kota:\n    imię (Tekst)\n"
        "\n"
        "Zwierzę to Kot albo Nic\n"
        "\n"
        "można wypisać coś (Cokolwiek) -> Nic\n"
        "\n"
        "aby wybrać flagę:\n"
        "    jeśli flaga:\n"
        "        zwróć Kot o imieniu \"Mruczek\"\n"
        "    zwróć Nic\n"
        "\n"
        "aby przedstawić kota (Kot):\n"
        "    wypisz (imię kota)\n"
        "\n"
        "aby działać:\n"
        "    zwierzę to wybierz fałsz\n"
        "    przedstaw zwierzę\n"
    )
    with pytest.raises(typechecker.TypeCheckError,
                       match="nie mieści się w slocie"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_fallthrough_unifies_nic_into_return(parse):
    """Ścieżka bez `zwróć` = niejawne `zwróć Nic`: funkcja częściowa
    z zadeklarowaną unią dostaje typ unii (fall-through jest legalny
    i widoczny w typie)."""
    src = (
        "definicja Kota:\n"
        "    imię (Tekst)\n"
        "\n"
        "Zwierzę to Kot albo Nic\n"
        "\n"
        "aby szukać flagi:\n"
        "    jeśli flaga:\n"
        "        zwróć Kot o imieniu \"Filemon\"\n"
    )
    typechecker.resolve_module(parse(src))
    assert ty(_fdt_by_surface(("szukać",)).ret_type) == "Zwierzę"


@pytest.mark.integration
def test_fallthrough_without_union_raises(parse):
    """Bez unii pokrywającej Kot i Nic funkcja częściowa jest odrzucana —
    dawniej typowała się jako Kot i padała w runtime na chainach
    (bad/nietotalny_zwrot.ć)."""
    src = (
        "definicja Kota:\n"
        "    imię (Tekst)\n"
        "\n"
        "aby szukać flagi:\n"
        "    jeśli flaga:\n"
        "        zwróć Kot o imieniu \"Filemon\"\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_unused_parameterized_alias_fails_grounding(parse):
    """Nieużyty alias `jako` sparametryzowanego wariantu w `działać`:
    element zostaje wolny i wpada w grounding — alias jest pisany przez
    użytkownika (jak wiązanie pola), więc błąd jest naprawialny (usuń
    martwy binder). NIEJAWNY cień podmiotu w tej samej gałęzi nie
    przeszkadza (Scope.shadows poza groundingiem)."""
    src = (
        "definicja Wyniku z elementem:\n"
        "    wynik (element)\n"
        "\n"
        "definicja Błędu:\n"
        "    opis (Tekst)\n"
        "\n"
        "Rezultat to Wynik albo Błąd\n"
        "\n"
        "aby działać:\n"
        "    rezultat (Rezultat) to Wynik o wyniku zero\n"
        "    rezultat jest:\n"
        "        Wynikiem jako paczka:\n"
        "            komunikat to \"ok\"\n"
        "        Błędem:\n"
        "            komunikat to \"źle\"\n"
    )
    with pytest.raises(typechecker.TypeCheckError, match="paczka"):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Extern (`można`) — rejestracja sygnatur w typecheckerze
# =====================================================================


@pytest.mark.integration
def test_extern_call_typechecks_and_grounds(parse, capsys):
    """Wywołanie externa w `działać`: typ zwracany z sygnatury dociera do
    zmiennej, grounding przechodzi (dawniej: find_fdt zwracał None i
    typechecker wywalał się AttributeError)."""
    src = (
        "można wysłać tekst (Tekst) do wtyczki (Liczba) -> Liczba\n"
        "\n"
        "aby działać:\n"
        "    wtyczka to siedem\n"
        "    wynik to wyślij \"abc\" do wtyczki\n"
    )
    typechecker.resolve_module(parse(src))
    fdt = _fdt_by_surface(("wysłać",))
    assert ty(fdt.arg_types[0]) == "Tekst"
    assert ty(fdt.arg_types[1]) == "Liczba"
    assert ty(fdt.ret_type) == "Liczba"


@pytest.mark.integration
def test_extern_arg_type_mismatch_raises(parse):
    src = (
        "można wypisać tekst (Tekst) -> Nic\n"
        "\n"
        "aby działać:\n"
        "    wypisz pięć\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_extern_signature_constrains_caller_param(parse):
    """Typ z sygnatury externa wnioskuje typ parametru funkcji wołającej."""
    src = (
        "można policzyć x (Tekst) -> Liczba\n"
        "\n"
        "aby opakować rzecz:\n"
        "    zwróć policz rzecz\n"
    )
    typechecker.resolve_module(parse(src))
    fdt = _fdt_by_surface(("opakować",))
    assert ty(fdt.arg_types[0]) == "Tekst"
    assert ty(fdt.ret_type) == "Liczba"


@pytest.mark.integration
def test_extern_unknown_type_shared_within_signature(parse):
    """Niezdefiniowana głowa (Miejsce) działa jak parametr typu sygnatury —
    oba wystąpienia muszą dostać TEN SAM typ; konflikt Liczba/Tekst rzuca."""
    src = (
        "można leżeć na polanie (Miejsce) w lesie (Miejsce) "
        "przy jeziorze (Liczba) -> Liczba\n"
        "\n"
        "aby działać:\n"
        "    n to leż na pięć w \"las\" przy siedem\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_extern_unknown_type_consistent_call_typechecks(parse):
    src = (
        "można leżeć na polanie (Miejsce) w lesie (Miejsce) "
        "przy jeziorze (Liczba) -> Liczba\n"
        "\n"
        "aby działać:\n"
        "    n to leż na pięć w sześć przy siedem\n"
    )
    typechecker.resolve_module(parse(src))  # Miejsce := Liczba w tej instancji


@pytest.mark.integration
def test_extern_returning_union_typechecks(parse):
    """Extern może zwracać typ wariantowy — dopasowanie `jest:` na wyniku działa."""
    src = (
        "definicja Błędu:\n"
        "    opis (Tekst)\n"
        "\n"
        "definicja Wyniku z elementem:\n"
        "    wynik (element)\n"
        "\n"
        "Rezultat to Wynik albo Błąd\n"
        "\n"
        "można zapisać dane (Tekst) -> Rezultat\n"
        "\n"
        "aby działać:\n"
        "    rezultat to zapisz \"abc\"\n"
        "    komunikat to \"\"\n"
        "    rezultat jest:\n"
        "        Wynikiem:\n"
        "            komunikat to \"ok\"\n"
        "        Błędem z opisem:\n"
        "            komunikat to opis\n"
    )
    typechecker.resolve_module(parse(src))


# =====================================================================
# Fixpoint — górna granica przebiegów (3N+5) pokrywa widening
# =====================================================================

_FIXPOINT_PRELUDE = (
    "definicja Błędu:\n"
    "    opis (Tekst)\n"
    "\n"
    "definicja Wyniku z elementem:\n"
    "    wynik (element)\n"
    "\n"
    "Rezultat to Wynik albo Błąd\n"
    "\n"
)

# 12 funkcji w cyklu rekurencyjnym; dwie bazy zwracają RÓŻNE warianty unii,
# więc każdy ret musi przejść pełną sekwencję faz: wolna → Wynik → Rezultat.
_CYCLE_FUNCS = "abcdefghijkl"


def _widening_cycle_src():
    parts = [_FIXPOINT_PRELUDE]
    n = len(_CYCLE_FUNCS)
    for i, c in enumerate(_CYCLE_FUNCS):
        nxt = _CYCLE_FUNCS[(i + 1) % n]
        base = ""
        if i == 0:
            base = "    jeśli x równe zero:\n        zwróć Wynik o wyniku zero\n"
        if i == n // 2:
            base = "    jeśli x równe jeden:\n        zwróć Błąd o opisie \"e\"\n"
        parts.append(
            f"aby robić_{c} dla x:\n{base}    zwróć rób_{nxt} dla x\n"
        )
    return "\n".join(parts)


@pytest.mark.integration
def test_fixpoint_converges_on_widening_cycle(parse, capsys):
    """Cykl wzajemnej rekursji, w którym typ zwracany każdej funkcji
    przechodzi wszystkie fazy (wolna → Wynik → Rezultat po wideningu).
    Cap przebiegów musi to pokrywać — brak ostrzeżenia o niedobiegnięciu
    i każdy ret skonkretyzowany do unii."""
    module = parse(_widening_cycle_src())
    typechecker.resolve_module(module)
    out = capsys.readouterr().out
    assert "OSTRZEŻENIE" not in out
    for c in _CYCLE_FUNCS:
        assert ty(_fdt_by_surface((f"robić_{c}".split("_")[0], c)).ret_type) \
            == "Rezultat"


@pytest.mark.integration
def test_fixpoint_converges_on_widening_relay(parse, capsys):
    """Sztafeta wideningu: każdy poziom łańcucha ma własną bazę-Wynik,
    a Błąd wspina się z dna — każdy ret najpierw stabilizuje się na Wynik,
    potem musi przejść na Rezultat drugą falą."""
    parts = [_FIXPOINT_PRELUDE]
    n = len(_CYCLE_FUNCS)
    for i, c in enumerate(_CYCLE_FUNCS):
        if i < n - 1:
            parts.append(
                f"aby robić_{c} dla x:\n"
                f"    jeśli x równe zero:\n"
                f"        zwróć Wynik o wyniku zero\n"
                f"    zwróć rób_{_CYCLE_FUNCS[i + 1]} dla x\n"
            )
        else:
            parts.append(
                f"aby robić_{c} dla x:\n"
                f"    zwróć Błąd o opisie \"e\"\n"
            )
    module = parse("\n".join(parts))
    typechecker.resolve_module(module)
    out = capsys.readouterr().out
    assert "OSTRZEŻENIE" not in out
    assert ty(_fdt_by_surface(("robić", "a")).ret_type) == "Rezultat"


# =====================================================================
# Wbudowane `Nic` — w uniach i jako wnioskowany typ zwracany
# =====================================================================

_NIC_UNION = (
    "definicja Czegoś z elementem:\n"
    "    wartość (element)\n"
    "\n"
    "Rezultat to Coś albo Nic\n"
    "\n"
)


@pytest.mark.integration
def test_explicit_return_nic_types_as_nic(parse):
    src = (
        "aby testować_nic:\n"
        "    zwróć Nic\n"
    )
    typechecker.resolve_module(parse(src))
    assert ty(_fdt_by_surface(("testować", "nic")).ret_type) == "Nic"


@pytest.mark.integration
def test_bare_return_types_as_nic(parse):
    src = (
        "aby testować_nic:\n"
        "    zwróć\n"
    )
    typechecker.resolve_module(parse(src))
    assert ty(_fdt_by_surface(("testować", "nic")).ret_type) == "Nic"


@pytest.mark.integration
def test_no_return_in_body_types_as_nic(parse):
    """Funkcja bez żadnego `zwróć` — typ zwracany Nic (dawniej: wolna
    zmienna, więc „wynik" takiej funkcji przechodził typecheck)."""
    src = (
        "aby testować_nic:\n"
        "    wynik to pięć\n"
    )
    typechecker.resolve_module(parse(src))
    assert ty(_fdt_by_surface(("testować", "nic")).ret_type) == "Nic"


@pytest.mark.integration
def test_no_return_in_nested_blocks_types_as_nic(parse):
    """Brak `zwróć` także w zagnieżdżonych blokach → Nic. `zwróć` ukryty
    tylko w gałęzi `jeśli` to funkcja CZĘŚCIOWA: fall-through dounifikowuje
    Nic, a Tekst∪Nic nie ma wspólnej unii → odrzucona (dawniej typowała
    się jako Tekst i padała w runtime — bad/nietotalny_zwrot.ć)."""
    src = (
        "aby testować_nic flaga:\n"
        "    jeśli flaga równe jeden:\n"
        "        x to dwa\n"
    )
    typechecker.resolve_module(parse(src))
    assert ty(_fdt_by_surface(("testować", "nic")).ret_type) == "Nic"

    czesciowa = (
        "aby badać flagę:\n"
        "    jeśli flaga równe jeden:\n"
        "        zwróć \"tekst\"\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(czesciowa))


@pytest.mark.integration
def test_annotated_return_without_return_raises(parse):
    """Jawna adnotacja `-> Tekst` przy ciele bez `zwróć` → konflikt z Nic."""
    src = (
        "aby testować_nic -> Tekst:\n"
        "    wynik to pięć\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_union_with_nic_member_widens_returns(parse):
    """`Nic` jako wariant unii: gałęzie zwracające `Coś` i `Nic` typują
    funkcję unią Rezultat."""
    src = _NIC_UNION + (
        "aby próbować dla x:\n"
        "    jeśli x równe zero:\n"
        "        zwróć Coś o wartości x\n"
        "    zwróć Nic\n"
    )
    typechecker.resolve_module(parse(src))
    assert ty(_fdt_by_surface(("próbować",)).ret_type) == "Rezultat"


@pytest.mark.integration
def test_match_with_nic_branch_typechecks(parse):
    """Gałąź `Niczym:` (narzędnik wbudowanego Nic) w dopasowaniu unii."""
    src = _NIC_UNION + (
        "aby opisywać rezultat -> Tekst:\n"
        "    rezultat jest:\n"
        "        Czymś z wartością:\n"
        "            zwróć \"jest coś\"\n"
        "        Niczym:\n"
        "            zwróć \"pusto\"\n"
    )
    typechecker.resolve_module(parse(src))
    fdt = _fdt_by_surface(("opisywać",))
    assert ty(fdt.arg_types[0]) == "Rezultat"
    assert ty(fdt.ret_type) == "Tekst"


@pytest.mark.integration
def test_match_missing_nic_branch_raises(parse):
    src = _NIC_UNION + (
        "aby opisywać rezultat (Rezultat) -> Tekst:\n"
        "    rezultat jest:\n"
        "        Czymś z wartością:\n"
        "            zwróć \"jest coś\"\n"
    )
    with pytest.raises(typechecker.TypeCheckError, match="brakuje gałęzi: Nic"):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Wywołania z obsługą błędu (tryb przypuszczający + `?`) — typowanie
# =====================================================================

_TRY_PRELUDE = (
    "definicja Sukcesu z elementem:\n"
    "    wartość (element)\n"
    "\n"
    "definicja Błędu:\n"
    "    opis (Tekst)\n"
    "\n"
    "Rezultat to Sukces albo Błąd\n"
    "\n"
    "aby wybrać pozycję z listy:\n"
    "    jeśli pozycja równe zero:\n"
    "        zwróć Sukces o wartości \"głowa\"\n"
    "    zwróć Błąd o opisie \"poza zakresem\"\n"
    "\n"
)


@pytest.mark.integration
def test_try_call_unwraps_and_widens_enclosing_return(parse):
    """`?` odpakowuje Sukces (typ konkretyzuje się przez użycie), a ret
    funkcji otaczającej rozszerza się o Błąd → z własnym Sukcesem daje
    Rezultat. Odpowiednik desugaru z dopasowaniem `jest:`."""
    src = _TRY_PRELUDE + (
        "aby przetwarzać części:\n"
        "    napis to wybrałbyś zero z części?\n"
        "    zwróć Sukces o wartości napis\n"
    )
    typechecker.resolve_module(parse(src))
    fdt = _fdt_by_surface(("przetwarzać",))
    assert ty(fdt.ret_type) == "Rezultat"


@pytest.mark.integration
def test_try_call_unwrapped_value_concretizes_by_use(parse):
    src = _TRY_PRELUDE + (
        "aby przetwarzać części:\n"
        "    liczba to wybrałbyś zero z części?\n"
        "    suma to liczba plus jeden\n"
        "    zwróć Sukces o wartości suma\n"
    )
    typechecker.resolve_module(parse(src))
    # liczba/suma skonkretyzowane przez `plus`
    types = _var_types()
    assert types["liczba"] == "Liczba"
    assert types["suma"] == "Liczba"


@pytest.mark.integration
def test_try_call_on_non_rezultat_callee_raises(parse):
    src = _TRY_PRELUDE + (
        "aby liczyć x:\n"
        "    zwróć pięć\n"
        "\n"
        "aby przetwarzać x:\n"
        "    y to liczyłbyś x?\n"
        "    zwróć Sukces o wartości y\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_try_call_without_rezultat_declaration_raises(parse):
    src = (
        "definicja Czegoś z elementem:\n"
        "    wartość (element)\n"
        "\n"
        "aby brać coś:\n"
        "    zwróć Coś o wartości coś\n"
        "\n"
        "aby przetwarzać x:\n"
        "    y to brałbyś x?\n"
        "    zwróć y\n"
    )
    with pytest.raises(typechecker.TypeCheckError,
                       match="Rezultat to Sukces albo Błąd"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_try_call_with_wrong_rezultat_shape_raises(parse):
    """Unia `Rezultat` o innym składzie (Coś albo Nic) nie wystarcza."""
    src = (
        "definicja Czegoś z elementem:\n"
        "    wartość (element)\n"
        "\n"
        "Rezultat to Coś albo Nic\n"
        "\n"
        "aby brać coś:\n"
        "    zwróć Coś o wartości coś\n"
        "\n"
        "aby przetwarzać x:\n"
        "    y to brałbyś x?\n"
        "    zwróć y\n"
    )
    with pytest.raises(typechecker.TypeCheckError,
                       match="Rezultat to Sukces albo Błąd"):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_try_call_in_function_without_return_raises(parse):
    """Funkcja używająca `?` bez żadnego `zwróć` → ret Nic vs Błąd —
    konflikt (jak Rust: `?` wymaga zwracania Rezultatu)."""
    src = _TRY_PRELUDE + (
        "aby przetwarzać części:\n"
        "    napis to wybrałbyś zero z części?\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_try_call_with_conflicting_annotation_raises(parse):
    src = _TRY_PRELUDE + (
        "aby przetwarzać części -> Tekst:\n"
        "    napis to wybrałbyś zero z części?\n"
        "    zwróć napis\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


# =====================================================================
# Literały logiczne `prawda` / `fałsz` — Przełącznik
# =====================================================================


def test_resolve_bool_literal():
    t = typechecker.resolve_expression(ast.BoolLit(True), typechecker.Scope())
    assert ty(t) == "Przełącznik"


@pytest.mark.integration
def test_bool_literal_types_as_przelacznik(parse):
    src = (
        "aby działać:\n"
        "    flaga to prawda\n"
        "    jeśli flaga:\n"
        "        flaga to fałsz\n"
        "    dopóki fałsz:\n"
        "        flaga to prawda\n"
    )
    typechecker.resolve_module(parse(src))
    assert _var_types()["flaga"] == "Przełącznik"


@pytest.mark.integration
def test_bool_literal_conflict_raises(parse):
    src = (
        "aby działać:\n"
        "    x to prawda\n"
        "    x to pięć\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_inflected_bool_literal_as_argument(parse):
    """`przyjmuj prawdę` — odmieniony literał jako argument (case None,
    dopasowanie pozycyjne jak INT_LIT); grounding w działać przechodzi."""
    src = (
        "aby przyjmować flagę -> Przełącznik:\n"
        "    zwróć flaga\n"
        "\n"
        "aby działać:\n"
        "    x to przyjmuj prawdę\n"
    )
    typechecker.resolve_module(parse(src))


# =====================================================================
# Typy strzałkowe i `zastosuj` (funkcje wyższego rzędu)
# =====================================================================


def test_arrow_unification_propagates_args_and_ret():
    a, r = typechecker.new_type(), typechecker.new_type()
    f1 = typechecker.arrow([a], r)
    f2 = typechecker.arrow([conc("Liczba")], conc("Tekst"))
    typechecker.unify_types(f1, f2)
    assert ty(a) == "Liczba"
    assert ty(r) == "Tekst"


def test_arrow_arity_mismatch_raises_readable():
    f1 = typechecker.arrow([conc("Liczba")], conc("Tekst"))
    f2 = typechecker.arrow([conc("Liczba"), conc("Liczba")], conc("Tekst"))
    with pytest.raises(typechecker.TypeCheckError,
                       match="liczba argumentów"):
        typechecker.unify_types(f1, f2)


def test_arrow_repr_readable():
    f = typechecker.arrow([conc("Liczba"), conc("Tekst")], conc("Nic"))
    assert repr(typechecker.find_type(f)) == "(Liczba, Tekst) → Nic"


def test_arrow_does_not_widen_into_union():
    """Strzałka nie należy do żadnej unii — widening odpada błędem,
    nie cichym rozszerzeniem."""
    f = typechecker.arrow([conc("Liczba")], conc("Tekst"))
    with pytest.raises(typechecker.TypeCheckError, match="cannot unify"):
        typechecker.unify_types(f, conc("Błąd"), widen=True)


def test_instantiate_arrow_in_signature_gets_fresh_vars():
    """Sygnatura z parametrem-strzałką generyczną: każda instancja dostaje
    niezależne zmienne (rank-1 per call-site)."""
    el = typechecker.new_type()
    fdt = typechecker.FunDefTypes(
        name=None, arg_types=[typechecker.arrow([el], el)], ret_type=el)
    (f1,), r1 = typechecker.instantiate(fdt)
    (f2,), r2 = typechecker.instantiate(fdt)
    typechecker.unify_types(f1, typechecker.arrow([conc("Liczba")],
                                                  typechecker.new_type()))
    assert ty(r1) == "Liczba"
    assert ty(r2) == "?"  # druga instancja niezależna


# ---------- integracja: referencje gerundialne + zastosuj ----------


_FOLD_SRC = (
    "definicja Węzła z elementem:\n"
    "    głowa (element)\n"
    "    ogon (Lista)\n"
    "\n"
    "definicja PustejListy:\n"
    "    znacznik (Liczba)\n"
    "\n"
    "Lista to Węzeł albo PustaLista\n"
    "\n"
    "aby dodawać pierwszą do drugiej:\n"
    "    zwróć pierwsza plus druga\n"
    "\n"
    "aby złożyć listę z operacją z akumulatorem:\n"
    "    lista jest:\n"
    "        Węzłem z głową z ogonem:\n"
    "            wynik to złóż ogon z operacją z akumulatorem\n"
    "            zwróć zastosuj operację z głową z wynikiem\n"
    "        PustąListą:\n"
    "            zwróć akumulator\n"
    "\n"
)


@pytest.mark.integration
def test_fold_with_gerund_ref_typechecks(parse):
    """Fold przekazujący `z dodawaniem` (referencja do `dodawać`) typuje
    się end-to-end; suma jest Liczbą."""
    src = _FOLD_SRC + (
        "aby działać:\n"
        "    liczby to Węzeł o głowie jeden o ogonie (PustaLista o znaczniku zero)\n"
        "    suma to złóż liczby z dodawaniem z zero\n"
        "    suma to suma plus jeden\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)  # nie rzuca
    assert _var_types()["suma"] == "Liczba"


@pytest.mark.integration
def test_function_ref_forward_declared(parse):
    """Referencja do funkcji zdefiniowanej PONIŻEJ — fixpoint + PASS 1."""
    src = (
        "aby działać:\n"
        "    operacja to mnożenie\n"
        "    wynik to zastosuj operację z dwa z trzy\n"
        "    wynik to wynik plus jeden\n"
        "\n"
        "aby mnożyć pierwszą przez drugą:\n"
        "    zwróć pierwsza razy druga\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)  # nie rzuca


@pytest.mark.integration
def test_function_ref_to_extern(parse):
    src = (
        "można zakodować liczbę (Liczba) -> Tekst\n"
        "\n"
        "aby działać:\n"
        "    kod to zastosuj zakodowanie z pięć\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)
    assert _var_types()["kod"] == "Tekst"


@pytest.mark.integration
def test_apply_wrong_arity_errors(parse):
    src = (
        "aby mnożyć pierwszą przez drugą:\n"
        "    zwróć pierwsza razy druga\n"
        "\n"
        "aby działać:\n"
        "    wynik to zastosuj mnożenie z dwa\n"
    )
    module = parse(src)
    with pytest.raises(typechecker.TypeCheckError,
                       match="przekazuje 1 argument"):
        typechecker.resolve_module(module)


@pytest.mark.integration
def test_apply_non_function_value_errors(parse):
    src = (
        "aby działać:\n"
        "    liczba to pięć\n"
        "    wynik to zastosuj liczbę z dwa\n"
    )
    module = parse(src)
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(module)


@pytest.mark.integration
def test_try_apply_requires_rezultat(parse):
    src = (
        "aby polubić wpis:\n"
        "    zwróć wpis\n"
        "\n"
        "aby przepuszczać operację przez wartość:\n"
        "    wynik to zastosowałbyś operację z wartością?\n"
        "    zwróć wynik\n"
    )
    module = parse(src)
    with pytest.raises(typechecker.TypeCheckError, match="Rezultat"):
        typechecker.resolve_module(module)


@pytest.mark.integration
def test_try_apply_typechecks_with_rezultat(parse):
    src = (
        "definicja Sukcesu z elementem:\n"
        "    wartość (element)\n"
        "\n"
        "definicja Błędu:\n"
        "    opis (Tekst)\n"
        "\n"
        "Rezultat to Sukces albo Błąd\n"
        "\n"
        # `próbować` zwraca samego Sukcesa — pozycja zwrotu strzałki
        # rozszerza się (widening) do Rezultatu wymaganego przez slot,
        # więc adnotacja `-> Rezultat` nie jest potrzebna.
        "aby próbować wartości:\n"
        "    zwróć Sukces o wartości wartość\n"
        "\n"
        "aby przepuszczać operację przez wartość:\n"
        "    wynik to zastosowałbyś operację z wartością?\n"
        "    zwróć Sukces o wartości wynik\n"
        "\n"
        "aby działać:\n"
        "    całość to przepuszczaj próbowanie przez pięć\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)  # nie rzuca


@pytest.mark.integration
def test_unapplied_generic_ref_in_dzialac_not_grounded(parse):
    """Referencja do funkcji generycznej przypisana w `działać` i nigdy
    nie zastosowana → strzałka z wolną zmienną → istniejący błąd
    groundingu (dodaj adnotację)."""
    src = (
        "aby zwracać x:\n"
        "    zwróć x\n"
        "\n"
        "aby działać:\n"
        "    operacja to zwracanie\n"
    )
    module = parse(src)
    with pytest.raises(typechecker.TypeCheckError, match="adnotację"):
        typechecker.resolve_module(module)


# =====================================================================
# Dopasowanie z gałęzią domyślną `inaczej:`
# =====================================================================


_KWIATKI = (
    "definicja Tulipana:\n"
    "    płatek (Tekst)\n"
    "\n"
    "definicja Róży:\n"
    "    płatek (Tekst)\n"
    "\n"
    "definicja Bratka:\n"
    "    płatek (Tekst)\n"
    "\n"
    "Kwiatki to Róża albo Tulipan albo Bratek\n"
    "\n"
)


@pytest.mark.integration
def test_partial_match_union_from_other_occurrence(parse, capsys):
    """Dwie unie ze wspólnym wariantem: o wyborze decyduje INNE wystąpienie
    zmiennej (przekazanie do funkcji o znanej sygnaturze)."""
    src = (
        "definicja Sukcesu z elementem:\n"
        "    wartość (element)\n"
        "\n"
        "definicja Błędu:\n"
        "    opis (Tekst)\n"
        "\n"
        "definicja Porażki:\n"
        "    powód (Tekst)\n"
        "\n"
        "Rezultat to Sukces albo Błąd\n"
        "Wynik to Sukces albo Porażka\n"
        "\n"
        "aby przyjąć rezultat (Rezultat) -> Tekst:\n"
        "    zwróć \"ok\"\n"
        "\n"
        "aby badać coś:\n"
        "    coś jest:\n"
        "        Sukcesem:\n"
        "            napis to \"sukces\"\n"
        "        inaczej:\n"
        "            napis to \"nie sukces\"\n"
        "    zwróć przyjmij coś\n"
    )
    module = parse(src)
    typechecker.resolve_module(module)
    fdt = _fdt_by_surface(("badać",))
    assert ty(fdt.arg_types[0]) == "Rezultat"


@pytest.mark.integration
def test_partial_match_unresolved_ambiguity_not_grounded(parse):
    """Ten sam setup bez zawężającego wystąpienia — zmienna w `działać`
    zostaje ambiguity-setem {Rezultat|Wynik} → istniejący grounding."""
    src = (
        "definicja Sukcesu z elementem:\n"
        "    wartość (element)\n"
        "\n"
        "definicja Błędu:\n"
        "    opis (Tekst)\n"
        "\n"
        "definicja Porażki:\n"
        "    powód (Tekst)\n"
        "\n"
        "Rezultat to Sukces albo Błąd\n"
        "Wynik to Sukces albo Porażka\n"
        "\n"
        "aby wytwarzać coś:\n"
        "    zwróć coś\n"
        "\n"
        "aby działać:\n"
        "    tajemnica to wytwarzaj pięć\n"
        "    tajemnica jest:\n"
        "        Sukcesem:\n"
        "            napis to \"sukces\"\n"
        "        inaczej:\n"
        "            napis to \"nie sukces\"\n"
    )
    module = parse(src)
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(module)


@pytest.mark.integration
def test_partial_match_branches_not_subset_raises(parse):
    src = _KWIATKI + (
        "definicja Psa:\n"
        "    imię (Tekst)\n"
        "\n"
        "aby działać:\n"
        "    kwiatki to Tulipan o płatku \"x\"\n"
        "    kwiatki są:\n"
        "        Tulipanem:\n"
        "            napis to \"t\"\n"
        "        Psem:\n"
        "            napis to \"p\"\n"
        "        inaczej:\n"
        "            napis to \"reszta\"\n"
    )
    module = parse(src)
    with pytest.raises(typechecker.TypeCheckError,
                       match="nie są podzbiorem"):
        typechecker.resolve_module(module)
