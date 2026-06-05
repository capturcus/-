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
    typechecker.module = None
    yield
    typechecker.last_type = 0
    typechecker.fun_decls = []
    typechecker.module = None


# ---------- helpery ----------

def ty(t):
    """Zresolwowany typ jako wartość porównywalna: '?' dla wolnej zmiennej,
    'A|B' (posortowane warianty) dla konkretu/wariantu."""
    r = typechecker.find_type(t)
    if isinstance(r, typechecker.TypeVar):
        return "?"
    return "|".join(sorted(r.variants))


def conc(*names):
    """Konkret/wariant z podanych nazw (skrót na typechecker.variant)."""
    return typechecker.variant(set(names))


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
    node = ast.Typed(expr=ast.IntLit(1), type_ref=ast.TypeRef(head=("Liczba",)))
    assert ty(typechecker.resolve_expression(node, typechecker.Scope())) == "Liczba"


def test_resolve_typed_conflict_raises():
    node = ast.Typed(expr=ast.IntLit(1), type_ref=ast.TypeRef(head=("Tekst",)))
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
    with pytest.raises(typechecker.TypeCheckError):
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
            ast.Field(name=make_ident("imię", gender="n"), type_ref=ast.TypeRef(head=("Tekst",))),
            ast.Field(name=make_ident("wiek"), type_ref=ast.TypeRef(head=("Liczba",))),
        ],
    )
    typechecker.module = ast.Module(body=[sd])
    assert typechecker.find_struct_def(("Użytkownik",)) is sd
    assert typechecker.find_struct_def(("Nieznany",)) is None


def test_find_field_by_key_and_type():
    sd = ast.StructDef(
        name=("Użytkownik",),
        fields=[
            ast.Field(name=make_ident("imię", gender="n"), type_ref=ast.TypeRef(head=("Tekst",))),
            ast.Field(name=make_ident("wiek"), type_ref=ast.TypeRef(head=("Liczba",))),
        ],
    )
    imie = typechecker.find_field(sd, (("imię",), "sg", "n"))
    assert imie is not None and "".join(imie.type_ref.head) == "Tekst"
    wiek = typechecker.find_field(sd, (("wiek",), "sg", "m"))
    assert wiek is not None and "".join(wiek.type_ref.head) == "Liczba"
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
        "    u to nowy UżytkownikSerwisu o imieniu \"Marcin\" o identyfikatorze cztery\n"
    )
    typechecker.resolve_module(parse(src))  # bez błędu


@pytest.mark.integration
def test_struct_out_of_order_typechecks(parse):
    # odwrócona kolejność pól: gdyby match był pozycyjny, imię dostałoby Liczbę
    # → błąd. Brak błędu dowodzi dopasowania po nazwie i unifikacji per pole.
    src = _STRUCT_DEF + (
        "aby działać:\n"
        "    u to nowy UżytkownikSerwisu o identyfikatorze cztery o imieniu \"Marcin\"\n"
    )
    typechecker.resolve_module(parse(src))  # bez błędu


@pytest.mark.integration
def test_struct_field_type_mismatch_raises(parse):
    src = _STRUCT_DEF + (
        "aby działać:\n"
        "    u to nowy UżytkownikSerwisu o imieniu cztery\n"  # Liczba w pole Tekst
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))


@pytest.mark.integration
def test_struct_shorthand_typechecks(parse):
    # odwzorowanie test_typów.ć: pole imię:Tekst wypełniane zmienną imię:Tekst
    src = _STRUCT_DEF + (
        "aby działać:\n"
        "    imię to \"Marcin\"\n"
        "    użytkownik to nowy UżytkownikSerwisu z imieniem\n"
    )
    typechecker.resolve_module(parse(src))  # bez błędu


@pytest.mark.integration
def test_struct_shorthand_type_mismatch_raises(parse):
    # zmienna imię:Liczba vs pole imię:Tekst → konflikt
    src = _STRUCT_DEF + (
        "aby działać:\n"
        "    imię to pięć\n"
        "    użytkownik to nowy UżytkownikSerwisu z imieniem\n"
    )
    with pytest.raises(typechecker.TypeCheckError):
        typechecker.resolve_module(parse(src))
