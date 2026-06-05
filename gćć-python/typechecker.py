import ast_nodes as ast
import re
import contextlib
import io
from dataclasses import dataclass, field

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
        return f"{self.head}[{', '.join(map(repr, self.args))}]"


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

def unify_types(t0, t1):
    ft0 = find_type(t0)
    ft1 = find_type(t1)
    if ft0 is ft1:
        return ft0
    if isinstance(ft0, VariantVar) and isinstance(ft1, VariantVar):
        common = ft0.variants & ft1.variants
        if len(common) == 0:
            raise TypeCheckError(f"cannot unify {ft0} with {ft1}")
        # Reużyj istniejący węzeł, gdy przecięcie równa się jednej ze stron —
        # w stanie ustalonym (fixpoint) przecięcia są co przebieg równe, więc
        # to całkowicie zatrzymuje rośnięcie łańcuchów .next (zero śmieci).
        if common == ft0.variants:
            ft1.next = ft0
            return ft0
        if common == ft1.variants:
            ft0.next = ft1
            return ft1
        # Przecięcie ściśle mniejsze od obu — dopiero teraz nowy węzeł.
        new_variant = VariantVar(variants=common)
        ft0.next = new_variant
        ft1.next = new_variant
        return new_variant
    # Co najmniej jedna strona to wolna zmienna — przepnij ją na drugą.
    concrete, abstract = (ft0, ft1) if isinstance(ft0, VariantVar) else (ft1, ft0)
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
        if isinstance(t, VariantVar):
            # Konkret — świeża kopia, by unifikacja w call-site nie mutowała schematu.
            # AppliedType są niemutowalne (frozen), więc kopiujemy sam zbiór.
            return VariantVar(variants=set(t.variants))
        if t not in subst:
            subst[t] = new_type()
        return subst[t]
    return [fresh(a) for a in fdt.arg_types], fresh(fdt.ret_type)

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
            for i, p in enumerate(decl.params):
                if p.type is not None:
                    unify_types(fdt.arg_types[i], variant(["".join(p.type.head)]))
            if decl.return_type is not None:
                unify_types(fdt.ret_type, variant(["".join(decl.return_type.head)]))
            fun_decls.append((decl.name, fdt))
            module_funcs.append((decl, fdt))

    # PASS 2 (do fixpointu): inferuj ciała, reużywając schematów + all_types.
    fun_scopes = _infer_to_fixpoint(module_funcs)

    for scope in fun_scopes:
        print("===")
        for s in scope.walk():
            for (v, t) in s.types:
                print("")
                print(v, find_type(t))


def _infer_bodies(module_funcs, scopes):
    """Jeden przebieg inferencji ciał na TRWAŁYCH scope'ach. Lokalne zmienne
    przeżywają między przebiegami, więc zawężenia (np. twoja_stara → Człowiek)
    propagują się do fixpointu. declare/get_type są idempotentne, a unifikacje
    monotoniczne (tylko przecinają/wiążą), więc ponowne przejście jest bezpieczne."""
    for (decl, _), scope in zip(module_funcs, scopes):
        resolve_function_def(decl, scope)


def _type_sig(r):
    return "?" if isinstance(r, TypeVar) else tuple(sorted(repr(a) for a in r.variants))


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
        explicit_t = variant(["".join(node.type.head)])
        return unify_types(expr_t, explicit_t)
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
    unify_types(target_type, value_type)
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
        unify_types(scope.root_fdt.ret_type, t)
    else:
        unify_types(scope.root_fdt.ret_type, variant(["Nic"]))


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
        unify_types(t0, t1)
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
    cur_struct = struct
    result_type = None
    for ident in reversed(chain):
        if cur_struct is None:
            return None
        field = find_field_for_ident(cur_struct, ident)
        if field is None:
            return None
        result_type = "".join(field.type.head)
        cur_struct = find_struct_def(result_type)
    return result_type


def resolve_getter_chain(node, scope):
    print("GetterChain")
    # Najmniej wiemy o ostatnim słowie — jego typ inferujemy z łańcucha.
    # Przedostatnie słowo musi być polem struktury ostatniego, więc kandydaci
    # na typ ostatniego słowa to wszystkie struktury mające to pole.
    penultimate_word = node.chain[-2]
    structs = find_struct_defs_by_field(penultimate_word)
    # pary (nazwa structu = możliwy typ ostatniego słowa, typ całego łańcucha)
    candidates = []
    for s in structs:
        result_type = can_resolve_chain_with_struct(node.chain[:-1], s)
        if result_type is not None:
            candidates.append(("".join(s.name), result_type))
    if not candidates:
        surfaces = " ".join("_".join(w.surface) for w in node.chain)
        print(f"nie można zresolvować łańcucha dopełniaczowego '{surfaces}'")
        raise
    # Zawęź ostatnie słowo do wariantu kandydujących struktur — przecina się
    # z ograniczeniami z innych statementów (np. drugi getter na tej zmiennej).
    last_word_t = unify_types(
        scope.get_type(node.chain[-1]),
        variant(name for name, _ in candidates),
    )
    # Typ zwracany liczymy z AKTUALNIE zresolwowanego typu ostatniego słowa:
    # zostaw tylko kandydatów zgodnych z jego wariantem (gdy wolny — wszystkich).
    if isinstance(last_word_t, VariantVar):
        surviving_heads = {a.head for a in last_word_t.variants}
        surviving = [rt for name, rt in candidates if name in surviving_heads]
    else:
        surviving = [rt for _, rt in candidates]
    return variant(surviving)


def resolve_subscript(node, scope):
    print("Subscript")
    resolve_expression(node.target, scope)
    resolve_expression(node.index, scope)


def find_struct_def(type_name):
    # type_name bywa krotką lemm (z StructCreation) albo sklejonym stringiem
    # (typ ze scope) — "".join normalizuje oba do tej samej postaci.
    target = "".join(type_name)
    for decl in module.body:
        if isinstance(decl, ast.StructDef) and "".join(decl.name) == target:
            return decl
    return None


def find_field(struct_def, field_key):
    for f in struct_def.fields:
        if any(ast.scope_key_matches(field_key, k) for k in f.name.scope_keys):
            return f
    return None


def resolve_struct_creation(node, scope):
    print("StructCreation")
    for a in node.args:
        resolve_struct_arg(a, scope, node)
    return variant(["".join(node.type_name)])


def resolve_struct_arg(node, scope, struct_creation):
    print("StructArg")
    struct_def = find_struct_def(struct_creation.type_name)
    field = find_field(struct_def, node.field_name)
    field_t = variant(["".join(field.type.head)])
    if node.value is not None:
        unify_types(field_t, resolve_expression(node.value, scope))
    else:
        unify_types(field_t, scope.get_type(field.name))


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