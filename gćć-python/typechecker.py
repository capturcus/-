import ast_nodes as ast
import re
import contextlib
import io
from dataclasses import dataclass, field
from type_parser import match_args_to_slots

last_type = 0
type_regex = re.compile(r"t[0-9]+")

# Węzły union-find. eq=False → tożsamość obiektu jest kluczem (hashowalne,
# porównywane po identyczności), bo łączymy je przez wskaźnik `next`.
@dataclass(eq=False, repr=False)
class TypeVar:
    number: int
    next: object = None

    def __repr__(self):
        return f"t{self.number}"

@dataclass(frozen=True)
class AppliedType:
    """Typ konstruktora zaaplikowany do argumentów (zinstancjonowany generyk).

    `head` — nazwa konstruktora (np. "Liczba", "Lista"). `args` — krotka
    argumentów typu (na razie zawsze pusta; parametryzacja dojdzie później).
    frozen=True → hashowalne i porównywane po wartości, więc `AppliedType`
    może być elementem zbioru `VariantVar.variants` i działa przecięcie."""
    head: str
    args: tuple = ()

    def __repr__(self):
        if not self.args:
            return self.head
        # Pokazuj REPREZENTANTA argumentu (find_type), nie zapisaną zmienną —
        # po unifikacji `t35` może już wskazywać np. na Liczbę.
        return f"{self.head}[{', '.join(repr(find_type(x)) for x in self.args)}]"


@dataclass(eq=False, repr=False)
class VariantVar:
    variants: set = field(default_factory=set)  # set[AppliedType]
    next: object = None

    def __repr__(self):
        return "|".join(sorted(repr(a) for a in self.variants)) if self.variants else "⊥"

class TypeCheckError(Exception):
    """Konflikt typów — np. unifikacja dwóch konkretów o pustym przecięciu."""

def variant(heads):
    # Typ konkretny/wariantowy z iterowalnej kolekcji nazw-głów (stringów).
    return VariantVar(variants={AppliedType(h) for h in heads})

def new_type():
    global last_type
    ret = TypeVar(number=last_type, next=None)
    last_type += 1
    return ret

def find_type(t):
    # Reprezentant: idź po `next` aż do końca łańcucha union-find.
    root = t
    while root.next is not None:
        root = root.next
    # Kompresja ścieżki — węzły po drodze wskazują wprost na root, więc
    # żywa ścieżka od zmiennej zostaje krótka, a stare węzły pośrednie
    # przestają być osiągalne (GC). Bez tego łańcuchy rosną co przebieg.
    while t is not root:
        t.next, t = root, t.next
    return root

def _occurs(var, t):
    """Czy `var` (TypeVar) występuje wewnątrz `t` — zapobiega nieskończonym
    typom (np. α = Lista[α]). Schodzi w argumenty AppliedType."""
    t = find_type(t)
    if t is var:
        return True
    if isinstance(t, VariantVar):
        return any(_occurs(var, arg) for a in t.variants for arg in a.args)
    return False


def _widening_union(heads):
    """Głowa zadeklarowanej unii pokrywającej wszystkie `heads` (każda głowa
    jest tą unią albo jej wariantem-strukturą). To jedyna dopuszczana relacja
    podtypowania: struktura < typ wariantowy. Przy wielu kandydatach wygrywa
    najmniejsza (minimalne pokrycie); remis → TypeCheckError. None gdy żadna
    unia nie pokrywa."""
    if module is None:
        return None
    cands = []
    for decl in module.body:
        if not isinstance(decl, ast.UnionDef):
            continue
        uh = "".join(decl.name)
        members = {"".join(m) for m in decl.members}
        if all(h == uh or h in members for h in heads):
            cands.append((len(members), uh))
    if not cands:
        return None
    cands.sort()
    if len(cands) > 1 and cands[0][0] == cands[1][0]:
        opts = " i ".join(sorted(uh for _, uh in cands[:2]))
        raise TypeCheckError(
            f"niejednoznaczne rozszerzenie do typu wariantowego: "
            f"{', '.join(sorted(heads))} pasuje do {opts}"
        )
    return cands[0][1]


def _unify_variants(ft0, ft1, widen=False):
    """Unifikacja dwóch konkretów: przecięcie po GŁOWIE, a dla wspólnych głów
    rekurencyjna unifikacja argumentów (strukturalnie). Przy pustych args
    redukuje się do przecięcia zbiorów (zachowanie sprzed generyków).

    `widen`: przy pustym przecięciu spróbuj rozszerzyć obie strony do
    wspólnej zadeklarowanej unii (struktura < typ wariantowy). Unia nie
    niesie parametrów typu (parametryzacja to sprawa struktur), więc
    argumenty wariantów są przy rozszerzeniu porzucane."""
    by0, by1 = {}, {}
    for a in ft0.variants:
        by0.setdefault(a.head, []).append(a)
    for a in ft1.variants:
        by1.setdefault(a.head, []).append(a)
    common_heads = by0.keys() & by1.keys()
    if not common_heads:
        if widen:
            u = _widening_union(by0.keys() | by1.keys())
            if u is not None:
                u_set = {AppliedType(u, ())}
                # Reużyj stronę będącą już unią (jak optymalizacja niżej) —
                # zero śmieci, gdy fixpoint trafia w ten sam widening co przebieg.
                if u_set == ft0.variants:
                    ft1.next = ft0
                    return ft0
                if u_set == ft1.variants:
                    ft0.next = ft1
                    return ft1
                widened = VariantVar(variants=u_set)
                ft0.next = widened
                ft1.next = widened
                return widened
        raise TypeCheckError(f"cannot unify {ft0} with {ft1}")
    result = set()
    for h in common_heads:
        for a0 in by0[h]:
            for a1 in by1[h]:
                if len(a0.args) != len(a1.args):
                    raise TypeCheckError(
                        f"arity mismatch for {h}: {len(a0.args)} vs {len(a1.args)}")
                for x, y in zip(a0.args, a1.args):
                    unify_types(x, y)
                result.add(AppliedType(h, a0.args))
    # Reużyj istniejący węzeł, gdy wynik równa się jednej ze stron — przy
    # pustych args to dokładnie stara optymalizacja (zero śmieci w fixpoincie).
    if result == ft0.variants:
        ft1.next = ft0
        return ft0
    if result == ft1.variants:
        ft0.next = ft1
        return ft1
    new_variant = VariantVar(variants=result)
    ft0.next = new_variant
    ft1.next = new_variant
    return new_variant


def unify_types(t0, t1, widen=False):
    """`widen=True` dopuszcza rozszerzenie struktura→unia przy konflikcie głów
    — używane na POZYCJACH TOP-LEVEL (przypisanie, return, argument wywołania,
    wartość pola, adnotacja). Rekurencyjna unifikacja argumentów typów jest
    zawsze ścisła (typy parametryzowane są inwariantne)."""
    ft0 = find_type(t0)
    ft1 = find_type(t1)
    if ft0 is ft1:
        return ft0
    if isinstance(ft0, VariantVar) and isinstance(ft1, VariantVar):
        return _unify_variants(ft0, ft1, widen)
    # Co najmniej jedna strona to wolna zmienna — przepnij ją na drugą.
    concrete, abstract = (ft0, ft1) if isinstance(ft0, VariantVar) else (ft1, ft0)
    if isinstance(concrete, VariantVar) and _occurs(abstract, concrete):
        raise TypeCheckError(f"occurs check: {abstract} w {concrete}")
    abstract.next = concrete
    return concrete

class Scope:
    """Węzeł drzewa scope'ów. Korzeń = ciało funkcji; dzieci = ciała bloków
    (`then`/`else`/`body`). Dzieci są trwałe (cache na węźle AST), więc żyją
    między przebiegami fixpointu, a zmienne wprowadzone w gałęzi są lokalne —
    ta sama nazwa w `then` i `else` to różne zmienne."""
    def __init__(self, parent=None):
        self.types = []
        self.parent = parent
        self.children = []
        self.root_fdt = parent.root_fdt if parent else None
        if parent is not None:
            parent.children.append(self)

    def _find_local(self, identifier):
        keys = identifier.scope_keys
        for (v, t) in self.types:
            if any(ast.scope_key_matches(a, b) for a in keys for b in v.scope_keys):
                return t
        return None

    def _find(self, identifier):
        # Czytanie: idź w górę drzewa — widać zmienne z przodków.
        s = self
        while s is not None:
            t = s._find_local(identifier)
            if t is not None:
                return t
            s = s.parent
        return None

    def declare(self, identifier, t):
        # Deklaracja zawsze lokalna (np. typ parametru w korzeniu funkcji).
        if self._find_local(identifier) is None:
            self.types.append((identifier, t))

    def get_type(self, identifier):
        t = self._find(identifier)   # widoczna w przodku → reużyj
        if t is not None:
            return t
        new_t = new_type()           # inaczej → nowa, lokalna w tym węźle
        self.types.append((identifier, new_t))
        return new_t

    def child_for(self, node, role):
        # Trwałe dziecko per blok: cache trzymany NA WĘŹLE AST (identyczność
        # z węzła, slot z roli), więc sąsiednie bloki się nie zlewają i nie
        # trzeba id(node). Tworzone raz, reużywane co przebieg.
        slots = node.__dict__.setdefault("_scopes", {})
        if role not in slots:
            slots[role] = Scope(self)
        return slots[role]

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

@dataclass
class FunDefTypes:
    name: ast.FunctionIdentifier
    arg_types: list
    ret_type: str

fun_decls = []

def find_fdt(func_id):
    global fun_decls
    for (name, fdt) in fun_decls:
        if name.lemmas_set & func_id.lemmas_set:
            return fdt

def instantiate(fdt):
    subst = {}
    def fresh(t):
        t = find_type(t)
        if isinstance(t, TypeVar):
            if t not in subst:
                subst[t] = new_type()
            return subst[t]
        # VariantVar: świeża kopia z REKURENCYJNIE świeżonymi argumentami, żeby
        # funkcja polimorficzna (∀W. (Lista[W], W)→…) dostała niezależne zmienne
        # elementu per call-site. Przy pustych args = stara płytka kopia.
        return VariantVar(variants={
            AppliedType(a.head, tuple(fresh(x) for x in a.args)) for a in t.variants
        })
    return [fresh(a) for a in fdt.arg_types], fresh(fdt.ret_type)


def _is_concrete(t):
    """Czy typ jest W PEŁNI skonkretyzowany: jedna głowa, argumenty rekurencyjnie
    skonkretyzowane. Wolna zmienna (t27) → nie; niejednoznaczny wariant (A|B) → nie."""
    t = find_type(t)
    if isinstance(t, TypeVar):
        return False
    if len(t.variants) != 1:
        return False
    a = next(iter(t.variants))
    return all(_is_concrete(x) for x in a.args)


def _check_grounded(decl, scope):
    """Punkt wejścia (działać) jest wykonywany na konkretnych wartościach, więc
    KAŻDA jego zmienna musi mieć jeden w pełni skonkretyzowany typ — runtime nie
    wie, jak reprezentować zmienną wolną (t27) ani niejednoznaczną (A|B). Funkcje
    generyczne mają wolne zmienne w sygnaturze (to polimorfizm) i NIE są tu
    sprawdzane — konkretyzują się przy wywołaniu, a niedookreślenie wychodzi
    wtedy w scope'ie wołającego (tu)."""
    for s in scope.walk():
        for ident, t in s.types:
            if not _is_concrete(t):
                line = getattr(ident, "line", None)
                raise TypeCheckError(
                    f"nie można wywnioskować konkretnego typu zmiennej "
                    f"'{'_'.join(ident.surface)}' (linia {line}); "
                    f"pozostało {find_type(t)!r} — dodaj adnotację typu"
                )


module = None

def resolve_module(node):
    print("Module")
    global fun_decls
    global module
    module = node
    # PASS 1 (raz): zadeklaruj schematy funkcji. module_funcs to lokalna lista
    # (decl, fdt) — używana w pass 2 zamiast kruchego indeksowania globalnego
    # fun_decls; fun_decls.append zostaje, bo find_fdt po nim chodzi.
    module_funcs = []
    for decl in node.body:
        if isinstance(decl, ast.FunctionDef):
            fdt = FunDefTypes(
                name=decl.name,
                arg_types=[new_type() for _ in range(len(decl.params))],
                ret_type=new_type()
            )
            fenv = {}  # niejawne parametry typu funkcji: nieznana mała-litera → świeża zmienna
            for i, p in enumerate(decl.params):
                if p.type is not None:
                    unify_types(fdt.arg_types[i], elaborate(p.type, fenv, fresh_unknown=True))
            if decl.return_type is not None:
                unify_types(fdt.ret_type, elaborate(decl.return_type, fenv, fresh_unknown=True))
            fun_decls.append((decl.name, fdt))
            module_funcs.append((decl, fdt))
        elif isinstance(decl, ast.ExternFunctionDef):
            # Extern: sygnatura w całości jawna (wymusza to parser), brak
            # ciała do inferencji — schemat budowany wprost z adnotacji.
            # Wspólny fenv: nieznana głowa (np. Miejsce) działa jak parametr
            # typu współdzielony w obrębie sygnatury.
            fenv = {}
            fdt = FunDefTypes(
                name=decl.name,
                arg_types=[
                    elaborate(p.type, fenv, fresh_unknown=True)
                    for p in decl.params
                ],
                ret_type=elaborate(decl.return_type, fenv, fresh_unknown=True),
            )
            fun_decls.append((decl.name, fdt))

    # PASS 2 (do fixpointu): inferuj ciała, reużywając schematów + all_types.
    fun_scopes = _infer_to_fixpoint(module_funcs)

    for scope in fun_scopes:
        print("===")
        for s in scope.walk():
            for (v, t) in s.types:
                print("")
                print(v, find_type(t))

    # Punkty wejścia (działać) są wykonywane — ich zmienne muszą być w pełni
    # skonkretyzowane (HM "type annotations needed" / Rust E0282).
    for (decl, _), scope in zip(module_funcs, fun_scopes):
        if ("działać",) in decl.name.lemmas_set:
            _check_grounded(decl, scope)


def _infer_bodies(module_funcs, scopes):
    """Jeden przebieg inferencji ciał na TRWAŁYCH scope'ach. Lokalne zmienne
    przeżywają między przebiegami, więc zawężenia (np. twoja_stara → Człowiek)
    propagują się do fixpointu. declare/get_type są idempotentne, a unifikacje
    monotoniczne (tylko przecinają/wiążą), więc ponowne przejście jest bezpieczne."""
    for (decl, _), scope in zip(module_funcs, scopes):
        resolve_function_def(decl, scope)


def _type_sig(r):
    # Strukturalna sygnatura: wolne zmienne → '?' (normalizuje dryf numerów tN
    # między przebiegami, żeby fixpoint dla typów parametryzowanych zbiegał),
    # rekurencyjnie w argumenty AppliedType. Sortuj po głowie (unikalna w zbiorze).
    r = find_type(r)
    if isinstance(r, TypeVar):
        return "?"
    return tuple(sorted(
        ((a.head, tuple(_type_sig(x) for x in a.args)) for a in r.variants),
        key=lambda e: e[0],
    ))


def _signature(module_funcs, scopes):
    """Sygnatura całego stanu: schematy funkcji + typy WSZYSTKICH zmiennych
    lokalnych. Wolne zmienne znormalizowane do '?'. Lokale muszą tu być, bo
    inaczej pętla zatrzyma się gdy ustabilizują się same schematy — zanim
    zawężenia lokalne dojdą do fixpointu. Równość dwóch kolejnych = fixpoint."""
    sig = []
    for (_, fdt) in module_funcs:
        for t in list(fdt.arg_types) + [fdt.ret_type]:
            sig.append(_type_sig(find_type(t)))
    for root in scopes:
        for s in root.walk():
            for (_, t) in s.types:
                sig.append(_type_sig(find_type(t)))
    return tuple(sig)


def _infer_to_fixpoint(module_funcs):
    cap = 2 * len(module_funcs) + 5
    # Trwałe scope per funkcja — tworzone RAZ, reużywane co przebieg.
    scopes = []
    for (_, fdt) in module_funcs:
        scope = Scope()
        scope.root_fdt = fdt
        scopes.append(scope)
    prev = None
    for _ in range(cap):
        _infer_bodies(module_funcs, scopes)
        sig = _signature(module_funcs, scopes)
        if sig == prev:
            return scopes
        prev = sig
    print(f"OSTRZEŻENIE: typecheck nie osiągnął fixpointu po {cap} przebiegach")
    return scopes


def resolve_function_def(node, scope):
    print("FunctionDef")
    for i, p in enumerate(node.params):
        scope.declare(p.name, scope.root_fdt.arg_types[i])
    for stmt in node.body:
        resolve_statement(stmt, scope)


def resolve_statement(node, scope):
    if isinstance(node, ast.Assignment):
        resolve_assignment(node, scope)
    if isinstance(node, ast.If):
        resolve_if(node, scope)
    if isinstance(node, ast.While):
        resolve_while(node, scope)
    if isinstance(node, ast.For):
        resolve_for(node, scope)
    if isinstance(node, ast.Match):
        resolve_match(node, scope)
    if isinstance(node, ast.Return):
        resolve_return(node, scope)
    resolve_expression(node, scope)


def resolve_expression(node, scope):
    if isinstance(node, ast.Phrase):
        node = node.resolved
    if isinstance(node, ast.Word):
        node = node.value
    if isinstance(node, ast.Typed):
        expr_t = resolve_expression(node.expr, scope)
        explicit_t = elaborate(node.type, {}, fresh_unknown=True)
        return unify_types(expr_t, explicit_t, widen=True)
    if isinstance(node, ast.BinOp):
        return resolve_bin_op(node, scope)
    if isinstance(node, ast.UnaryOp):
        return resolve_unary_op(node, scope)
    if isinstance(node, ast.Not):
        return resolve_not(node, scope)
    if isinstance(node, ast.And):
        return resolve_and(node, scope)
    if isinstance(node, ast.Or):
        return resolve_or(node, scope)
    if isinstance(node, ast.FunctionCall):
        return resolve_function_call(node, scope)
    if isinstance(node, ast.GetterChain):
        return resolve_getter_chain(node, scope)
    if isinstance(node, ast.Subscript):
        return resolve_subscript(node, scope)
    if isinstance(node, ast.StructCreation):
        return resolve_struct_creation(node, scope)
    if isinstance(node, ast.StructArg):
        raise
    if isinstance(node, ast.Identifier):
        return resolve_identifier(node, scope)
    if isinstance(node, ast.IntLit):
        print("IntLit")
        return variant(["Liczba"])
    if isinstance(node, ast.StrLit):
        print("StrLit")
        return variant(["Tekst"])

def resolve_assignment(node, scope):
    print("Assignment")
    target_type = resolve_expression(node.target.resolved, scope)
    value_type = resolve_expression(node.value.resolved, scope)
    unify_types(target_type, value_type, widen=True)
    # # target to krotka — element pojedynczy lub łańcuch getterów
    # if isinstance(node.target, tuple):
    #     for t in node.target:
    #         check(t)
    # else:
    #     check(node.target)
    # check(node.value)


# Operatory porównania (CMP_OP) zwracają Przełącznik; arytmetyczne — Liczbę.
_COMPARISON_OPS = {"<", ">", "<=", ">=", "=", "!="}

def resolve_bin_op(node, scope):
    print("BinOp")
    t0 = resolve_expression(node.left, scope)
    t1 = resolve_expression(node.right, scope)
    unify_types(t0, t1)
    if node.op in _COMPARISON_OPS:
        return variant(["Przełącznik"])
    unify_types(t0, variant(["Liczba"]))
    return t0


def resolve_unary_op(node, scope):
    print("UnaryOp")
    t = resolve_expression(node.operand, scope)
    unify_types(t, variant(["Liczba"]))
    return t


def resolve_if(node, scope):
    print("If")
    t = resolve_expression(node.cond, scope)
    unify_types(t, variant(["Przełącznik"]))
    then_scope = scope.child_for(node, "then")
    for stmt in node.then_body:
        resolve_statement(stmt, then_scope)
    else_scope = scope.child_for(node, "else")
    for stmt in node.else_body:
        resolve_statement(stmt, else_scope)


def resolve_while(node, scope):
    print("While")
    t = resolve_expression(node.cond, scope)
    unify_types(t, variant(["Przełącznik"]))
    body_scope = scope.child_for(node, "body")
    for stmt in node.body:
        resolve_statement(stmt, body_scope)


def resolve_for(node, scope):
    print("For")
    resolve_expression(node.collection, scope)
    body_scope = scope.child_for(node, "body")
    body_scope.get_type(node.var)
    for stmt in node.body:
        resolve_statement(stmt, body_scope)


def resolve_return(node, scope):
    print("Return")
    if node.value is not None:
        t = resolve_expression(node.value, scope)
        # widen: gałęzie zwracające różne warianty jednej unii typują
        # funkcję tą unią; warianty bez wspólnej unii → TypeCheckError.
        unify_types(scope.root_fdt.ret_type, t, widen=True)
    else:
        unify_types(scope.root_fdt.ret_type, variant(["Nic"]))


def _union_for_match(subject_t, branch_heads, line):
    """Unia, do której należy subject `czym jest`. Kandydaci: unie, których
    zbiór wariantów RÓWNA SIĘ zbiorowi gałęzi (każdy wariant unii musi mieć
    gałąź — wyczerpujące dopasowanie; gałąź spoza unii też dyskwalifikuje).
    Przy wielu kandydatach rozstrzyga znany typ subjectu. Gdy brak kandydata,
    a typ subjectu to znana unia — komunikat wskazuje brakujące/nadmiarowe
    gałęzie."""
    branch_set = set(branch_heads)
    ft = find_type(subject_t)
    subj_head = None
    if isinstance(ft, VariantVar) and len(ft.variants) == 1:
        subj_head = next(iter(ft.variants)).head
    cands = [
        decl for decl in module.body
        if isinstance(decl, ast.UnionDef)
        and {"".join(m) for m in decl.members} == branch_set
    ]
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        for c in cands:
            if "".join(c.name) == subj_head:
                return c
        opts = ", ".join(sorted("".join(c.name) for c in cands))
        raise TypeCheckError(
            f"gałęzie 'czym jest' (linia {line}) pasują do wielu typów "
            f"wariantowych: {opts} — dodaj adnotację typu")
    if subj_head is not None:
        ud = find_union_def((subj_head,))
        if ud is not None:
            members = {"".join(m) for m in ud.members}
            problems = []
            missing = members - branch_set
            if missing:
                problems.append(f"brakuje gałęzi: {', '.join(sorted(missing))}")
            extra = branch_set - members
            if extra:
                problems.append(
                    f"gałęzie spoza unii: {', '.join(sorted(extra))}")
            raise TypeCheckError(
                f"'czym jest' (linia {line}) na typie '{subj_head}': "
                f"{'; '.join(problems)}")
    raise TypeCheckError(
        f"gałęzie 'czym jest' (linia {line}) — "
        f"{', '.join(sorted(branch_set))} — nie odpowiadają wariantom "
        f"żadnego zadeklarowanego typu wariantowego")


def resolve_match(node, scope):
    print("Match")
    subject_t = resolve_expression(node.subject, scope)
    branch_heads = []
    for br in node.branches:
        h = "".join(br.type_name)
        if h in branch_heads:
            raise TypeCheckError(
                f"powtórzona gałąź '{h}' w 'czym jest' (linia {node.line})")
        branch_heads.append(h)
    ud = _union_for_match(subject_t, branch_heads, node.line)
    unify_types(
        subject_t,
        VariantVar(variants={AppliedType("".join(ud.name), ())}),
        widen=True,
    )
    for br in node.branches:
        sd = find_struct_def(br.type_name)
        # Świeża instancja per gałąź: unia nie niesie parametrów typu, więc
        # pola-parametry wariantu zaczynają jako wolne zmienne i konkretyzują
        # się przez użycie w ciele gałęzi.
        _, env = instantiate_struct(sd)
        br_scope = scope.child_for(br, "body")
        for fid in br.fields:
            field = find_field_for_ident(sd, fid)
            if field is None:
                raise TypeCheckError(
                    f"'{'_'.join(fid.surface)}' nie jest polem struktury "
                    f"'{'_'.join(br.type_name)}' (linia {br.line})")
            br_scope.declare(fid, elaborate(field.type, env))
        for stmt in br.body:
            resolve_statement(stmt, br_scope)


def resolve_not(node, scope):
    print("Not")
    t = resolve_expression(node.operand, scope)
    unify_types(t, variant(["Przełącznik"]))
    return t


def resolve_and(node, scope):
    print("And")
    t0 = resolve_expression(node.left, scope)
    t1 = resolve_expression(node.right, scope)
    unify_types(t0, t1)
    unify_types(t0, variant(["Przełącznik"]))
    return t0


def resolve_or(node, scope):
    print("Or")
    t0 = resolve_expression(node.left, scope)
    t1 = resolve_expression(node.right, scope)
    unify_types(t0, t1)
    unify_types(t0, variant(["Przełącznik"]))
    return t0


def resolve_function_call(node, scope):
    print("FunctionCall")
    fdt = find_fdt(node.name)
    arg_types, ret_type = instantiate(fdt)
    for (t0, p) in zip(arg_types, node.params):
        t1 = resolve_expression(p, scope)
        unify_types(t0, t1, widen=True)
    return ret_type


def find_field_for_ident(struct_def, ident):
    for key in ident.scope_keys:
        f = find_field(struct_def, key)
        if f is not None:
            return f
    return None

def find_struct_defs_by_field(field_name):
    ret = []
    for decl in module.body:
        if isinstance(decl, ast.StructDef):
            if not find_field_for_ident(decl, field_name) is None:
                ret.append(decl)
    return ret

def can_resolve_chain_with_struct(chain, struct):
    """Czy `chain` (ogniwa łańcucha dopełniaczowego BEZ ostatniego słowa,
    w kolejności od tyłu do przodu) daje się zresolvować, gdy ostatnie słowo ma typ
    `struct`? Zwraca typ całego łańcucha (typ pola ogniwa chain[0]) jeśli się
    udało, inaczej None.

    Idziemy od najpóźniejszego ogniwa (chain[-1] — pole `struct`) ku
    najwcześniejszemu (chain[0]). Typ każdego pola wyznacza strukturę,
    w której szukamy ogniwa poprzedzającego; gdy pole nie jest strukturą,
    a łańcuch chce iść dalej — nie pasuje (None)."""
    base_inst, cur_env = instantiate_struct(struct)
    cur_struct = struct
    result_t = None
    for ident in reversed(chain):
        if cur_struct is None:
            return None
        field = find_field_for_ident(cur_struct, ident)
        if field is None:
            return None
        result_t = elaborate(field.type, cur_env)   # pole-parametr → zmienna instancji
        cur_struct, cur_env = _as_struct(result_t)   # zejdź głębiej, jeśli pole to struktura
    return base_inst, result_t


def resolve_getter_chain(node, scope):
    print("GetterChain")
    # Najmniej wiemy o ostatnim słowie — jego typ inferujemy z łańcucha.
    # Przedostatnie słowo musi być polem struktury ostatniego, więc kandydaci
    # na typ ostatniego słowa to wszystkie struktury mające to pole.
    penultimate_word = node.chain[-2]
    structs = find_struct_defs_by_field(penultimate_word)
    # trójki (struktura, jej świeża instancja, typ wynikowy całego łańcucha)
    candidates = []
    for s in structs:
        res = can_resolve_chain_with_struct(node.chain[:-1], s)
        if res is not None:
            base_inst, result_t = res
            candidates.append((s, base_inst, result_t))
    if not candidates:
        surfaces = " ".join("_".join(w.surface) for w in node.chain)
        print(f"nie można zresolvować łańcucha dopełniaczowego '{surfaces}'")
        raise
    # Zawęź ostatnie słowo do unii instancji kandydatów — strukturalna unifikacja
    # przecina po głowie I wiąże argumenty (np. drugi getter na tej zmiennej).
    base_union = set()
    for _, base_inst, _ in candidates:
        base_union |= base_inst.variants
    last_word_t = find_type(unify_types(
        scope.get_type(node.chain[-1]), VariantVar(variants=base_union)))
    surv_heads = ({a.head for a in last_word_t.variants}
                  if isinstance(last_word_t, VariantVar) else None)
    surviving = [rt for s, _, rt in candidates
                 if surv_heads is None or "".join(s.name) in surv_heads]
    if len(surviving) == 1:
        return surviving[0]   # jednoznaczny kandydat — zachowaj parametr (zmienną)
    # Wielu ocalałych → unia konkretnych głów ich typów wynikowych (jak dawniej:
    # np. imię z UżytkownikSerwis|Pies → Tekst, z Człowiek → Liczba ⇒ Tekst|Liczba).
    union = set()
    for rt in surviving:
        rt = find_type(rt)
        if isinstance(rt, VariantVar):
            union |= rt.variants
    return VariantVar(variants=union) if union else surviving[0]


def resolve_subscript(node, scope):
    print("Subscript")
    resolve_expression(node.target, scope)
    resolve_expression(node.index, scope)


def find_struct_def(type_name):
    # type_name bywa krotką lemm (z StructCreation) albo sklejonym stringiem
    # (typ ze scope) — "".join normalizuje oba do tej samej postaci.
    return _find_type_decl(type_name, ast.StructDef)


def find_union_def(type_name):
    return _find_type_decl(type_name, ast.UnionDef)


def _find_type_decl(type_name, decl_cls):
    if module is None:
        return None
    target = "".join(type_name)
    for decl in module.body:
        if isinstance(decl, decl_cls) and "".join(decl.name) == target:
            return decl
    return None


def find_field(struct_def, field_key):
    for f in struct_def.fields:
        if any(ast.scope_key_matches(field_key, k) for k in f.name.scope_keys):
            return f
    return None


BUILTINS = {"Liczba", "Tekst", "Przełącznik", "Nic", "Znak"}


def _struct_env(struct_def, args):
    """Mapa nazwa-parametru (lemma) → węzeł typu, z `args` (równoległe do params)."""
    env = {}
    for p, a in zip(struct_def.params, args):
        for lemmas in p.name.lemmas_set:
            env["".join(lemmas)] = a
    return env


def instantiate_struct(struct_def):
    """Świeża instancja struktury: AppliedType(name, (α1..αn)) + env param→αi."""
    fresh = [new_type() for _ in struct_def.params]
    inst = VariantVar(variants={AppliedType("".join(struct_def.name), tuple(fresh))})
    return inst, _struct_env(struct_def, fresh)


def elaborate(tref, env, fresh_unknown=False):
    """TypeRef (składnia) → węzeł typu (semantyka), względem `env` (nazwa
    parametru → węzeł). Głowa będąca parametrem → jego węzeł. Głowa będąca
    strukturą → AppliedType(name, args ułożone w kolejności parametrów przez
    dopasowanie (prep, case)). Builtin/nieznana 0-arg → konkret. `fresh_unknown`
    (sygnatury funkcji/adnotacje): nieznana mała-litera głowa → świeża zmienna
    (niejawny parametr typu), memoizowana w `env`."""
    h = "".join(tref.head)
    if h in env:
        return find_type(env[h])
    sd = find_struct_def(tref.head)
    if sd is None:
        if find_union_def(tref.head) is not None:
            # Unia jest zawsze 0-arg — parametryzacja to sprawa struktur.
            if tref.args:
                raise TypeCheckError(
                    f"typ wariantowy '{h}' nie przyjmuje argumentów typu")
            return VariantVar(variants={AppliedType(h, ())})
        if fresh_unknown and h not in BUILTINS:
            v = new_type()
            env[h] = v
            return v
        return VariantVar(variants={AppliedType(h, ())})
    # struktura: sloty per parametr, argumenty dopasowane (prep, case) i ułożone
    slots = [new_type() for _ in sd.params]
    if tref.args and len(tref.args) == len(sd.params):
        arg_meta = [(ta.prep, ta.case, ta) for ta in tref.args]
        slot_to_arg = match_args_to_slots(
            arg_meta, sd.params,
            on_error=lambda: TypeCheckError(
                f"argumenty typu nie pasują do parametrów '{h}'"))
        for slot_i, arg_i in slot_to_arg.items():
            unify_types(slots[slot_i],
                        elaborate(tref.args[arg_i].type, env, fresh_unknown))
    return VariantVar(variants={AppliedType(h, tuple(slots))})


def _as_struct(result_t):
    """Jeśli `result_t` to pojedyncza struktura (AppliedType), zwróć
    (struct_def, env) do zejścia głębiej w łańcuchu; inaczej (None, None).
    env mapuje parametry struktury na jej AKTUALNE argumenty (nie świeże)."""
    rt = find_type(result_t)
    if isinstance(rt, VariantVar) and len(rt.variants) == 1:
        at = next(iter(rt.variants))
        sd = find_struct_def((at.head,))
        if sd is not None:
            return sd, _struct_env(sd, at.args)
    return None, None


def resolve_struct_creation(node, scope):
    print("StructCreation")
    sd = find_struct_def(node.type_name)
    if sd is None and find_union_def(node.type_name) is not None:
        raise TypeCheckError(
            f"nie można utworzyć wartości typu wariantowego "
            f"'{'_'.join(node.type_name)}' — utwórz jedną z jego struktur")
    if sd is None:
        # Nieznana struktura (builtin / test bez `module`) — zachowanie sprzed generyków.
        for a in node.args:
            resolve_struct_arg(a, scope, node)
        return variant(["".join(node.type_name)])
    inst, env = instantiate_struct(sd)
    node.__dict__["_struct_env"] = env   # env per instancja, dla resolve_struct_arg
    for a in node.args:
        resolve_struct_arg(a, scope, node)
    return inst


def resolve_struct_arg(node, scope, struct_creation):
    print("StructArg")
    struct_def = find_struct_def(struct_creation.type_name)
    if struct_def is None:
        if node.value is not None:
            resolve_expression(node.value, scope)
        return
    field = find_field(struct_def, node.field_name)
    env = struct_creation.__dict__.get("_struct_env", {})
    field_t = elaborate(field.type, env)   # pole-parametr → współdzielona zmienna instancji
    if node.value is not None:
        unify_types(field_t, resolve_expression(node.value, scope), widen=True)
    else:
        unify_types(field_t, scope.get_type(field.name), widen=True)


def resolve_identifier(node, scope):
    return scope.get_type(node)


# _DISPATCH = {
#     ast.Module: resolve_module,
#     ast.FunctionDef: resolve_function_def,
#     ast.ExternFunctionDef: resolve_extern_function_def,
#     ast.Param: resolve_param,
#     ast.StructDef: resolve_struct_def,
#     ast.Field: resolve_field,
#     ast.Phrase: resolve_phrase,
#     ast.Word: resolve_word,
#     ast.Assignment: resolve_assignment,
#     ast.IntLit: resolve_int_lit,
#     ast.StrLit: resolve_str_lit,
#     ast.BinOp: resolve_bin_op,
#     ast.UnaryOp: resolve_unary_op,
#     ast.If: resolve_if,
#     ast.While: resolve_while,
#     ast.For: resolve_for,
#     ast.Break: resolve_break,
#     ast.Continue: resolve_continue,
#     ast.Return: resolve_return,
#     ast.Not: resolve_not,
#     ast.And: resolve_and,
#     ast.Or: resolve_or,
#     ast.FunctionCall: resolve_function_call,
#     ast.GetterChain: resolve_getter_chain,
#     ast.Subscript: resolve_subscript,
#     ast.StructCreation: resolve_struct_creation,
#     ast.StructArg: resolve_struct_arg,
#     ast.Identifier: resolve_identifier,
# }

# statements
#     ast.Assignment: resolve_assignment,
#     ast.If: resolve_if,
#     ast.While: resolve_while,
#     ast.For: resolve_for,
#     ast.Return: resolve_return,


# definitions
#     ast.FunctionDef: resolve_function_def,
#     ast.ExternFunctionDef: resolve_extern_function_def,
#     ast.StructDef: resolve_struct_def,

# expressions
#     ast.BinOp: resolve_bin_op,
#     ast.UnaryOp: resolve_unary_op,
#     ast.Not: resolve_not,
#     ast.And: resolve_and,
#     ast.Or: resolve_or,
#     ast.FunctionCall: resolve_function_call,
#     ast.GetterChain: resolve_getter_chain,
#     ast.Subscript: resolve_subscript,
#     ast.StructCreation: resolve_struct_creation,
#     ast.StructArg: resolve_struct_arg,
#     ast.Identifier: resolve_identifier,
# }