import errno
import sys

import ast_nodes as ast
from expression import _field_canonical_lemma
from dataclasses import dataclass, field

# Limit Pythona (~1000 ramek) jest za niski dla tree-walkera: głęboka
# rekursja Ć + limit wypisu (poniżej) potrzebują zapasu.
sys.setrecursionlimit(20000)

# Struktury są referencyjne, więc cykle są konstruowalne — wypis obcina
# się na tej głębokości znacznikiem „…" zamiast rekurencją bez dna.
LIMIT_WYPISU = 1000

class CRuntimeError(Exception):
    """Błąd wykonania z Ć-owym stosem wywołań: `stack` to lista ramek
    (nazwa funkcji, linia bieżącej instrukcji) od zewnętrznej do
    najgłębszej. Budowany na szczycie (`execute`) z `call_stack`,
    zamiast surowego tracebacku Pythona.
    `nazwa` — polska etykieta w wypisie błędu (gćć.py)."""
    nazwa = "BłądWykonania"

    def __init__(self, message, stack):
        super().__init__(message)
        self.stack = stack


# Ć-owy stos wywołań: ramka per wykonywana funkcja Ć. Ramki są zdejmowane
# na ścieżkach SUKCESU; przy błędzie (RuntimeError/RecursionError) stos
# zostaje nietknięty aż do `execute`, które robi migawkę do CRuntimeError.
call_stack = []


def _stack_snapshot():
    return [(f["fn"], f["line"]) for f in call_stack]


class ErrorPropagation(Exception):
    """Gałąź-Błąd wywołania '?' — przerywa funkcję otaczającą, która
    zwraca niesiony Błąd jako swój wynik."""
    def __init__(self, value):
        self.value = value

class _TailCall:
    """Ogonowe `zwróć wywołanie` — trampolina w execute_function podmienia
    argumenty pętli zamiast rekurować (TCO: pętle ogonowe w O(1) stosu
    Pythona i Ć)."""
    __slots__ = ("lemmas", "args")

    def __init__(self, lemmas, args):
        self.lemmas = lemmas
        self.args = args


class Domknięcie:
    """Wartość `zwiąż F z X` — klucz funkcji + zamrożone pierwsze argumenty.
    Aplikacja dokleja resztę (`_rozwiąż_funkcyjną`); ponowne wiązanie
    konkatenuje. Nośnikiem gołej referencji pozostaje sam klucz-krotka."""
    __slots__ = ("klucz", "związane")

    def __init__(self, klucz, związane):
        self.klucz = klucz
        self.związane = związane


def _zwiąż(nośnik, args):
    if isinstance(nośnik, Domknięcie):
        return Domknięcie(nośnik.klucz, nośnik.związane + args)
    return Domknięcie(nośnik, args)


def _rozwiąż_funkcyjną(nośnik, args):
    """Wartość funkcyjna → (lemmas, pełne argumenty) dla execute_function:
    domknięcie dokleja zamrożone argumenty przed podanymi."""
    if isinstance(nośnik, Domknięcie):
        return [nośnik.klucz], nośnik.związane + args
    return [nośnik], args


class ReturnUnwind(Exception):
    """`zwróć` w zagnieżdżonym bloku — przerywa ciało funkcji z wartością."""
    def __init__(self, value):
        self.value = value

class BreakUnwind(Exception):
    """`dość` — przerywa najbliższą pętlę `dopóki`."""

class ContinueUnwind(Exception):
    """`dalej` — przeskakuje do następnej iteracji `dopóki`."""

def _brak_pola(czynność, struct, keys):
    """Błąd odczytu/zapisu pola: nazwa pola i typ wartości zamiast surowych
    scope-keys; lokalizację (linia, funkcja) dokleja `execute` ze stosu."""
    nazwa = min(("_".join(k[0]) for k in keys), default="?")
    return RuntimeError(
        f"{czynność} pola '{nazwa}' z wartości typu '{struct.type}' — "
        f"wartość nie jest wariantem posiadającym to pole")

def _field_value(struct, keys):
    """Wartość pola struktury (RuntimeValue) po scope-keys pola."""
    if tekst_lista is not None:
        _wymuś_tekst(struct)
    if isinstance(struct.value, dict):
        for stored_key, value in struct.value.items():
            if any(ast.scope_key_matches(k, stored_key) for k in keys):
                return value
    raise _brak_pola("odczyt", struct, keys)

def _field_set(struct, keys, value):
    """Zapis pola po scope-keys; konstrukcja jest zawsze pełna, więc brak
    wpisu to błąd interpretera."""
    if tekst_lista is not None:
        _wymuś_tekst(struct)
    if isinstance(struct.value, dict):
        for stored_key in struct.value:
            if any(ast.scope_key_matches(k, stored_key) for k in keys):
                struct.value[stored_key] = value
                return
    raise _brak_pola("zapis", struct, keys)

# Moduł z aliasem `Tekst` (przygrywka) reprezentuje tekst listą znaków:
# (nazwa ogniwa, klucz pola-głowy, klucz pola-ogona). None → moduł bez
# aliasu `Tekst` (literały tekstowe są wtedy nielegalne — typechecker).
tekst_lista = None

# Hierarchia unii: nazwa unii → zbiór LIŚCI (struktur) osiągalnych przez
# zagnieżdżone unie — gałąź-unia dopasowania łapie każdy swój liść.
unie_liście = {}


def _wylicz_unie(module_node):
    człony = {"".join(n.name): ["".join(m) for m in n.members]
              for n in module_node.body if isinstance(n, ast.UnionDef)}

    def liście(u, widziane):
        if u in widziane:
            return set()
        widziane.add(u)
        out = set()
        for m in człony.get(u, ()):
            if m in człony:
                out |= liście(m, widziane)
            else:
                out.add(m)
        return out

    return {u: liście(u, set()) for u in człony}

def _wykryj_tekst_listowy(module_node):
    """Klucze reprezentacji tekstu Z MODUŁU (nie hardkodowane): alias
    `Tekst` → (łańcuch aliasów) → unia → jej członek-struktura o dwóch
    polach, z których dokładnie jedno ma typ tej unii (ogon); drugie to
    głowa. None gdy moduł nie ma aliasu `Tekst` albo kształt się nie
    składa (wtedy literały zostają skalarne)."""
    aliasy = {"".join(n.name): n for n in module_node.body
              if isinstance(n, ast.TypeAlias)}
    alias = aliasy.get("Tekst")
    if alias is None:
        return None
    tref = alias.target
    while "".join(tref.head) in aliasy:
        tref = aliasy["".join(tref.head)].target
    union_name = "".join(tref.head)
    union = next((n for n in module_node.body
                  if isinstance(n, ast.UnionDef)
                  and "".join(n.name) == union_name), None)
    if union is None:
        return None
    member_names = {"".join(m) for m in union.members}
    for n in module_node.body:
        if not isinstance(n, ast.StructDef):
            continue
        if "".join(n.name) not in member_names or len(n.fields) != 2:
            continue
        ogony = [f for f in n.fields
                 if f.type is not None and "".join(f.type.head) == union_name]
        if len(ogony) != 1:
            continue
        głowa = next(f for f in n.fields if f is not ogony[0])
        return ("".join(n.name),
                _field_canonical_lemma(głowa.name),
                _field_canonical_lemma(ogony[0].name))
    return None

class _LeniwyTekst:
    """Kompaktowa reprezentacja tekstu: python-str + offset zamiast
    łańcucha słowników-ogniw. Materializuje się PO JEDNYM OGNIWIE przy
    pierwszym dostępie do pól (match, łańcuch, zapis); wypis, równość
    tekst-tekst i konwersje plikowe idą fast-pathem bez materializacji.
    Literał / odczyt pliku: O(1) zamiast O(n) słowników."""
    __slots__ = ("napis", "start")

    def __init__(self, napis, start=0):
        self.napis = napis
        self.start = start

    def reszta(self):
        return self.napis[self.start:]


def _wymuś_tekst(rv):
    """Zmaterializuj JEDEN poziom leniwego tekstu w miejscu (głowa-Znak
    + leniwy ogon) — wołane przy dostępie do pól."""
    w = rv.value
    if type(w) is _LeniwyTekst:
        ogniwo, klucz_głowy, klucz_ogona = tekst_lista
        następny = w.start + 1
        if następny < len(w.napis):
            ogon = RuntimeValue(
                value=_LeniwyTekst(w.napis, następny), type=ogniwo)
        else:
            ogon = RuntimeValue(value=None, type="Nic")
        rv.value = {
            klucz_głowy: RuntimeValue(value=w.napis[w.start], type="Znak"),
            klucz_ogona: ogon,
        }
    return rv


def _lista_tekstów(napisy):
    """Lista Tekstów (argumenty programu) z pythonowych stringów — te
    same ogniwa co listy przygrywki; pusta lista ≡ Nic."""
    ogniwo, klucz_głowy, klucz_ogona = tekst_lista
    wynik = RuntimeValue(value=None, type="Nic")
    for napis in reversed(napisy):
        wynik = RuntimeValue(
            value={klucz_głowy: _lista_znaków(napis),
                   klucz_ogona: wynik},
            type=ogniwo)
    return wynik

def _lista_znaków(napis):
    """Tekst z pythonowego stringa: leniwa reprezentacja O(1).
    Pusty tekst ≡ Nic (świadoma decyzja przygrywki)."""
    if not napis:
        return RuntimeValue(value=None, type="Nic")
    return RuntimeValue(value=_LeniwyTekst(napis), type=tekst_lista[0])

def _znaki_ogniw(rv):
    """Łańcuch ogniw znaków → python str; None gdy to nie tekst (głowa
    inna niż Znak, urwany łańcuch, cykl/limit — wtedy zwykły wypis
    struktur, który sam się obcina)."""
    ogniwo, klucz_głowy, klucz_ogona = tekst_lista
    znaki = []
    while rv.type == ogniwo:
        if type(rv.value) is _LeniwyTekst:
            znaki.append(rv.value.reszta())
            return "".join(znaki)
        if len(znaki) > LIMIT_WYPISU:
            return None
        głowa = rv.value[klucz_głowy]
        if głowa.type != "Znak":
            return None
        znaki.append(głowa.value)
        rv = rv.value[klucz_ogona]
    if rv.type != "Nic":
        return None
    return "".join(znaki)

def _tekst(rv, depth=0):
    if depth > LIMIT_WYPISU:
        return "…"
    if rv.type == "Przełącznik":
        return "prawda" if rv.value else "fałsz"
    if rv.type == "Nic":
        return "Nic"
    if rv.type == "Funkcja":
        if isinstance(rv.value, Domknięcie):
            return (f"funkcja {'_'.join(rv.value.klucz)} "
                    f"(związane argumenty: {len(rv.value.związane)})")
        return f"funkcja {'_'.join(rv.value)}"
    if type(rv.value) is _LeniwyTekst:
        return rv.value.reszta()
    if isinstance(rv.value, dict):
        if tekst_lista is not None and rv.type == tekst_lista[0]:
            napis = _znaki_ogniw(rv)
            if napis is not None:
                return napis
        fields = ", ".join(f"{'_'.join(k[0])}: {_tekst(v, depth + 1)}"
                           for k, v in rv.value.items())
        return f"{rv.type}({fields})"
    return str(rv.value)

def _podziel(args):
    """Dzielenie całkowitoliczbowe (podłogowe, jak w Pythonie:
    -7 podzielone przez 2 to -4)."""
    dzielna, dzielnik = args
    if dzielnik.value == 0:
        raise RuntimeError("dzielenie przez zero")
    return RuntimeValue(value=dzielna.value // dzielnik.value, type="Liczba")


def _reszta_z_dzielenia(args):
    """Reszta z dzielenia (podłogowa, znak dzielnika — dla dodatniego
    dzielnika zawsze nieujemna)."""
    dzielna, dzielnik = args
    if dzielnik.value == 0:
        raise RuntimeError("reszta z dzielenia przez zero")
    return RuntimeValue(value=dzielna.value % dzielnik.value, type="Liczba")


def _tekst_do_pythona(rv):
    """Ć-owy Tekst (łańcuch ogniw znaków) → python str, bez limitu długości
    (w odróżnieniu od `_znaki_ogniw`, które służy wypisowi). None gdy
    wartość nie jest tekstem."""
    if tekst_lista is None:
        return None
    ogniwo, klucz_głowy, klucz_ogona = tekst_lista
    znaki = []
    widziane = set()
    while rv.type == ogniwo:
        if type(rv.value) is _LeniwyTekst:
            znaki.append(rv.value.reszta())
            return "".join(znaki)
        if id(rv.value) in widziane:   # cykl — to nie tekst
            return None
        widziane.add(id(rv.value))
        głowa = rv.value[klucz_głowy]
        if głowa.type != "Znak":
            return None
        znaki.append(głowa.value)
        rv = rv.value[klucz_ogona]
    if rv.type != "Nic":
        return None
    return "".join(znaki)


# Wartości Sukces/Błąd budowane przez wbudowane funkcje plikowe: klucze
# pól w formie atomowej (lemma, None, None) — `scope_key_matches` dopasuje
# je do każdego odczytu po samej lemmie.
def _sukces(rv):
    return RuntimeValue(value={(("wartość",), None, None): rv},
                        type="Sukces")


def _błąd(opis):
    return RuntimeValue(value={(("opis",), None, None): _lista_znaków(opis)},
                        type="Błąd")


def _zapisz_znakiem(args):
    """chr: punkt kodowy Unicode → Znak. Odpowiednik pythonowego `chr`."""
    kod = args[0].value
    if kod < 0 or kod > 0x10FFFF:
        raise RuntimeError(
            f"punkt kodowy poza zakresem Unicode (0..1114111): {kod}")
    return RuntimeValue(value=chr(kod), type="Znak")


def _zapisz_liczbą(args):
    """ord: Znak → punkt kodowy Unicode. Odpowiednik pythonowego `ord`."""
    return RuntimeValue(value=ord(args[0].value), type="Liczba")


# Polskie opisy typowych błędów systemowych — `strerror` przychodzi
# z systemu po angielsku. Nietypowe errno przechodzą z numerem
# i oryginalnym opisem w nawiasie.
_ERRNO_OPISY = {
    errno.ENOENT: "plik nie istnieje",
    errno.EACCES: "brak uprawnień",
    errno.EISDIR: "to katalog, nie plik",
    errno.ENOTDIR: "składnik ścieżki nie jest katalogiem",
    errno.ENOSPC: "brak miejsca na urządzeniu",
}


def _opis_oserror(e):
    opis = _ERRNO_OPISY.get(e.errno)
    if opis is not None:
        return opis
    return f"błąd systemowy nr {e.errno} ({e.strerror or e})"


def _czytaj_plik(args):
    ścieżka = _tekst_do_pythona(args[0])
    if ścieżka is None:
        return _błąd("ścieżka nie jest tekstem")
    try:
        with open(ścieżka, encoding="utf-8") as f:
            return _sukces(_lista_znaków(f.read()))
    except OSError as e:
        return _błąd(f"nie można odczytać pliku '{ścieżka}': "
                     f"{_opis_oserror(e)}")


def _zapisz_plik(args):
    zawartość = _tekst_do_pythona(args[0])
    ścieżka = _tekst_do_pythona(args[1])
    if zawartość is None or ścieżka is None:
        return _błąd("zawartość i ścieżka muszą być tekstami")
    try:
        with open(ścieżka, "w", encoding="utf-8") as f:
            f.write(zawartość)
        return _sukces(RuntimeValue(
            value=len(zawartość.encode("utf-8")), type="Liczba"))
    except OSError as e:
        return _błąd(f"nie można zapisać pliku '{ścieżka}': "
                     f"{_opis_oserror(e)}")


def _wczytaj_wejście(args):
    """input: jedna linia ze standardowego wejścia (bez końcowego znaku
    nowej linii) jako Tekst. Koniec strumienia (EOF) daje pusty tekst."""
    return _lista_znaków(sys.stdin.readline().removesuffix("\n"))


def _wylosuj_liczbę(args):
    """randint: losowa liczba całkowita z domkniętego przedziału."""
    import random
    dolna, górna = args[0].value, args[1].value
    if dolna > górna:
        raise RuntimeError(
            f"pusty przedział losowania: od {dolna} do {górna}")
    return RuntimeValue(value=random.randint(dolna, górna), type="Liczba")


# Wbudowane funkcje: implementacja tutaj, sygnatura jako deklaracja
# `można` w programie (przygrywka deklaruje podzielić/wziąć_resztę…/
# czytać_plik/zapisać_plik/wczytać_wejście).
BUILTIN_FUNCTIONS = [
    ([("wypisać",)], lambda args: print(_tekst(args[0]))),
    ([("podzielić",)], _podziel),
    ([("wziąć", "reszta", "z", "dzielenie")], _reszta_z_dzielenia),
    ([("zapisać", "znak")], _zapisz_znakiem),
    ([("zapisać", "liczba")], _zapisz_liczbą),
    ([("czytać", "plik")], _czytaj_plik),
    ([("zapisać", "plik")], _zapisz_plik),
    ([("wczytać", "wejście")], _wczytaj_wejście),
    ([("wylosować", "liczba")], _wylosuj_liczbę),
]

# Builtiny graficzne — oddzielny moduł z leniwym importem pygame, żeby
# interpreter działał bez zainstalowanego pygame. Import cykliczny jest
# bezpieczny: gra_builtins sięga do atrybutów executora tylko w runtime.
import gra_builtins
BUILTIN_FUNCTIONS.extend(gra_builtins.BUILTIN_FUNCTIONS)

# op → (funkcja, typ wyniku); semantyka jak w typechecker.resolve_bin_op
BIN_OPS = {
    "+": (lambda a, b: a + b, "Liczba"),
    "-": (lambda a, b: a - b, "Liczba"),
    "*": (lambda a, b: a * b, "Liczba"),
    "<": (lambda a, b: a < b, "Przełącznik"),
    ">": (lambda a, b: a > b, "Przełącznik"),
    "<=": (lambda a, b: a <= b, "Przełącznik"),
    ">=": (lambda a, b: a >= b, "Przełącznik"),
}

def _równe(a, b, visited=None):
    """Równość STRUKTURALNA (`równe`): skrót tożsamościowy, tag typu,
    wartości proste po wartości, struktury rekurencyjnie po polach.
    Cykle bezpieczne: odwiedzona para słowników uznana za równą
    (koindukcja — różnica i tak wyjdzie na innej ścieżce)."""
    if a is b:
        return True
    if a.type != b.type:
        return False
    if type(a.value) is _LeniwyTekst and type(b.value) is _LeniwyTekst:
        return a.value.reszta() == b.value.reszta()
    if tekst_lista is not None and a.type == tekst_lista[0]:
        # Iteracyjne porównanie łańcuchów znaków (mieszanych: leniwe
        # i zmaterializowane) — rekurencja po ogonach przepełniała stos
        # Pythona na długich tekstach.
        ta, tb = _tekst_do_pythona(a), _tekst_do_pythona(b)
        if ta is not None and tb is not None:
            return ta == tb
    if tekst_lista is not None:
        _wymuś_tekst(a)
        _wymuś_tekst(b)
    if not isinstance(a.value, dict):
        return a.value == b.value
    if visited is None:
        visited = set()
    para = (id(a.value), id(b.value))
    if para in visited:
        return True
    visited.add(para)
    return all(_równe(w, b.value[k], visited) for k, w in a.value.items())

def _tożsame(a, b):
    """Równość REFERENCYJNA (`tożsame`): struktury — ten sam obiekt
    (słownik pól jest nośnikiem tożsamości); wartości proste są
    niemutowalne, więc tożsamość degeneruje się do równości wartości."""
    if isinstance(a.value, dict) or isinstance(b.value, dict):
        return a.value is b.value
    return a.value == b.value

@dataclass
class RuntimeValue:
    value: any
    type: str

@dataclass
class RuntimeScope:
    vars: list = field(default_factory=list)  # [(scope_keys, RuntimeValue)]
    parent: object = None

    def variable_value(self, keys):
        for stored_keys, value in self.vars:
            if any(ast.scope_key_matches(a, b) for a in keys for b in stored_keys):
                return value
        if self.parent is not None:
            return self.parent.variable_value(keys)
        nazwa = min(("_".join(k[0]) for k in keys), default="?")
        raise RuntimeError(f"zmienna '{nazwa}' nieznana w tym zakresie")

    def assign(self, keys, value):
        # Reasignacja tam, gdzie zmienna jest widoczna (także u przodka);
        # niewidoczna nigdzie → deklaracja w bieżącym bloku.
        scope = self
        while scope is not None:
            for i, (stored_keys, _) in enumerate(scope.vars):
                if any(ast.scope_key_matches(a, b) for a in keys for b in stored_keys):
                    scope.vars[i] = (stored_keys, value)
                    return
            scope = scope.parent
        self.vars.append((keys, value))

def execute_expression(expr_node, scope):
    if isinstance(expr_node, ast.StrLit):
        # Typechecker gwarantuje alias `Tekst` w module z literałem
        # tekstowym; None zostaje tylko gdy alias nie opisuje listy znaków.
        if tekst_lista is None:
            raise RuntimeError(
                "literał tekstowy: alias 'Tekst' nie opisuje listy znaków")
        return _lista_znaków(str(expr_node.value))
    if isinstance(expr_node, ast.CharLit):
        return RuntimeValue(value=expr_node.value, type="Znak")
    if isinstance(expr_node, ast.IntLit):
        return RuntimeValue(value=int(expr_node.value), type="Liczba")
    if isinstance(expr_node, ast.BoolLit):
        return RuntimeValue(value=expr_node.value, type="Przełącznik")
    if isinstance(expr_node, ast.Identifier):
        return scope.variable_value(expr_node.scope_keys)
    if isinstance(expr_node, ast.GetterChain):
        value = scope.variable_value(expr_node.chain[-1].scope_keys)
        for fid in reversed(expr_node.chain[:-1]):
            value = _field_value(value, fid.scope_keys)
        return value
    if isinstance(expr_node, ast.FunctionCall):
        evaluated_params = [execute_expression(expr.value, scope) for expr in expr_node.params]
        return execute_function(expr_node.name.lemmas_set, evaluated_params)
    if isinstance(expr_node, ast.FunctionRef):
        return RuntimeValue(value=expr_node.key, type="Funkcja")
    if isinstance(expr_node, ast.Apply):
        fn = execute_expression(expr_node.fn, scope)
        args = [execute_expression(w.value, scope) for w in expr_node.args]
        lemmas, args = _rozwiąż_funkcyjną(fn.value, args)
        return execute_function(lemmas, args)
    if isinstance(expr_node, ast.Bind):
        fn = execute_expression(expr_node.fn, scope)
        args = [execute_expression(w.value, scope) for w in expr_node.args]
        return RuntimeValue(value=_zwiąż(fn.value, args), type="Funkcja")
    if isinstance(expr_node, ast.StructCreation):
        # Jawne `Nic` (konstrukcja bez pól) normalizuje się do kanonicznej
        # wartości None — tej samej, którą daje fall-through funkcji i
        # desugar pustego tekstu; dwie reprezentacje psuły `równe`/`tożsame`.
        if "".join(expr_node.type_name) == "Nic":
            return RuntimeValue(value=None, type="Nic")
        fields = {}
        for arg in expr_node.args:
            if arg.value is None:  # skrót `z polem` — zmienna o nazwie pola
                fields[arg.field_name] = scope.variable_value([arg.field_name])
            else:
                fields[arg.field_name] = execute_expression(arg.value, scope)
        return RuntimeValue(value=fields, type="".join(expr_node.type_name))
    if isinstance(expr_node, ast.TryCall):
        result = execute_expression(expr_node.call, scope)
        if result.type == "Błąd":
            raise ErrorPropagation(result)
        return next(iter(result.value.values()))
    if isinstance(expr_node, ast.BinOp):
        left = execute_expression(expr_node.left, scope)
        right = execute_expression(expr_node.right, scope)
        if expr_node.op == "=":
            return RuntimeValue(value=_równe(left, right), type="Przełącznik")
        if expr_node.op == "!=":
            return RuntimeValue(value=not _równe(left, right), type="Przełącznik")
        if expr_node.op == "≡":
            return RuntimeValue(value=_tożsame(left, right), type="Przełącznik")
        fn, result_type = BIN_OPS[expr_node.op]
        return RuntimeValue(value=fn(left.value, right.value), type=result_type)
    if isinstance(expr_node, ast.UnaryOp):
        operand = execute_expression(expr_node.operand, scope)
        value = operand.value if expr_node.op == "+" else -operand.value
        return RuntimeValue(value=value, type="Liczba")
    if isinstance(expr_node, ast.Not):
        operand = execute_expression(expr_node.operand, scope)
        return RuntimeValue(value=not operand.value, type="Przełącznik")
    if isinstance(expr_node, ast.And):
        left = execute_expression(expr_node.left, scope)
        right = execute_expression(expr_node.right, scope)
        return RuntimeValue(value=left.value and right.value, type="Przełącznik")
    if isinstance(expr_node, ast.Or):
        left = execute_expression(expr_node.left, scope)
        right = execute_expression(expr_node.right, scope)
        return RuntimeValue(value=left.value or right.value, type="Przełącznik")

def execute_function(function_lemmas, args):
  # Trampolina TCO: ogonowe `zwróć wywołanie` wraca tu jako _TailCall
  # i podmienia (function_lemmas, args) bez nowej ramki.
  while True:
    for f in BUILTIN_FUNCTIONS:
        for function_lemma in function_lemmas:
            if function_lemma in f[0]:
                return f[1](args)
    global module_funcs
    function_node = None
    for f in module_funcs:
        for function_lemma in function_lemmas:
            if function_lemma in f.name.lemmas_set:
                function_node = f
    if function_node is None:
        nazwy = ", ".join("_".join(l) for l in function_lemmas)
        raise RuntimeError(f"funkcja '{nazwy}' nie istnieje")
    scope = RuntimeScope()
    scope.vars = [(p.name.scope_keys, value) for p, value in zip(function_node.params, args)]
    # Ramka Ć-owego stosu: zdejmowana na ścieżkach sukcesu; przy wyjątku
    # zostaje — `execute` czyta z niej pełny stos do CRuntimeError.
    call_stack.append({"fn": "_".join(function_node.name.surface), "line": None})
    try:
        execute_block(function_node.body, scope)
    except ReturnUnwind as r:
        call_stack.pop()
        if type(r.value) is _TailCall:
            function_lemmas, args = r.value.lemmas, r.value.args
            continue
        return r.value
    except ErrorPropagation as e:
        call_stack.pop()
        return e.value
    except BreakUnwind:
        raise RuntimeError("'dość' poza pętlą 'dopóki'")
    except ContinueUnwind:
        raise RuntimeError("'dalej' poza pętlą 'dopóki'")
    call_stack.pop()
    return RuntimeValue(value=None, type="Nic")

def _stmt_line(stmt):
    """Linia instrukcji do ramki stosu (Phrase i Match wprost, inne
    z frazy składowej)."""
    if isinstance(stmt, ast.Phrase):
        return stmt.line
    if isinstance(stmt, ast.Assignment):
        return (getattr(stmt.target, "line", None)
                or getattr(stmt.value, "line", None))
    if isinstance(stmt, (ast.If, ast.While)):
        return getattr(stmt.cond, "line", None)
    if isinstance(stmt, ast.Match):
        return stmt.line
    if isinstance(stmt, ast.Return):
        return getattr(stmt.value, "line", None)
    return None


def execute_block(stmts, scope):
    for stmt in stmts:
        line = _stmt_line(stmt)
        if call_stack and line is not None:
            call_stack[-1]["line"] = line
        if isinstance(stmt, ast.Phrase):
            stmt = stmt.resolved
        if isinstance(stmt, ast.FunctionCall):
            evaluated_params = [execute_expression(expr.value, scope) for expr in stmt.params]
            execute_function(stmt.name.lemmas_set, evaluated_params)
        if isinstance(stmt, (ast.Apply, ast.Bind, ast.TryCall)):
            # Gołe `zastosuj F z X` (i pokrewne) jako instrukcja —
            # wykonaj dla efektów; wynik przepada jak przy FunctionCall.
            execute_expression(stmt, scope)
        if isinstance(stmt, ast.Assignment):
            value = execute_expression(stmt.value.resolved, scope)
            target = stmt.target.resolved
            if isinstance(target, ast.Typed):  # adnotacja bez znaczenia w runtime
                target = target.expr
            if isinstance(target, ast.GetterChain):
                owner = scope.variable_value(target.chain[-1].scope_keys)
                for fid in reversed(target.chain[1:-1]):
                    owner = _field_value(owner, fid.scope_keys)
                _field_set(owner, target.chain[0].scope_keys, value)
            else:
                scope.assign(target.scope_keys, value)
        if isinstance(stmt, ast.If):
            cond = execute_expression(stmt.cond.resolved, scope)
            branch = stmt.then_body if cond.value else stmt.else_body
            execute_block(branch, RuntimeScope(parent=scope))
        if isinstance(stmt, ast.While):
            while execute_expression(stmt.cond.resolved, scope).value:
                try:
                    execute_block(stmt.body, RuntimeScope(parent=scope))
                except ContinueUnwind:
                    continue
                except BreakUnwind:
                    break
        if isinstance(stmt, ast.Break):
            raise BreakUnwind()
        if isinstance(stmt, ast.Continue):
            raise ContinueUnwind()
        if isinstance(stmt, ast.Match):
            subject = execute_expression(stmt.subject.resolved, scope)
            for br in stmt.branches:
                if br.type_name is not None:
                    głowa_br = "".join(br.type_name)
                    if (głowa_br != subject.type
                            and subject.type
                            not in unie_liście.get(głowa_br, ())):
                        continue
                br_scope = RuntimeScope(parent=scope)
                for fid in br.fields:
                    br_scope.vars.append((fid.scope_keys, _field_value(subject, fid.scope_keys)))
                if br.alias is not None:
                    br_scope.vars.append((br.alias.scope_keys, subject))
                # Podmiot-zmienna NIE dostaje wpisu w scope gałęzi: odczyty
                # i tak widzą tę samą wartość u przodka, a zapis (`reszta to
                # ogon` — idiom kursora) ma pisać NA ZEWNĄTRZ, jak każda
                # reasignacja. Zawężenie typu podmiotu żyje wyłącznie
                # w typecheckerze (Scope.shadows).
                execute_block(br.body, br_scope)
                break
            else:
                raise RuntimeError(f"żadna gałąź 'jest:' nie pasuje do {subject.type}")
        if isinstance(stmt, ast.Return):
            if stmt.value is None:  # gołe `zwróć`
                raise ReturnUnwind(RuntimeValue(value=None, type="Nic"))
            wynik = stmt.value.resolved
            # Pozycja ogonowa: `zwróć wywołanie` idzie przez trampolinę
            # (argumenty wyewaluowane TERAZ, wywołanie w pętli ramki).
            if isinstance(wynik, ast.FunctionCall):
                params = [execute_expression(e.value, scope)
                          for e in wynik.params]
                raise ReturnUnwind(_TailCall(wynik.name.lemmas_set, params))
            if isinstance(wynik, ast.Apply):
                fn = execute_expression(wynik.fn, scope)
                params = [execute_expression(w.value, scope)
                          for w in wynik.args]
                lemmas, params = _rozwiąż_funkcyjną(fn.value, params)
                raise ReturnUnwind(_TailCall(lemmas, params))
            raise ReturnUnwind(execute_expression(wynik, scope))

def execute(module_node, argumenty=None):
    global module_funcs, tekst_lista, unie_liście
    module_funcs = [node for node in module_node.body if isinstance(node, ast.FunctionDef)]
    tekst_lista = _wykryj_tekst_listowy(module_node)
    unie_liście = _wylicz_unie(module_node)
    call_stack.clear()
    # `działać` opcjonalnie przyjmuje argumenty wywołania (po `--` w CLI)
    # jako Listę Tekstów; typechecker gwarantuje 0 albo 1 parametr
    # i obecność przygrywkowych typów przy 1.
    działać = next((f for f in module_funcs
                    if ("działać",) in f.name.lemmas_set), None)
    args = []
    if działać is not None and len(działać.params) == 1:
        args = [_lista_tekstów(argumenty or [])]
    try:
        execute_function([("działać",)], args)
    except RecursionError:
        # Tu Ć-owe ramki są już odwinięte (wolne miejsce na stosie
        # Pythona), a call_stack wciąż pełny — zdejmowany dopiero teraz.
        ramki = len(call_stack)
        fn = call_stack[-1]["fn"] if call_stack else "działać"
        stack = _stack_snapshot()
        call_stack.clear()
        raise CRuntimeError(
            f"przekroczono głębokość rekursji (~{ramki} ramek Ć) w '{fn}' "
            f"— czy rekursja ma przypadek bazowy? "
            f"(limit interpretera, nie języka)",
            stack) from None
    except RuntimeError as e:
        stack = _stack_snapshot()
        loc = ""
        if call_stack:
            fn, line = call_stack[-1]["fn"], call_stack[-1]["line"]
            loc = (f" (linia {line}, w funkcji '{fn}')" if line is not None
                   else f" (w funkcji '{fn}')")
        call_stack.clear()
        raise CRuntimeError(f"{e}{loc}", stack) from None
