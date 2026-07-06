"""Typechecker Ć — MLsub (simple-sub) z niepełną kratą nominalną.

Rdzeń: zmienne typowe to węzły grafu GRANIC (dolne = co wpływa, górne =
czego się wymaga), a jedyną operacją jest biunifikacja `ogranicz(pod, nad)`
— granice wyłącznie PRZYBYWAJĄ, nie ma destrukcyjnego przepinania klas
union-find, więc wynik nie zależy od kolejności ograniczeń.

Krata typów jest NOMINALNA i NIEPEŁNA: struktura ≤ unia tylko przez
zadeklarowane `U to A albo B`; join dwóch struktur nie jest liczony
zachłannie — materializuje się dopiero przy groundingu (najmniejsza
pokrywająca unia). Łączliwość granic dolnych sprawdzana jest jednak
ZACHŁANNIE (decyzja projektowa): dolanie granicy, której nie pokrywa
żadna unia razem z dotychczasowymi, to błąd w linii sprawcy.

Pola struktur są INWARIANTNE (mutowalne przez zapis łańcuchowy —
wymóg poprawności), strzałki kontrawariantne w argumentach i
kowariantne w wyniku. Rekursja (także wzajemna) jest MONOMORFICZNA
w obrębie silnie spójnej składowej grafu wywołań: składowe typuje się
topologicznie, wywołania wewnątrz składowej współdzielą zmienne
sygnatury, między składowymi sygnatura jest instancjonowana przez
skopiowanie osiągalnego grafu granic. Fixpoint nie istnieje.

Rozszerzenie poza teorię MLsub: DYSJUNKCJE kandydatów (`alternatywy`
na zmiennej) dla częściowych dopasowań `inaczej:` i łańcuchów
o wielu kandydatach — zbiór możliwych głów zawężany kolejnymi
granicami; nierozstrzygnięty w punkcie wejścia → błąd ujednoznacznienia.
"""

import ast_nodes as ast
from dataclasses import dataclass, field
from type_parser import match_args_to_slots


class TypeCheckError(Exception):
    """Konflikt typów: niełączliwe granice, głowa poza kratą, itp."""


# ---------- kontekst diagnostyczny ----------

_ctx_line = None
_ctx_fun = None
_current_note = None


def _set_note(text):
    global _current_note
    _current_note = (f"linia {_ctx_line}: {text}"
                     if _ctx_line is not None else text)


# ---------- typy ----------

last_type = 0

ARROW = "→"

# Zbiór odwiedzonych par (id, id) biunifikacji — terminacja na typach
# rekurencyjnych; czyszczony w resolve_module. `_pary_żywe` przypina
# referencje: bez tego odśmiecony tymczasowy Konkret oddaje swój id
# nowemu obiektowi i świeże ograniczenie bywa fałszywie „już widziane".
_pary = set()
_pary_żywe = []


@dataclass(eq=False, repr=False)
class Zmienna:
    """Węzeł grafu granic. `dolne`/`górne` to listy par (typ, nota) —
    nota niesie linię i kontekst powstania granicy (poszlaka).
    `alternatywy`: None albo dict głowa→Konkret — dysjunkcja kandydatów."""
    number: int
    dolne: list = field(default_factory=list)
    górne: list = field(default_factory=list)
    alternatywy: object = None
    ślad: list = field(default_factory=list)

    def __repr__(self):
        return f"t{self.number}"


@dataclass(frozen=True)
class Konkret:
    """Aplikacja konstruktora: struktura/unia/builtin/strzałka.
    Dla strzałki args = (a1..ak, ret)."""
    głowa: str
    args: tuple = ()

    def __repr__(self):
        if not self.args:
            return self.głowa
        args = [repr(a) for a in self.args]
        if self.głowa == ARROW:
            return f"({', '.join(args[:-1])}) → {args[-1]}"
        return f"{self.głowa}[{', '.join(args)}]"


def new_type():
    global last_type
    v = Zmienna(number=last_type)
    last_type += 1
    return v


def konkret(głowa):
    return Konkret(głowa)


BUILTINS = {"Liczba", "Przełącznik", "Nic", "Znak"}


# ---------- krata nominalna ----------

module = None


def _find_type_decl(type_name, decl_cls):
    if module is None:
        return None
    target = "".join(type_name)
    for decl in module.body:
        if isinstance(decl, decl_cls) and "".join(decl.name) == target:
            return decl
    return None


def find_struct_def(type_name):
    return _find_type_decl(type_name, ast.StructDef)


def find_union_def(type_name):
    return _find_type_decl(type_name, ast.UnionDef)


def find_type_alias(type_name):
    return _find_type_decl(type_name, ast.TypeAlias)


def członkowie(głowa):
    """Zbiór głów-członków zadeklarowanej unii; None gdy to nie unia."""
    ud = find_union_def((głowa,)) if module is not None else None
    if ud is None:
        return None
    return {"".join(m) for m in ud.members}


def czy_głowa_podtypem(pod, nad):
    """S ≤ S; S ≤ U gdy S jest członkiem U. Unia ≤ inna unia tylko gdy
    to ta sama unia."""
    if pod == nad:
        return True
    czł = członkowie(nad)
    return czł is not None and pod in czł


def najmniejsza_unia(głowy):
    """Najmniejsza zadeklarowana unia pokrywająca wszystkie `głowy`
    (każda głowa jest tą unią albo jej członkiem). None gdy żadna nie
    pokrywa; remis minimalnych → błąd."""
    if module is None:
        return None
    kandydatki = []
    for decl in module.body:
        if not isinstance(decl, ast.UnionDef):
            continue
        uh = "".join(decl.name)
        czł = {"".join(m) for m in decl.members}
        if all(g == uh or g in czł for g in głowy):
            kandydatki.append((len(czł), uh))
    if not kandydatki:
        return None
    kandydatki.sort()
    if len(kandydatki) > 1 and kandydatki[0][0] == kandydatki[1][0]:
        raise TypeCheckError(
            f"głowy {sorted(głowy)} pokrywa więcej niż jedna minimalna "
            f"unia: {kandydatki[0][1]}, {kandydatki[1][1]} — dodaj "
            f"adnotację typu")
    return kandydatki[0][1]


def _union_param_names(głowa):
    """Niejawne parametry unii: dziedziczone po nazwach od członków-struktur,
    w kolejności pierwszego wystąpienia; [] gdy brak."""
    ud = find_union_def((głowa,)) if module is not None else None
    if ud is None:
        return []
    params = []
    for m in ud.members:
        sd = find_struct_def(m)
        if sd is None:
            continue
        for p in sd.params:
            names = frozenset("".join(l) for l in p.name.lemmas_set)
            if not any(names & s for s in params):
                params.append(names)
    return params


def _mapowanie_członka(członek, unia):
    """Pary (i, j): i-ty parametr struktury-członka odpowiada j-temu
    niejawnemu argumentowi unii (po nazwach)."""
    sd = find_struct_def(członek)
    if sd is None:
        return []
    u_params = _union_param_names(unia)
    pary = []
    for i, p in enumerate(sd.params):
        names = {"".join(l) for l in p.name.lemmas_set}
        for j, u_names in enumerate(u_params):
            if names & u_names:
                pary.append((i, j))
                break
    return pary


def _param_pedigree(głowa, i):
    """(nazwa, definicja) i-tego parametru typu `głowa` — do rodowodu
    niejawnych argumentów w komunikatach."""
    sd = find_struct_def(głowa)
    if sd is not None:
        if i < len(sd.params):
            p = sd.params[i]
            return (min(("".join(l) for l in p.name.lemmas_set), key=len),
                    głowa)
        return None, None
    ud = find_union_def(głowa)
    if ud is None:
        return None, None
    params = []
    for m in ud.members:
        msd = find_struct_def(m)
        if msd is None:
            continue
        for p in msd.params:
            names = frozenset("".join(l) for l in p.name.lemmas_set)
            if not any(names & s for s, _ in params):
                params.append((names, "".join(msd.name)))
    if i < len(params):
        names, origin = params[i]
        return min(names, key=len), origin
    return None, None


def _unia_applied(głowa, env=None, bound=None):
    """Konkret unii z niejawnymi argumentami: nazwa widoczna w `env`
    (wnętrze definicji struktury) → przechwyt; `bound` (aplikacja
    nazwana) → gotowy węzeł; inaczej świeża zmienna per wystąpienie."""
    args = []
    for names in _union_param_names(głowa):
        if bound:
            b = next((bound[n] for n in names if n in bound), None)
            if b is not None:
                args.append(b)
                continue
        captured = None
        if env:
            for n in names:
                if n in env:
                    captured = env[n]
                    break
        args.append(captured if captured is not None else new_type())
    return Konkret(głowa, tuple(args))


def _instancja_struktury(sd):
    """Świeża instancja struktury: Konkret(nazwa, świeże argi) + env
    nazwa-parametru → arg."""
    fresh = [new_type() for _ in sd.params]
    env = {}
    for p, a in zip(sd.params, fresh):
        for lemmas in p.name.lemmas_set:
            env["".join(lemmas)] = a
    return Konkret("".join(sd.name), tuple(fresh)), env


# ---------- biunifikacja ----------

def _głowy_dolnych(var):
    return {t.głowa for t, _ in var.dolne if isinstance(t, Konkret)}


def _poszlaki(var):
    noty = [n for _, n in var.dolne if n] + [n for _, n in var.górne if n]
    widziane, out = set(), []
    for n in noty:
        if n not in widziane:
            widziane.add(n)
            out.append(n)
    return out


def _msg_konflikt(a, b, noty_a=(), noty_b=()):
    msg = f"nie można zunifikować {a!r} z {b!r}"
    linie = []
    if noty_a:
        linie.append(f"  poszlaki o {a!r}: " + "; ".join(noty_a[-8:]))
    if noty_b:
        linie.append(f"  poszlaki o {b!r}: " + "; ".join(noty_b[-8:]))
    if linie:
        msg += " — zdecyduj, która poszlaka jest błędna:\n" + "\n".join(linie)
    return msg


def _zawęź_alternatywy(var, głowa_faktu):
    """Konkretna granica zawęża dysjunkcję kandydatów: zostają alternatywy
    zgodne z głową faktu (ta sama, członek, unia zawierająca)."""
    if var.alternatywy is None:
        return
    zgodne = {
        h: inst for h, inst in var.alternatywy.items()
        if h == głowa_faktu
        or czy_głowa_podtypem(głowa_faktu, h)
        or czy_głowa_podtypem(h, głowa_faktu)
    }
    if not zgodne:
        opcje = ", ".join(sorted(var.alternatywy))
        raise TypeCheckError(
            f"typ '{głowa_faktu}' nie pasuje do żadnej z możliwości "
            f"{{{opcje}}} zebranych z wcześniejszych użyć")
    var.alternatywy = zgodne
    if len(zgodne) == 1:
        (jedyna_inst,) = zgodne.values()
        var.alternatywy = None
        ogranicz(var, jedyna_inst)


def _dodaj_dolną(var, typ):
    """Nowa granica dolna + ZACHŁANNY test łączliwości: głowy wszystkich
    konkretnych dolnych muszą mieć wspólną głowę albo pokrywającą unię."""
    if any(t is typ or t == typ for t, _ in var.dolne):
        return False
    if isinstance(typ, Konkret) and typ.głowa != ARROW:
        głowy = {g for g in _głowy_dolnych(var) if g != ARROW}
        nowe = głowy | {typ.głowa}
        if len(nowe) > 1 and najmniejsza_unia(nowe) is None:
            stare = next(t for t, _ in var.dolne
                         if isinstance(t, Konkret) and t.głowa != ARROW)
            raise TypeCheckError(_msg_konflikt(
                stare, typ,
                _poszlaki(var),
                [_current_note] if _current_note else ()))
        _zawęź_alternatywy(var, typ.głowa)
    var.dolne.append((typ, _current_note))
    if _current_note and _current_note not in var.ślad:
        var.ślad.append(_current_note)
    return True


def _dodaj_górną(var, typ):
    if any(t is typ or t == typ for t, _ in var.górne):
        return False
    if isinstance(typ, Konkret) and typ.głowa != ARROW:
        _zawęź_alternatywy(var, typ.głowa)
    var.górne.append((typ, _current_note))
    if _current_note and _current_note not in var.ślad:
        var.ślad.append(_current_note)
    return True


def ogranicz(pod, nad):
    """Biunifikacja: `pod` (typ produkowany) płynie w `nad` (wymaganie).
    Granice tylko przybywają; para (pod, nad) przetwarzana raz."""
    if pod is nad:
        return
    klucz = (id(pod), id(nad))
    if klucz in _pary:
        return
    _pary.add(klucz)
    _pary_żywe.append((pod, nad))
    if isinstance(pod, Konkret) and isinstance(nad, Konkret):
        _ogranicz_konkrety(pod, nad)
    elif isinstance(pod, Zmienna) and isinstance(nad, Zmienna):
        # Krawędź var–var zapisywana OBUSTRONNIE: górna na pod, dolna na
        # nad — grounding i materializacja czytają dolne, poszlaki płyną
        # w obie strony.
        _dodaj_górną(pod, nad)
        _dodaj_dolną(nad, pod)
        for d, nota in list(pod.dolne):
            if d is not nad:
                _przepchnij(d, nad, nota)
        for g, nota in list(nad.górne):
            if g is not pod:
                _przepchnij(pod, g, nota)
    elif isinstance(pod, Zmienna):
        if _dodaj_górną(pod, nad):
            for d, nota in list(pod.dolne):
                _przepchnij(d, nad, nota)
    else:
        if _dodaj_dolną(nad, pod):
            for g, nota in list(nad.górne):
                _przepchnij(pod, g, nota)


def _przepchnij(pod, nad, nota):
    """Domknięcie przechodnie z dekoracją poszlaką granicy pośredniczącej."""
    try:
        ogranicz(pod, nad)
    except TypeCheckError as e:
        if nota and nota not in str(e):
            raise TypeCheckError(f"{e}\n  przez granicę: {nota}") from None
        raise


def _ogranicz_konkrety(pod, nad):
    if pod.głowa == ARROW or nad.głowa == ARROW:
        if pod.głowa != nad.głowa:
            raise TypeCheckError(_msg_konflikt(pod, nad))
        if len(pod.args) != len(nad.args):
            raise TypeCheckError(
                f"niezgodna liczba argumentów funkcji: {pod!r} vs {nad!r}")
        *pa, pret = pod.args
        *na, nret = nad.args
        for x, y in zip(pa, na):
            ogranicz(y, x)          # argumenty kontrawariantnie
        ogranicz(pret, nret)        # wynik kowariantnie
        return
    if pod.głowa == nad.głowa:
        if len(pod.args) != len(nad.args):
            raise TypeCheckError(
                f"niezgodna arność '{pod.głowa}': "
                f"{len(pod.args)} vs {len(nad.args)}")
        for i, (x, y) in enumerate(zip(pod.args, nad.args)):
            _inwariantnie(pod.głowa, i, x, y)
        return
    if czy_głowa_podtypem(pod.głowa, nad.głowa):
        # struktura ≤ unia: argumenty członka ↔ niejawne argumenty unii
        # po nazwach parametrów, inwariantnie.
        for i, j in _mapowanie_członka(pod.głowa, nad.głowa):
            if i < len(pod.args) and j < len(nad.args):
                _inwariantnie(nad.głowa, j, pod.args[i], nad.args[j])
        return
    raise TypeCheckError(_msg_konflikt(pod, nad))


def _inwariantnie(głowa, i, x, y):
    """Argument konstruktora: inwariantny (pola są mutowalne). Konflikt
    dekorowany rodowodem niejawnego parametru."""
    try:
        ogranicz(x, y)
        ogranicz(y, x)
    except TypeCheckError as e:
        if "niejawny argument" in str(e):
            raise
        pname, origin = _param_pedigree(głowa, i)
        if pname is None:
            raise
        raise TypeCheckError(
            f"niejawny argument '{pname}' typu '{głowa}' (parametr "
            f"'{pname}' z definicji '{origin}') nie zgadza się między "
            f"wystąpieniami — {e}") from None


# ---------- materializacja (grounding / wypis) ----------

def _zmaterializuj(t, wymagaj=False, widziane=None):
    """Najlepszy konkret dla typu: konkret → on sam; zmienna → join głów
    dolnych (pojedyncza głowa albo najmniejsza pokrywająca unia), w braku
    dolnych default z górnych (singleton / dokładna unia+członkowie).
    `wymagaj=True` → None zamiast wolnej zmiennej (grounding zgłosi błąd
    z kontekstem)."""
    if widziane is None:
        widziane = set()
    if isinstance(t, Konkret):
        return t
    if t in widziane:
        return None
    widziane.add(t)
    if t.alternatywy is not None and len(t.alternatywy) > 1:
        opcje = ", ".join(sorted(t.alternatywy))
        raise TypeCheckError(
            f"typ pasuje do wielu możliwości: {opcje} — dodaj adnotację "
            f"typu")
    konkrety = [x for x, _ in t.dolne if isinstance(x, Konkret)]
    dolne_vars = [x for x, _ in t.dolne if isinstance(x, Zmienna)]
    for dv in dolne_vars:
        m = _zmaterializuj(dv, widziane=widziane)
        if m is not None:
            konkrety.append(m)
    if konkrety:
        strzałki = [k for k in konkrety if k.głowa == ARROW]
        if strzałki:
            return strzałki[0]
        głowy = {k.głowa for k in konkrety}
        if len(głowy) == 1:
            return konkrety[0]
        unia = najmniejsza_unia(głowy)
        if unia is None:
            raise TypeCheckError(_msg_konflikt(
                konkrety[0], konkrety[-1], _poszlaki(t)))
        return _unia_applied(unia)
    górne = [x for x, _ in t.górne if isinstance(x, Konkret)]
    if górne:
        głowy = {g.głowa for g in górne}
        if len(głowy) == 1:
            return górne[0]
        for g in głowy:
            czł = członkowie(g)
            if czł is not None and głowy == (czł | {g}):
                return _unia_applied(g)
    return None


def _czy_ugruntowany(t):
    """Czy typ jest dostatecznie konkretny dla punktu wejścia: ma
    materializację, a jej argumenty (poza uniami — konkretyzacja przez
    użycie) też są ugruntowane."""
    m = _zmaterializuj(t)
    if m is None:
        return False
    if członkowie(m.głowa) is not None or m.głowa == ARROW:
        return True
    return all(_czy_ugruntowany(a) for a in m.args)


# ---------- scope (drzewo zasięgów + cienie zawężeń) ----------

class Scope:
    def __init__(self, parent=None):
        self.types = []
        self.shadows = []
        self.parent = parent
        self.children = []
        self.root_fdt = parent.root_fdt if parent else None
        if parent is not None:
            parent.children.append(self)

    def _find_local(self, identifier):
        keys = identifier.scope_keys
        for (v, t) in self.types:
            if any(ast.scope_key_matches(a, b) for a in keys
                   for b in v.scope_keys):
                return t
        for (v, t) in self.shadows:
            if any(ast.scope_key_matches(a, b) for a in keys
                   for b in v.scope_keys):
                return t
        return None

    def declare_shadow(self, identifier, t):
        if self._find_local(identifier) is None:
            self.shadows.append((identifier, t))

    def assign_target_type(self, identifier):
        """Cel przypisania: zmienna widoczna w łańcuchu Z POMINIĘCIEM
        cieni (zapis idzie na zewnątrz — idiom kursora); niewidoczna →
        deklaracja lokalna."""
        keys = identifier.scope_keys
        s = self
        while s is not None:
            for (v, t) in s.types:
                if any(ast.scope_key_matches(a, b) for a in keys
                       for b in v.scope_keys):
                    return t
            s = s.parent
        new_t = new_type()
        self.types.append((identifier, new_t))
        return new_t

    def find_shadow(self, identifier):
        keys = identifier.scope_keys
        s = self
        while s is not None:
            for (v, t) in s.shadows:
                if any(ast.scope_key_matches(a, b) for a in keys
                       for b in v.scope_keys):
                    return t
            s = s.parent
        return None

    def _find(self, identifier):
        s = self
        while s is not None:
            t = s._find_local(identifier)
            if t is not None:
                return t
            s = s.parent
        return None

    def declare(self, identifier, t):
        if self._find_local(identifier) is None:
            self.types.append((identifier, t))

    def get_type(self, identifier):
        t = self._find(identifier)
        if t is not None:
            return t
        new_t = new_type()
        self.types.append((identifier, new_t))
        return new_t

    def child_for(self, node, role):
        slots = node.__dict__.setdefault("_scopes", {})
        if role not in slots:
            slots[role] = Scope(self)
        return slots[role]

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


# ---------- schematy funkcji ----------

@dataclass
class FunDefTypes:
    name: ast.FunctionIdentifier
    arg_types: list
    ret_type: object
    ret_annotated: bool = False
    extern: bool = False


fun_decls = []
fun_scopes = []


def find_fdt(func_id):
    for (name, fdt) in fun_decls:
        if name.lemmas_set & func_id.lemmas_set:
            return fdt


def find_fdt_by_key(key):
    for (name, fdt) in fun_decls:
        if key in name.lemmas_set:
            return fdt


def _kopiuj(t, memo):
    """Instancjacja: głęboka kopia osiągalnego grafu granic (memoizowana,
    bezpieczna dla cykli)."""
    if isinstance(t, Konkret):
        if not t.args:
            return t
        return Konkret(t.głowa, tuple(_kopiuj(a, memo) for a in t.args))
    if t in memo:
        return memo[t]
    n = new_type()
    memo[t] = n
    n.ślad = list(t.ślad)
    if t.alternatywy is not None:
        n.alternatywy = {h: _kopiuj(k, memo)
                         for h, k in t.alternatywy.items()}
    n.dolne = [(_kopiuj(x, memo), nota) for x, nota in t.dolne]
    n.górne = [(_kopiuj(x, memo), nota) for x, nota in t.górne]
    return n


def instantiate(fdt):
    memo = {}
    return ([_kopiuj(a, memo) for a in fdt.arg_types],
            _kopiuj(fdt.ret_type, memo))


# ---------- elaborate: TypeRef (składnia) → typ (semantyka) ----------

def elaborate(tref, env, fresh_unknown=False, alias_args=False):
    h = "".join(tref.head)
    if h in env:
        return env[h]
    al = find_type_alias(tref.head)
    if al is not None:
        if tref.args:
            raise TypeCheckError(
                f"alias typu '{h}' nie przyjmuje argumentów typu — jawna "
                f"aplikacja parametrów jest dozwolona tylko w deklaracji "
                f"aliasu")
        return elaborate(al.target, env, fresh_unknown, alias_args=True)
    sd = find_struct_def(tref.head)
    if sd is None:
        if find_union_def(tref.head) is not None:
            if tref.args and not (alias_args
                                  or all(ta.name is not None
                                         for ta in tref.args)):
                raise TypeCheckError(
                    f"typ wariantowy '{h}' nie przyjmuje argumentów typu")
            bound = {
                "".join(ta.name): elaborate(ta.type, env, fresh_unknown,
                                            alias_args=True)
                for ta in tref.args
            } if tref.args else None
            if bound:
                znane = _union_param_names(h)
                for nm in bound:
                    if not any(nm in names for names in znane):
                        dostępne = ", ".join(
                            sorted(min(ns, key=len) for ns in znane)) or "brak"
                        raise TypeCheckError(
                            f"typ wariantowy '{h}' nie ma parametru '{nm}' "
                            f"— parametry: {dostępne}")
            return _unia_applied(h, env, bound)
        if fresh_unknown and h not in BUILTINS:
            v = new_type()
            env[h] = v
            return v
        if h in BUILTINS and tref.args:
            raise TypeCheckError(
                f"typ wbudowany '{h}' nie przyjmuje argumentów typu")
        return Konkret(h)
    sloty = [new_type() for _ in sd.params]
    if tref.args and (alias_args
                      or all(ta.name is not None for ta in tref.args)):
        for ta in tref.args:
            nm = "".join(ta.name)
            trafiony = False
            for slot, p in zip(sloty, sd.params):
                if any(nm == "".join(l) for l in p.name.lemmas_set):
                    val = elaborate(ta.type, env, fresh_unknown,
                                    alias_args=True)
                    ogranicz(val, slot)
                    ogranicz(slot, val)
                    trafiony = True
                    break
            if not trafiony:
                dostępne = ", ".join(sorted(
                    min(("".join(l) for l in p.name.lemmas_set), key=len)
                    for p in sd.params)) or "brak"
                raise TypeCheckError(
                    f"typ '{h}' nie ma parametru '{nm}' — parametry: "
                    f"{dostępne}")
    elif tref.args and len(tref.args) == len(sd.params):
        arg_meta = [(ta.prep, ta.case, ta) for ta in tref.args]
        slot_to_arg = match_args_to_slots(
            arg_meta, sd.params,
            on_error=lambda **kw: TypeCheckError(
                f"argumenty typu nie pasują do parametrów '{h}'"))
        for slot_i, arg_i in slot_to_arg.items():
            val = elaborate(tref.args[arg_i].type, env, fresh_unknown)
            ogranicz(val, sloty[slot_i])
            ogranicz(sloty[slot_i], val)
    elif tref.args:
        raise TypeCheckError(
            f"typ '{h}' oczekuje {len(sd.params)} argumentów, "
            f"otrzymał {len(tref.args)}")
    return Konkret(h, tuple(sloty))


# ---------- walidacja aliasów (pass 0) ----------

def _check_aliases(node):
    for decl in node.body:
        if isinstance(decl, ast.TypeAlias):
            _validate_alias_tref(decl.target, ["".join(decl.name)])


def _validate_alias_tref(tref, seen):
    h = "".join(tref.head)
    al = find_type_alias(tref.head)
    if al is not None:
        if h in seen:
            raise TypeCheckError(
                f"cykl aliasów typów: {' → '.join([*seen, h])}")
        if tref.args:
            raise TypeCheckError(
                f"alias typu '{h}' nie przyjmuje argumentów typu — "
                f"zastosuj parametry w jego własnej deklaracji")
        _validate_alias_tref(al.target, [*seen, h])
        return
    sd = find_struct_def(tref.head)
    ud = find_union_def(tref.head)
    if sd is None and ud is None:
        if h in BUILTINS:
            if tref.args:
                raise TypeCheckError(
                    f"typ wbudowany '{h}' nie przyjmuje argumentów typu")
            return
        raise TypeCheckError(
            f"nieznany typ '{h}' w deklaracji aliasu '{seen[0]}'")
    if sd is not None:
        params = [frozenset("".join(l) for l in p.name.lemmas_set)
                  for p in sd.params]
    else:
        params = _union_param_names(h)
    bound = set()
    for ta in tref.args:
        nm = "".join(ta.name) if ta.name else None
        if nm is None:
            raise TypeCheckError(
                f"aplikacja parametru typu w aliasie wymaga formy "
                f"'o NAZWIE Typ' (deklaracja aliasu '{seen[0]}')")
        slot = next(
            (i for i, names in enumerate(params) if nm in names), None)
        if slot is None:
            known = ", ".join(sorted(min(ns, key=len) for ns in params))
            raise TypeCheckError(
                f"typ '{h}' nie ma parametru '{nm}' (deklaracja aliasu "
                f"'{seen[0]}'); parametry: {known or 'brak'}")
        if slot in bound:
            raise TypeCheckError(
                f"parametr '{nm}' typu '{h}' związany wielokrotnie "
                f"w deklaracji aliasu '{seen[0]}'")
        bound.add(slot)
        _validate_alias_tref(ta.type, seen)


# ---------- totalność zwrotów ----------

def _returns_totally(stmts):
    for stmt in stmts:
        if isinstance(stmt, ast.Return):
            return True
        if isinstance(stmt, ast.If):
            if (stmt.then_body and stmt.else_body
                    and _returns_totally(stmt.then_body)
                    and _returns_totally(stmt.else_body)):
                return True
        elif isinstance(stmt, ast.Match):
            if stmt.branches and all(
                    _returns_totally(br.body) for br in stmt.branches):
                return True
    return False


# ---------- graf wywołań i SCC ----------

def _wywoływane(node, out):
    """Zbierz FunctionIdentifiery/klucze wywołań z poddrzewa AST."""
    if node is None or isinstance(node, (str, int, bool, tuple, frozenset)):
        return
    if isinstance(node, ast.FunctionCall):
        out.append(("id", node.name))
    if isinstance(node, ast.FunctionRef):
        out.append(("key", node.key))
    if isinstance(node, list):
        for x in node:
            _wywoływane(x, out)
        return
    if hasattr(node, "__dict__"):
        for k, v in node.__dict__.items():
            if k in ("analyses", "variants", "_scopes"):
                continue
            _wywoływane(v, out)


def _scc_kolejność(module_funcs):
    """Tarjan po grafie wywołań; zwraca listę składowych (list indeksów)
    w kolejności odwrotnie topologicznej (liście najpierw)."""
    indeks_fdt = {id(fdt): i for i, (_, fdt) in enumerate(module_funcs)}
    krawędzie = [set() for _ in module_funcs]
    for i, (decl, _) in enumerate(module_funcs):
        cele = []
        _wywoływane(decl.body, cele)
        for rodzaj, ref in cele:
            fdt = find_fdt(ref) if rodzaj == "id" else find_fdt_by_key(ref)
            if fdt is not None and id(fdt) in indeks_fdt:
                krawędzie[i].add(indeks_fdt[id(fdt)])
    indeksy = {}
    low = {}
    stos, na_stosie = [], set()
    wynik = []
    licznik = [0]

    def strong(v):
        indeksy[v] = low[v] = licznik[0]
        licznik[0] += 1
        stos.append(v)
        na_stosie.add(v)
        for w in krawędzie[v]:
            if w not in indeksy:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in na_stosie:
                low[v] = min(low[v], indeksy[w])
        if low[v] == indeksy[v]:
            skł = []
            while True:
                w = stos.pop()
                na_stosie.discard(w)
                skł.append(w)
                if w == v:
                    break
            wynik.append(skł)

    for v in range(len(module_funcs)):
        if v not in indeksy:
            strong(v)
    return wynik


# ---------- moduł ----------

_bieżąca_składowa = set()   # id(fdt) funkcji typowanych właśnie razem


def resolve_module(node):
    global module, fun_decls, fun_scopes
    global _ctx_line, _ctx_fun, _current_note, _bieżąca_składowa
    module = node
    _ctx_line = _ctx_fun = _current_note = None
    _pary.clear()
    _pary_żywe.clear()
    _bieżąca_składowa = set()
    _check_aliases(node)
    module_funcs = []
    for decl in node.body:
        if isinstance(decl, ast.FunctionDef):
            fenv = {}
            arg_types = [
                elaborate(p.type, fenv, fresh_unknown=True)
                if p.type is not None else new_type()
                for p in decl.params
            ]
            if decl.return_type is not None:
                ret = elaborate(decl.return_type, fenv, fresh_unknown=True)
                annotated = True
            else:
                ret = new_type()
                annotated = False
            fdt = FunDefTypes(name=decl.name, arg_types=arg_types,
                              ret_type=ret, ret_annotated=annotated)
            fun_decls.append((decl.name, fdt))
            module_funcs.append((decl, fdt))
        elif isinstance(decl, ast.ExternFunctionDef):
            fenv = {}
            fdt = FunDefTypes(
                name=decl.name,
                arg_types=[elaborate(p.type, fenv, fresh_unknown=True)
                           for p in decl.params],
                ret_type=elaborate(decl.return_type, fenv,
                                   fresh_unknown=True),
                ret_annotated=True, extern=True)
            fun_decls.append((decl.name, fdt))

    scopes = {}
    for składowa in _scc_kolejność(module_funcs):
        _bieżąca_składowa = {id(module_funcs[i][1]) for i in składowa}
        for i in składowa:
            decl, fdt = module_funcs[i]
            scope = Scope()
            scope.root_fdt = fdt
            scopes[i] = scope
            resolve_function_def(decl, scope)
            if not _returns_totally(decl.body):
                _set_note(f"niejawny zwrot Nic z '{_ctx_fun}'")
                ogranicz(Konkret("Nic"), fdt.ret_type)
    _bieżąca_składowa = set()
    fun_scopes = [(decl, scopes[i])
                  for i, (decl, _) in enumerate(module_funcs)]
    for decl, scope in fun_scopes:
        if ("działać",) in decl.name.lemmas_set:
            _check_grounded(decl, scope)


def _ślady_z_grafu(var, widziane=None):
    """Ślady zmiennej i jej poszlak-zmiennych (rodowód płynie krawędziami
    grafu granic — np. nota „pochodzi z externa" siedzi na zmiennej
    wyniku wywołania, nie na zmiennej użytkownika)."""
    if widziane is None:
        widziane = set()
    if var in widziane:
        return []
    widziane.add(var)
    out = list(var.ślad)
    for d, _ in var.dolne:
        if isinstance(d, Zmienna):
            for n in _ślady_z_grafu(d, widziane):
                if n not in out:
                    out.append(n)
    return out


def _check_grounded(decl, scope):
    for s in scope.walk():
        for ident, t in s.types:
            try:
                ok = _czy_ugruntowany(t)
            except TypeCheckError as e:
                line = getattr(ident, "line", None)
                raise TypeCheckError(
                    f"typ zmiennej '{'_'.join(ident.surface)}' "
                    f"(linia {line}): {e}") from None
            if not ok:
                line = getattr(ident, "line", None)
                ślad = _ślady_z_grafu(t) if isinstance(t, Zmienna) else []
                źródło = ("; " + "; ".join(ślad[-4:])) if ślad else ""
                raise TypeCheckError(
                    f"nie można wywnioskować konkretnego typu zmiennej "
                    f"'{'_'.join(ident.surface)}' (linia {line}); "
                    f"pozostało {t!r}{źródło} — użyj wartości "
                    f"strukturalnie albo dodaj adnotację typu")


# ---------- funkcje i instrukcje ----------

def resolve_function_def(node, scope):
    global _ctx_fun
    _ctx_fun = "_".join(node.name.surface)
    for i, p in enumerate(node.params):
        scope.declare(p.name, scope.root_fdt.arg_types[i])
    for stmt in node.body:
        resolve_statement(stmt, scope)


def _node_line(node):
    if isinstance(node, ast.Phrase):
        return node.line
    if isinstance(node, ast.Assignment):
        return (getattr(node.target, "line", None)
                or getattr(node.value, "line", None))
    if isinstance(node, (ast.If, ast.While)):
        return getattr(node.cond, "line", None)
    if isinstance(node, ast.Match):
        return node.line
    if isinstance(node, ast.Return):
        return getattr(node.value, "line", None)
    return None


def resolve_statement(node, scope):
    global _ctx_line
    line = _node_line(node)
    if line is not None:
        _ctx_line = line
        _set_note("wnioskowanie")
    try:
        if isinstance(node, ast.Assignment):
            return resolve_assignment(node, scope)
        if isinstance(node, ast.If):
            return resolve_if(node, scope)
        if isinstance(node, ast.While):
            return resolve_while(node, scope)
        if isinstance(node, ast.For):
            raise TypeCheckError(
                "pętla 'dla' czeka na protokół iteracji (kolekcje są "
                "biblioteczne) — użyj 'dopóki' albo rekurencji")
        if isinstance(node, ast.Match):
            return resolve_match(node, scope)
        if isinstance(node, ast.Return):
            return resolve_return(node, scope)
        if isinstance(node, (ast.Break, ast.Continue)):
            return
        resolve_expression(node, scope)
    except TypeCheckError as e:
        if "lini" in str(e) or line is None:
            raise
        ctx = f"podczas typowania linii {line}"
        if _ctx_fun:
            ctx += f", w funkcji '{_ctx_fun}'"
        raise TypeCheckError(f"{e} ({ctx})") from None


def resolve_assignment(node, scope):
    target = node.target.resolved
    value_type = resolve_expression(node.value.resolved, scope)
    explicit_t = None
    if isinstance(target, ast.Typed) and isinstance(target.expr,
                                                    ast.Identifier):
        explicit_t = elaborate(target.type, {}, fresh_unknown=True)
        target = target.expr
    if isinstance(target, ast.Identifier):
        _set_note(f"przypisanie do '{'_'.join(target.surface)}'")
        outer_t = scope.assign_target_type(target)
        if explicit_t is not None:
            # Adnotowana deklaracja przybija typ: wartości sprawdzane
            # względem adnotacji, odczyty widzą adnotację.
            ogranicz(value_type, explicit_t)
            ogranicz(explicit_t, outer_t)
            ogranicz(outer_t, explicit_t)
        else:
            ogranicz(value_type, outer_t)
        # Zapis do nazwy podmiotu idzie WYŁĄCZNIE na zewnątrz — cień
        # zawężenia zostaje wąski (idiom kursora czyta głowę i przesuwa
        # wskaźnik w tej samej gałęzi); odczyty PO bloku widzą typ
        # zewnętrzny, uczciwie poszerzony o zapis.
        return
    target_type = resolve_expression(target, scope)
    _set_note("zapis pola przez łańcuch dopełniaczowy")
    ogranicz(value_type, target_type)


def resolve_return(node, scope):
    if node.value is not None:
        t = resolve_expression(node.value, scope)
        _set_note(f"zwrot z funkcji '{_ctx_fun}'")
        ogranicz(t, scope.root_fdt.ret_type)
    else:
        _set_note(f"gołe 'zwróć' z funkcji '{_ctx_fun}'")
        ogranicz(Konkret("Nic"), scope.root_fdt.ret_type)


def resolve_if(node, scope):
    cond = resolve_expression(node.cond, scope)
    ogranicz(cond, Konkret("Przełącznik"))
    for stmt in node.then_body:
        resolve_statement(stmt, scope.child_for(node, "then"))
    for stmt in node.else_body:
        resolve_statement(stmt, scope.child_for(node, "else"))


def resolve_while(node, scope):
    cond = resolve_expression(node.cond, scope)
    ogranicz(cond, Konkret("Przełącznik"))
    for stmt in node.body:
        resolve_statement(stmt, scope.child_for(node, "body"))


# ---------- dopasowanie `jest:` ----------

def _głowy_znane(t):
    """Głowy konkretów znanych o typie (materializacja miękka) — do
    rozstrzygania kandydatów dopasowań i łańcuchów."""
    if isinstance(t, Konkret):
        return {t.głowa}
    m = None
    try:
        m = _zmaterializuj(t)
    except TypeCheckError:
        pass
    return {m.głowa} if m is not None else set()


def _fakty_dolne(t, widziane=None):
    """Głowa wywiedziona WYŁĄCZNIE z granic dolnych (faktów o wartości) —
    bez domyślkowania z górnych, które są dozwoleniem, nie faktem."""
    if isinstance(t, Konkret):
        return {t.głowa}
    if widziane is None:
        widziane = set()
    if t in widziane:
        return set()
    widziane.add(t)
    głowy = set()
    for d, _ in t.dolne:
        if isinstance(d, Konkret):
            głowy.add(d.głowa)
        else:
            głowy |= _fakty_dolne(d, widziane)
    if len(głowy) > 1:
        unia = najmniejsza_unia(głowy)
        if unia is not None:
            return {unia}
    return głowy


def _union_for_match(subject_t, branch_heads, line):
    branch_set = set(branch_heads)
    cands = [
        decl for decl in module.body
        if isinstance(decl, ast.UnionDef)
        and {"".join(m) for m in decl.members} == branch_set
    ]
    znane = _głowy_znane(subject_t)
    if len(cands) > 1 and znane:
        zawężone = [c for c in cands
                    if "".join(c.name) in znane
                    or znane & {"".join(m) for m in c.members}]
        if zawężone:
            cands = zawężone
    if len(cands) == 1:
        return cands[0]
    if not cands:
        for głowa in znane:
            czł = członkowie(głowa)
            if czł is not None:
                brakuje = czł - branch_set
                nadmiar = branch_set - czł
                if brakuje:
                    raise TypeCheckError(
                        f"dopasowanie 'jest:' (linia {line}) na wartości "
                        f"typu '{głowa}' — brakuje gałęzi: "
                        f"{', '.join(sorted(brakuje))}")
                if nadmiar:
                    raise TypeCheckError(
                        f"dopasowanie 'jest:' (linia {line}) ma gałęzie "
                        f"spoza unii: {', '.join(sorted(nadmiar))}")
        raise TypeCheckError(
            f"gałęzie dopasowania 'jest:' (linia {line}) — "
            f"{', '.join(sorted(branch_set))} — nie odpowiadają członkom "
            f"żadnego zadeklarowanego typu wariantowego")
    opts = ", ".join(sorted("".join(c.name) for c in cands))
    raise TypeCheckError(
        f"dopasowanie 'jest:' (linia {line}) pasuje do wielu typów "
        f"wariantowych: {opts} — dodaj adnotację typu")


def _unions_for_partial_match(subject_t, branch_heads, line):
    branch_set = set(branch_heads)
    cands = [
        decl for decl in module.body
        if isinstance(decl, ast.UnionDef)
        and branch_set <= {"".join(m) for m in decl.members}
    ]
    if not cands:
        raise TypeCheckError(
            f"gałęzie dopasowania z 'inaczej:' (linia {line}) — "
            f"{', '.join(sorted(branch_set))} — nie są podzbiorem "
            f"wariantów żadnego zadeklarowanego typu wariantowego")
    znane = _głowy_znane(subject_t)
    if znane:
        zawężone = [
            c for c in cands
            if "".join(c.name) in znane
            or znane & {"".join(m) for m in c.members}
        ]
        if len(zawężone) > 1:
            opts = ", ".join(sorted("".join(c.name) for c in zawężone))
            raise TypeCheckError(
                f"dopasowanie z 'inaczej:' (linia {line}) pasuje do wielu "
                f"typów wariantowych: {opts} — dodaj adnotację typu")
        if zawężone:
            return zawężone
    return cands


def resolve_match(node, scope):
    subject_t = resolve_expression(node.subject, scope)
    _set_note("podmiot dopasowania 'jest:'")
    branch_heads = []
    has_default = False
    for br in node.branches:
        if br.type_name is None:
            has_default = True
            continue
        h = "".join(br.type_name)
        if h in branch_heads:
            raise TypeCheckError(
                f"powtórzona gałąź '{h}' w dopasowaniu 'jest:' "
                f"(linia {node.line})")
        branch_heads.append(h)
    if has_default:
        cands = _unions_for_partial_match(subject_t, branch_heads,
                                          node.line)
        if len(cands) == 1:
            u_inst = _unia_applied("".join(cands[0].name))
            ogranicz(subject_t, u_inst)
            linked = u_inst
        else:
            linked = None
            if isinstance(subject_t, Zmienna):
                alt = {"".join(c.name): _unia_applied("".join(c.name))
                       for c in cands}
                if subject_t.alternatywy is None:
                    subject_t.alternatywy = alt
                else:
                    wspólne = {h: k for h, k in subject_t.alternatywy.items()
                               if h in alt}
                    if not wspólne:
                        raise TypeCheckError(
                            f"dopasowanie z 'inaczej:' (linia {node.line}) "
                            f"nie przecina się z wcześniejszymi "
                            f"możliwościami podmiotu")
                    subject_t.alternatywy = wspólne
    else:
        ud = _union_for_match(subject_t, branch_heads, node.line)
        linked = _unia_applied("".join(ud.name))
        ogranicz(subject_t, linked)
    for br in node.branches:
        if br.type_name is None:
            br_scope = scope.child_for(br, "body")
            for stmt in br.body:
                resolve_statement(stmt, br_scope)
            continue
        sd = find_struct_def(br.type_name)
        if sd is None:
            br_scope = scope.child_for(br, "body")
            if br.alias is not None:
                br_scope.declare(br.alias, Konkret("".join(br.type_name)))
            for stmt in br.body:
                resolve_statement(stmt, br_scope)
            continue
        inst, env = _instancja_struktury(sd)
        if linked is not None:
            for i, j in _mapowanie_członka(inst.głowa, linked.głowa):
                ogranicz(inst.args[i], linked.args[j])
                ogranicz(linked.args[j], inst.args[i])
        br_scope = scope.child_for(br, "body")
        for fid in br.fields:
            f = _find_field_for_ident(sd, fid)
            if f is None:
                raise TypeCheckError(
                    f"'{'_'.join(fid.surface)}' nie jest polem struktury "
                    f"'{'_'.join(br.type_name)}' (linia {br.line})")
            br_scope.declare(fid, elaborate(f.type, env))
        if br.alias is not None:
            br_scope.declare(br.alias, inst)
        subject = node.subject.resolved
        if isinstance(subject, ast.Identifier):
            br_scope.declare_shadow(subject, inst)
        for stmt in br.body:
            resolve_statement(stmt, br_scope)


def _find_field_for_ident(struct_def, ident):
    for key in ident.scope_keys:
        for f in struct_def.fields:
            if any(ast.scope_key_matches(key, k) for k in f.name.scope_keys):
                return f
    return None


# ---------- wyrażenia ----------

_COMPARISON_OPS = {"<", ">", "<=", ">="}
_EQUALITY_OPS = {"=", "!=", "≡"}


def resolve_expression(node, scope):
    if isinstance(node, ast.Phrase):
        node = node.resolved
    if isinstance(node, ast.Word):
        node = node.value
    if isinstance(node, ast.Typed):
        expr_t = resolve_expression(node.expr, scope)
        explicit_t = elaborate(node.type, {}, fresh_unknown=True)
        ogranicz(expr_t, explicit_t)
        return explicit_t
    if isinstance(node, ast.BinOp):
        return resolve_bin_op(node, scope)
    if isinstance(node, ast.UnaryOp):
        t = resolve_expression(node.operand, scope)
        ogranicz(t, Konkret("Liczba"))
        return Konkret("Liczba")
    if isinstance(node, ast.Not):
        t = resolve_expression(node.operand, scope)
        ogranicz(t, Konkret("Przełącznik"))
        return Konkret("Przełącznik")
    if isinstance(node, (ast.And, ast.Or)):
        for strona in (node.left, node.right):
            t = resolve_expression(strona, scope)
            ogranicz(t, Konkret("Przełącznik"))
        return Konkret("Przełącznik")
    if isinstance(node, ast.FunctionCall):
        return resolve_function_call(node, scope)
    if isinstance(node, ast.FunctionRef):
        return resolve_function_ref(node, scope)
    if isinstance(node, ast.Apply):
        return resolve_apply(node, scope)
    if isinstance(node, ast.TryCall):
        return resolve_try_call(node, scope)
    if isinstance(node, ast.GetterChain):
        return resolve_getter_chain(node, scope)
    if isinstance(node, ast.StructCreation):
        return resolve_struct_creation(node, scope)
    if isinstance(node, ast.StructArg):
        raise TypeCheckError(
            "wewnętrzny błąd interpretera: argument konstrukcji struktury "
            "poza konstrukcją — zgłoś ten program jako bug")
    if isinstance(node, ast.Identifier):
        return scope.get_type(node)
    if isinstance(node, ast.IntLit):
        return Konkret("Liczba")
    if isinstance(node, ast.StrLit):
        if find_type_alias("Tekst") is None:
            raise TypeCheckError(
                "literał tekstowy wymaga aliasu typu 'Tekst' "
                "(np. uwzględnij przygrywka.ć)")
        return elaborate(ast.TypeRef(head=("Tekst",), args=[]), {})
    if isinstance(node, ast.CharLit):
        return Konkret("Znak")
    if isinstance(node, ast.BoolLit):
        return Konkret("Przełącznik")


def _porównywalne(t0, t1, op):
    """Porównywalność równościowa BEZ przepływu wartości: głowy znanych
    konkretów muszą być identyczne albo mieć wspólną unię; argumenty
    porównywanych konkretów wiążą się wzajemnie (lista znaków ≠ lista
    liczb)."""
    g0 = _głowy_znane(t0)
    g1 = _głowy_znane(t1)
    if not g0 or not g1:
        return
    wspólna = najmniejsza_unia(g0 | g1)
    if g0 != g1 and wspólna is None:
        raise TypeCheckError(
            f"wartości typów {sorted(g0)} i {sorted(g1)} są "
            f"nieporównywalne ('{op}') — nie łączy ich żadna unia")
    m0, m1 = _zmaterializuj(t0), _zmaterializuj(t1)
    if (m0 is not None and m1 is not None and m0.głowa == m1.głowa
            and m0.args and len(m0.args) == len(m1.args)):
        for i, (x, y) in enumerate(zip(m0.args, m1.args)):
            _inwariantnie(m0.głowa, i, x, y)
    elif m0 is not None and m1 is not None and wspólna is not None:
        u = _unia_applied(wspólna)
        for m in (m0, m1):
            if m.głowa != wspólna:
                for i, j in _mapowanie_członka(m.głowa, wspólna):
                    ogranicz(m.args[i], u.args[j])
                    ogranicz(u.args[j], m.args[i])


def resolve_bin_op(node, scope):
    t0 = resolve_expression(node.left, scope)
    t1 = resolve_expression(node.right, scope)
    if node.op in _EQUALITY_OPS:
        _porównywalne(t0, t1, node.op)
        return Konkret("Przełącznik")
    ogranicz(t0, Konkret("Liczba"))
    ogranicz(t1, Konkret("Liczba"))
    if node.op in _COMPARISON_OPS:
        return Konkret("Przełącznik")
    return Konkret("Liczba")


def resolve_function_call(node, scope):
    fdt = find_fdt(node.name)
    if fdt is None:
        raise TypeCheckError(
            f"wywołanie niezadeklarowanej funkcji "
            f"'{'_'.join(node.name.surface)}'")
    fname = "_".join(node.name.surface)
    if id(fdt) in _bieżąca_składowa:
        # Rekursja (także wzajemna) monomorficzna: współdzielimy zmienne
        # sygnatury zamiast instancjonować.
        arg_types, ret_type = fdt.arg_types, fdt.ret_type
    else:
        arg_types, ret_type = instantiate(fdt)
    if fdt.extern and isinstance(ret_type, Zmienna):
        nota = (f"pochodzi z externa '{fname}' (czysta świeżość) i musi "
                f"zostać ustalony przez użycie")
        if nota not in ret_type.ślad:
            ret_type.ślad.append(nota)
    for i, (slot, p) in enumerate(zip(arg_types, node.params)):
        t = resolve_expression(p, scope)
        _set_note(f"argument {i + 1} wywołania '{fname}'")
        ogranicz(t, slot)
    return ret_type


def resolve_function_ref(node, scope):
    fdt = find_fdt_by_key(node.key)
    if fdt is None:
        raise TypeCheckError(
            f"referencja do nieznanej funkcji '{'_'.join(node.key)}' "
            f"(linia {node.line})")
    if id(fdt) in _bieżąca_składowa:
        arg_types, ret_type = fdt.arg_types, fdt.ret_type
    else:
        arg_types, ret_type = instantiate(fdt)
    return Konkret(ARROW, tuple(arg_types) + (ret_type,))


def resolve_apply(node, scope):
    t_f = resolve_expression(node.fn, scope)
    args = [new_type() for _ in node.args]
    ret = new_type()
    strzałka = Konkret(ARROW, tuple(args) + (ret,))
    try:
        ogranicz(t_f, strzałka)
    except TypeCheckError as e:
        if "liczba argumentów" in str(e):
            raise TypeCheckError(
                f"zastosowanie (linia {node.line}) przekazuje "
                f"{len(node.args)} argument(ów) — {e}") from None
        raise
    for slot, w in zip(args, node.args):
        t = resolve_expression(w.value, scope)
        _set_note(f"argument zastosowania (linia {node.line})")
        ogranicz(t, slot)
    return ret


def _require_rezultat(line):
    ud = find_union_def(("Rezultat",))
    if ud is None or {"".join(m) for m in ud.members} != {"Sukces", "Błąd"}:
        raise TypeCheckError(
            f"wywołanie z obsługą błędu '?' (linia {line}) wymaga "
            f"zadeklarowanej unii 'Rezultat to Sukces albo Błąd'")


def resolve_try_call(node, scope):
    _require_rezultat(node.line)
    if scope.root_fdt is None:
        raise TypeCheckError(
            f"wywołanie z obsługą błędu '?' (linia {node.line}) jest "
            f"dozwolone tylko w ciele funkcji")
    if isinstance(node.call, ast.Apply):
        t = resolve_apply(node.call, scope)
    else:
        t = resolve_function_call(node.call, scope)
    r_inst = _unia_applied("Rezultat")
    ogranicz(t, r_inst)
    _set_note(f"propagacja Błędu przez '?' (linia {node.line})")
    ogranicz(Konkret("Błąd"), scope.root_fdt.ret_type)
    # Odpakowana wartość Sukcesu = niejawny argument-element Rezultatu.
    mapa = _mapowanie_członka("Sukces", "Rezultat")
    if mapa and r_inst.args:
        return r_inst.args[mapa[0][1]]
    return new_type()


def resolve_struct_creation(node, scope):
    sd = find_struct_def(node.type_name)
    if sd is None and find_type_alias(node.type_name) is not None:
        raise TypeCheckError(
            f"nie można utworzyć wartości przez alias typu "
            f"'{'_'.join(node.type_name)}' — użyj bezpośrednio typu "
            f"docelowego")
    if sd is None and find_union_def(node.type_name) is not None:
        raise TypeCheckError(
            f"nie można utworzyć wartości typu wariantowego "
            f"'{'_'.join(node.type_name)}' — utwórz jedną z jego struktur")
    if sd is None:
        for a in node.args:
            if a.value is not None:
                resolve_expression(a.value, scope)
        return Konkret("".join(node.type_name))
    inst, env = _instancja_struktury(sd)
    for a in node.args:
        f = _find_field(sd, a.field_name)
        field_t = elaborate(f.type, env)
        if a.value is not None:
            value_t = resolve_expression(a.value, scope)
            _set_note(f"pole '{'_'.join(a.field_name[0])}' konstrukcji "
                      f"'{'_'.join(node.type_name)}'")
        else:
            value_t = scope.get_type(f.name)
            _set_note(f"skrót 'z {'_'.join(a.field_name[0])}' konstrukcji "
                      f"'{'_'.join(node.type_name)}'")
        ogranicz(value_t, field_t)
    return inst


def _find_field(struct_def, field_key):
    for f in struct_def.fields:
        if any(ast.scope_key_matches(field_key, k)
               for k in f.name.scope_keys):
            return f
    return None


# ---------- łańcuchy dopełniaczowe ----------

def _struktury_z_polem(field_name):
    ret = []
    for decl in module.body:
        if isinstance(decl, ast.StructDef):
            if _find_field_for_ident(decl, field_name) is not None:
                ret.append(decl)
    return ret


def _chain_przez_strukturę(chain, struct):
    """Czy łańcuch (bez ostatniego słowa, od zewnątrz) domyka się na
    strukturze `struct`? → (instancja bazy, typ wyniku) albo None."""
    base_inst, cur_env = _instancja_struktury(struct)
    cur_sd = struct
    result_t = None
    for ident in reversed(chain):
        if cur_sd is None:
            return None
        f = _find_field_for_ident(cur_sd, ident)
        if f is None:
            return None
        result_t = elaborate(f.type, cur_env)
        cur_sd, cur_env = _jako_struktura(result_t)
    return base_inst, result_t


def _jako_struktura(t):
    """Struktura, na którą typ wskazuje (do zejścia w głąb łańcucha)."""
    m = t if isinstance(t, Konkret) else None
    if m is None:
        return None, {}
    sd = find_struct_def((m.głowa,))
    if sd is None:
        return None, {}
    env = {}
    for p, a in zip(sd.params, m.args):
        for lemmas in p.name.lemmas_set:
            env["".join(lemmas)] = a
    return sd, env


def resolve_getter_chain(node, scope):
    penultimate_word = node.chain[-2]
    structs = _struktury_z_polem(penultimate_word)
    candidates = []
    for s in structs:
        res = _chain_przez_strukturę(node.chain[:-1], s)
        if res is not None:
            candidates.append((s, res[0], res[1]))
    field_surface = "_".join(penultimate_word.surface)
    line = getattr(node.chain[0], "line", None)
    if not candidates:
        surfaces = " ".join("_".join(w.surface) for w in node.chain)
        if structs:
            cand = ", ".join(sorted("_".join(s.name) for s in structs))
            detail = (f"pole '{field_surface}' mają struktury: {cand}, "
                      f"ale żadna nie domyka dalszej części łańcucha")
        else:
            detail = f"żadna struktura nie ma pola '{field_surface}'"
        raise TypeCheckError(
            f"nie można zresolvować łańcucha dopełniaczowego '{surfaces}' "
            f"(linia {line}) — {detail}")
    base_t = scope.get_type(node.chain[-1])
    znane = _fakty_dolne(base_t)
    if not znane and isinstance(base_t, Zmienna):
        # Brak faktów — górne granice działają jak FILTR kandydatów
        # (`x ≤ Gałąź` dopuszcza członków unii, nie orzeka, że x nią jest).
        dozwolone = set()
        for g, _ in base_t.górne:
            if isinstance(g, Konkret):
                dozwolone.add(g.głowa)
                dozwolone |= (członkowie(g.głowa) or set())
        if dozwolone:
            przefiltrowani = [c for c in candidates
                              if "".join(c[0].name) in dozwolone]
            if przefiltrowani:
                candidates = przefiltrowani
    if znane:
        przeżyli = [c for c in candidates if "".join(c[0].name) in znane]
        if not przeżyli:
            # Chain przez wartość typu unii: podpowiedz zawężenie.
            for głowa in znane:
                czł = członkowie(głowa)
                if czł is not None:
                    warianty = sorted(
                        "".join(s.name) for s, _, _ in candidates
                        if "".join(s.name) in czł)
                    if warianty:
                        nic = " (może być Niczym)" if "Nic" in czł else ""
                        raise TypeCheckError(
                            f"pole '{field_surface}' czytane z wartości "
                            f"typu unii '{głowa}'{nic} (linia {line}) — "
                            f"zawęź dopasowaniem `jest:`; pole ma wariant "
                            f"{', '.join(warianty)}")
            raise TypeCheckError(
                f"pole '{field_surface}' (linia {line}) nie występuje "
                f"w typie {sorted(znane)} podstawy łańcucha")
        candidates = przeżyli
    if len(candidates) == 1:
        s, base_inst, result_t = candidates[0]
        _set_note(f"łańcuch '{field_surface} …' (linia {line})")
        ogranicz(base_t, base_inst)
        ogranicz(base_inst, base_t)
        return result_t
    # Wielu kandydatów: dysjunkcja na bazie; wynik = świeża zmienna
    # z dysjunkcją głów wyników (rozstrzygną inne wystąpienia).
    if isinstance(base_t, Zmienna):
        alt = {"".join(s.name): inst for s, inst, _ in candidates}
        if base_t.alternatywy is None:
            base_t.alternatywy = alt
        else:
            wspólne = {h: k for h, k in base_t.alternatywy.items()
                       if h in alt}
            if wspólne:
                base_t.alternatywy = wspólne
                if len(wspólne) == 1:
                    (h,) = wspólne
                    wybrany = next(c for c in candidates
                                   if "".join(c[0].name) == h)
                    return wybrany[2]
    wynik = new_type()
    for _, _, rt in candidates:
        m = rt if isinstance(rt, Konkret) else _zmaterializuj(rt)
        if m is not None:
            if wynik.alternatywy is None:
                wynik.alternatywy = {}
            wynik.alternatywy.setdefault(m.głowa, m)
    return wynik
