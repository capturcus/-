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
    `alternatywy`: None albo dict głowa→Konkret — dysjunkcja kandydatów
    (`alternatywy_nota` pamięta, skąd dysjunkcja pochodzi).
    `etykieta`: ludzki opis zmiennej do komunikatów („parametr 'liczbę'
    funkcji 'dodać'") zamiast surowego tN."""
    number: int
    dolne: list = field(default_factory=list)
    górne: list = field(default_factory=list)
    alternatywy: object = None
    alternatywy_nota: object = None
    ślad: list = field(default_factory=list)
    etykieta: object = None

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


def new_type(etykieta=None):
    global last_type
    v = Zmienna(number=last_type, etykieta=etykieta)
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


def czy_głowa_podtypem(pod, nad, _widziane=None):
    """Podtypowanie nominalne PRZECHODNIE: S ≤ S; S ≤ U gdy S jest
    członkiem U albo członkiem członka-unii (hierarchia:
    Labrador ≤ Pies ≤ Zwierzę). Cykle unii odrzuca resolver, ale
    strażnik `_widziane` i tak chroni przed zapętleniem."""
    if pod == nad:
        return True
    czł = członkowie(nad)
    if czł is None:
        return False
    if pod in czł:
        return True
    if _widziane is None:
        _widziane = set()
    if nad in _widziane:
        return False
    _widziane.add(nad)
    return any(członkowie(m) is not None
               and czy_głowa_podtypem(pod, m, _widziane)
               for m in czł)


def członkowie_przechodni(głowa, _widziane=None):
    """LIŚCIE hierarchii unii: struktury (i Nic) osiągalne przez
    zagnieżdżone unie. None gdy `głowa` nie jest unią."""
    czł = członkowie(głowa)
    if czł is None:
        return None
    if _widziane is None:
        _widziane = set()
    if głowa in _widziane:
        return set()
    _widziane.add(głowa)
    liście = set()
    for m in czł:
        pod = członkowie_przechodni(m, _widziane)
        liście |= pod if pod is not None else {m}
    return liście


def najmniejsza_unia(głowy):
    """Najmniejsza zadeklarowana unia pokrywająca wszystkie `głowy`
    (przechodnio — głowa może być liściem zagnieżdżonej unii).
    Rozmiar mierzony liczbą LIŚCI. None gdy żadna nie pokrywa;
    remis minimalnych → błąd."""
    if module is None:
        return None
    kandydatki = []
    for decl in module.body:
        if not isinstance(decl, ast.UnionDef):
            continue
        uh = "".join(decl.name)
        if all(czy_głowa_podtypem(g, uh) for g in głowy):
            kandydatki.append((len(członkowie_przechodni(uh)), uh))
    if not kandydatki:
        return None
    kandydatki.sort()
    if len(kandydatki) > 1 and kandydatki[0][0] == kandydatki[1][0]:
        raise TypeCheckError(
            f"głowy {sorted(głowy)} pokrywa więcej niż jedna minimalna "
            f"unia: {kandydatki[0][1]}, {kandydatki[1][1]} — dodaj "
            f"adnotację typu")
    return kandydatki[0][1]


def _union_param_names(głowa, _widziane=None):
    """Niejawne parametry unii: dziedziczone po nazwach od członków —
    struktur wprost, a przez zagnieżdżone unie rekurencyjnie —
    w kolejności pierwszego wystąpienia; [] gdy brak."""
    ud = find_union_def((głowa,)) if module is not None else None
    if ud is None:
        return []
    if _widziane is None:
        _widziane = set()
    if głowa in _widziane:
        return []
    _widziane.add(głowa)
    params = []
    for m in ud.members:
        sd = find_struct_def(m)
        if sd is not None:
            nowe = [frozenset("".join(l) for l in p.name.lemmas_set)
                    for p in sd.params]
        else:
            nowe = _union_param_names("".join(m), _widziane)
        for names in nowe:
            if not any(names & s for s in params):
                params.append(names)
    return params


def _param_names_dla(głowa):
    """Nazwy parametrów typu (struktura → własne, unia → niejawne)."""
    sd = find_struct_def((głowa,))
    if sd is not None:
        return [frozenset("".join(l) for l in p.name.lemmas_set)
                for p in sd.params]
    if członkowie(głowa) is not None:
        return _union_param_names(głowa)
    return []


def _mapowanie_członka(członek, unia):
    """Pary (i, j): i-ty parametr członka (struktury ALBO pod-unii)
    odpowiada j-temu niejawnemu argumentowi unii (po nazwach)."""
    m_params = _param_names_dla(członek)
    u_params = _union_param_names(unia)
    pary = []
    for i, names in enumerate(m_params):
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
        args.append(captured if captured is not None
                    else new_type(f"niejawny argument "
                                  f"'{min(names, key=len)}' "
                                  f"unii '{głowa}'"))
    return Konkret(głowa, tuple(args))


def _env_z_instancji(sd, args):
    """Env nazwa-parametru → argument dla instancji struktury `sd`."""
    env = {}
    for p, a in zip(sd.params, args):
        for lemmas in p.name.lemmas_set:
            env["".join(lemmas)] = a
    return env


def _instancja_struktury(sd):
    """Świeża instancja struktury: Konkret(nazwa, świeże argi) + env
    nazwa-parametru → arg."""
    nazwa = "".join(sd.name)
    fresh = [
        new_type(f"parametr "
                 f"'{min(('' .join(l) for l in p.name.lemmas_set), key=len)}'"
                 f" struktury '{nazwa}'")
        for p in sd.params
    ]
    return Konkret(nazwa, tuple(fresh)), _env_z_instancji(sd, fresh)


# ---------- biunifikacja ----------

def _głowy_dolnych(var):
    return {t.głowa for t, _ in var.dolne if isinstance(t, Konkret)}


LIMIT_POSZLAK = 12


def _opis_zmiennej(v):
    return v.etykieta or f"zmienna typowa {v!r}"


def _render_typu(t, widziane=None):
    """Typ do komunikatu: argumenty konstruktorów zmaterializowane
    (Ogniwo[Liczba], nie Ogniwo[t5]); zmienna → jej materializacja
    albo '?'."""
    if widziane is None:
        widziane = set()
    if isinstance(t, Zmienna):
        if t in widziane:
            return "…"
        widziane.add(t)
        try:
            m = _zmaterializuj(t)
        except TypeCheckError:
            m = None
        return _render_typu(m, widziane) if m is not None else "?"
    if t is None:
        return "?"
    if not t.args:
        return t.głowa
    if t.głowa == ARROW:
        args = [_render_typu(a, widziane) for a in t.args]
        return f"({', '.join(args[:-1])}) → {args[-1]}"
    return (t.głowa + "["
            + ", ".join(_render_typu(a, widziane) for a in t.args) + "]")


def _unia_ze_składem(h):
    czł = członkowie(h)
    if czł is None:
        return h
    return f"{h} ({' albo '.join(sorted(czł))})"


def _poszlakownik(var):
    """Pełny zrzut ograniczeń zmiennej: wszystkie granice z liniami —
    programista sam wskazuje, która poszlaka jest błędna."""
    linie = [f"{_opis_zmiennej(var)}:"]

    def blok(tytuł, pary):
        if not pary:
            return
        linie.append(f"  {tytuł}:")
        for t, nota in pary[:LIMIT_POSZLAK]:
            wiersz = f"    • {_render_typu(t)}"
            if nota:
                wiersz += f" — {nota}"
            linie.append(wiersz)
        if len(pary) > LIMIT_POSZLAK:
            linie.append(f"    … i {len(pary) - LIMIT_POSZLAK} dalszych "
                         f"(najstarsze pominięte)")

    blok("wpływa do niej", var.dolne)
    blok("wymaga się od niej", var.górne)
    if var.alternatywy is not None:
        opcje = ", ".join(sorted(var.alternatywy))
        skąd = f" — {var.alternatywy_nota}" if var.alternatywy_nota else ""
        linie.append(f"  możliwości (dysjunkcja): {opcje}{skąd}")
    return "\n".join(linie)


def _odległość(a, b):
    """Odległość edycyjna (Levenshtein) — do podpowiedzi literówek."""
    if abs(len(a) - len(b)) > 2:
        return 3
    poprz = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        bież = [i]
        for j, cb in enumerate(b, 1):
            bież.append(min(poprz[j] + 1, bież[-1] + 1,
                            poprz[j - 1] + (ca != cb)))
        poprz = bież
    return poprz[-1]


def _podobne(cel, kandydaci, prog=2):
    """Kandydaci w odległości ≤ prog od celu, od najbliższych."""
    trafienia = sorted(
        ((k, _odległość(cel, k)) for k in kandydaci),
        key=lambda p: p[1])
    return [k for k, d in trafienia if d <= prog and k != cel][:3]


def _sugestia_unii(głowy):
    """Podpowiedź przy niełączliwych dolnych: prawie pasujące unie
    (ze składem i brakami) + szablon deklaracji."""
    linie = []
    for decl in (module.body if module is not None else []):
        if not isinstance(decl, ast.UnionDef):
            continue
        uh = "".join(decl.name)
        czł = {"".join(m) for m in decl.members}
        pokryte = {g for g in głowy if czy_głowa_podtypem(g, uh)}
        if pokryte and pokryte != set(głowy):
            poza = sorted(set(głowy) - pokryte)
            linie.append(f"    • {_unia_ze_składem(uh)} — nie obejmuje: "
                         f"{', '.join(poza)}")
    out = (f"\n  żadna zadeklarowana unia nie łączy "
           f"{{{', '.join(sorted(głowy))}}}")
    if linie:
        out += "; prawie pasują:\n" + "\n".join(linie)
    out += (f"\n  jeśli to zamierzone, zadeklaruj unię: "
            f"`NazwaUnii to {' albo '.join(sorted(głowy))}`")
    return out


def _msg_konflikt(a, b, noty_a=(), noty_b=()):
    msg = f"nie można zunifikować {_render_typu(a)} z {_render_typu(b)}"
    linie = []
    if noty_a:
        linie.append(f"  poszlaki o {_render_typu(a)}: "
                     + "; ".join(noty_a[-LIMIT_POSZLAK:]))
    if noty_b:
        linie.append(f"  poszlaki o {_render_typu(b)}: "
                     + "; ".join(noty_b[-LIMIT_POSZLAK:]))
    if linie:
        msg += " — zdecyduj, która poszlaka jest błędna:\n" + "\n".join(linie)
    return msg


def _z_poszlakownikiem(e, var):
    """Dołóż do błędu pełny zrzut ograniczeń zmiennej, przez którą
    konflikt przepłynął (raz na zmienną, z limitem długości)."""
    opis = _opis_zmiennej(var)
    tekst = str(e)
    if (not var.dolne and not var.górne) or opis in tekst \
            or len(tekst) > 4000:
        return e
    return TypeCheckError(f"{tekst}\n{_poszlakownik(var)}")


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
        opcje = ", ".join(_unia_ze_składem(h)
                          for h in sorted(var.alternatywy))
        skąd = (f" ({var.alternatywy_nota})"
                if var.alternatywy_nota else "")
        raise TypeCheckError(
            f"typ '{głowa_faktu}' nie pasuje do żadnej z możliwości "
            f"{{{opcje}}} zebranych z wcześniejszych użyć{skąd}")
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
            nadchodzi = f"\n  nadchodzi:\n    • {_render_typu(typ)}"
            if _current_note:
                nadchodzi += f" — {_current_note}"
            nadchodzi += "   ← sprzeczna z powyższymi"
            raise TypeCheckError(
                f"nie można zunifikować {_render_typu(stare)} "
                f"z {_render_typu(typ)} — zdecyduj, która poszlaka "
                f"jest błędna:\n{_poszlakownik(var)}{nadchodzi}"
                + _sugestia_unii(nowe))
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
    Granice tylko przybywają; para (pod, nad) przetwarzana raz.
    Domknięcie przechodnie ITERACYJNE (kolejka robocza) — rekurencja
    pythonowa pękała na głębokich strukturach (drzewa AVL)."""
    kolejka = [(pod, nad, None)]

    def wstaw(a, b, nota):
        # Filtr przy WKŁADANIU: bez niego kolejka puchnie duplikatami
        # (setki milionów odrzutów przy głębokich strukturach).
        if a is not b and (id(a), id(b)) not in _pary:
            kolejka.append((a, b, nota))

    while kolejka:
        p, n, nota = kolejka.pop()
        if p is n:
            continue
        klucz = (id(p), id(n))
        if klucz in _pary:
            continue
        _pary.add(klucz)
        _pary_żywe.append((p, n))
        try:
            if isinstance(p, Konkret) and isinstance(n, Konkret):
                _ogranicz_konkrety(p, n)
            elif isinstance(p, Zmienna) and isinstance(n, Zmienna):
                # Krawędź var-var: pojedyncza, BEZ materializacji
                # domknięcia przechodniego po zmiennych (to kwadrat
                # krawędzi, który instancjacja by potem kopiowała).
                # Przez krawędź przepychamy wyłącznie KONKRETY; inwariant:
                # każda zmienna zna wszystkie osiągalne konkretne granice,
                # więc łączliwość dolnych i konflikty konkret-konkret
                # wykrywane są tak samo jak przy pełnym domknięciu.
                _dodaj_górną(p, n)
                _dodaj_dolną(n, p)
                for d, nd in list(p.dolne):
                    if isinstance(d, Konkret):
                        wstaw(d, n, nd)
                for g, ng in list(n.górne):
                    if isinstance(g, Konkret):
                        wstaw(p, g, ng)
            elif isinstance(p, Zmienna):
                if _dodaj_górną(p, n):
                    for d, nd in list(p.dolne):
                        wstaw(d, n, nd)
            else:
                if _dodaj_dolną(n, p):
                    for g, ng in list(n.górne):
                        wstaw(p, g, ng)
        except TypeCheckError as e:
            # Dekoracja drogą wartości (nota granicy pośredniczącej)
            # i poszlakownikami zmiennych, przez które konflikt płynie.
            if nota and nota not in str(e):
                e = TypeCheckError(f"{e}\n  ↳ droga wartości: {nota}")
            for strona in (p, n):
                if isinstance(strona, Zmienna):
                    e = _z_poszlakownikiem(e, strona)
            raise e from None


def _ogranicz_konkrety(pod, nad):
    if pod.głowa == ARROW or nad.głowa == ARROW:
        if pod.głowa != nad.głowa:
            raise TypeCheckError(_msg_konflikt(pod, nad))
        if len(pod.args) != len(nad.args):
            raise TypeCheckError(
                f"niezgodna liczba argumentów funkcji: wartość funkcyjna "
                f"{_render_typu(pod)} przyjmuje {len(pod.args) - 1}, "
                f"a użycie {_render_typu(nad)} wymaga "
                f"{len(nad.args) - 1}")
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
    if członkowie(pod.głowa) is not None \
            and czy_głowa_podtypem(nad.głowa, pod.głowa):
        # Unia w slocie wariantu: w runtime wartość może być innym
        # członkiem — podpowiedz zawężenie zamiast surowego konfliktu.
        inni = sorted((członkowie(pod.głowa) or set()) - {nad.głowa})
        raise TypeCheckError(
            f"wartość typu unii '{_unia_ze_składem(pod.głowa)}' nie "
            f"mieści się w slocie oczekującym dokładnie "
            f"{_render_typu(nad)} — w runtime może być: "
            f"{', '.join(inni)}; zawęź dopasowaniem `jest:` przed "
            f"przekazaniem")
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
    if t.alternatywy is not None and len(t.alternatywy) == 1:
        # Dysjunkcja zwężona do jednej głowy (np. wynik łańcucha, którego
        # wszyscy kandydaci zwracają ten sam typ) — to już materializacja.
        (jedyny,) = t.alternatywy.values()
        return jedyny
    if t.alternatywy is not None and len(t.alternatywy) > 1:
        # Najmniejszy kandydat zgodny z FAKTAMI (join semantyki solvera):
        # fakt-struktura wybiera strukturę, fakt-unia (albo dwa fakty
        # różnych wariantów) wybiera unię. Kandydaci-unie łańcuchów po
        # polach wspólnych współistnieją z kandydatami-strukturami —
        # dopiero fakty rozstrzygają, przez co czytamy.
        fakty = {x.głowa for x, _ in t.dolne if isinstance(x, Konkret)}
        for x, _ in t.dolne:
            if isinstance(x, Zmienna):
                m = _zmaterializuj(x, widziane=widziane)
                if m is not None:
                    fakty.add(m.głowa)
        if fakty:
            zgodne = {
                h: k for h, k in t.alternatywy.items()
                if all(f == h or czy_głowa_podtypem(f, h) for f in fakty)
            }
            if zgodne:
                rozmiar = {h: len(członkowie_przechodni(h) or {h})
                           for h in zgodne}
                porządek = sorted(zgodne, key=lambda h: rozmiar[h])
                if (len(porządek) == 1
                        or rozmiar[porządek[0]] < rozmiar[porządek[1]]):
                    return zgodne[porządek[0]]
        opcje = ", ".join(_unia_ze_składem(h)
                          for h in sorted(t.alternatywy))
        skąd = (f" (możliwości zebrane: {t.alternatywy_nota})"
                if t.alternatywy_nota else "")
        # Dyskryminatory: członkowie występujący tylko w jednej opcji.
        wskazówka = ""
        składy = {h: (członkowie_przechodni(h) or {h})
                  for h in t.alternatywy}
        unikaty = []
        for h, czł in składy.items():
            reszta = set().union(*(c for g, c in składy.items() if g != h))
            for w in sorted(czł - reszta):
                unikaty.append(f"{w} (tylko {h})")
        if unikaty:
            wskazówka = (f"; rozstrzygnie użycie wariantu-dyskryminatora: "
                         f"{', '.join(unikaty[:4])} — albo adnotacja")
        raise TypeCheckError(
            f"typ pasuje do wielu możliwości: {opcje}{skąd} — dodaj "
            f"adnotację typu{wskazówka}")
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
            raise TypeCheckError(
                f"nie można zunifikować {_render_typu(konkrety[0])} "
                f"z {_render_typu(konkrety[-1])} — zdecyduj, która "
                f"poszlaka jest błędna:\n{_poszlakownik(t)}"
                + _sugestia_unii(głowy))
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
        new_t = new_type(f"zmienna '{'_'.join(identifier.surface)}'"
                         + (f" ({_ctx_fun})" if _ctx_fun else ""))
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
        new_t = new_type(f"zmienna '{'_'.join(identifier.surface)}'"
                         + (f" ({_ctx_fun})" if _ctx_fun else ""))
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
    n = new_type(t.etykieta)
    memo[t] = n
    n.ślad = list(t.ślad)
    n.alternatywy_nota = t.alternatywy_nota
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
                params = _union_param_names(h)
                przykład = (min(params[0], key=len) if params else "NAZWIE")
                raise TypeCheckError(
                    f"typ wariantowy '{h}' nie przyjmuje argumentów typu "
                    f"pozycyjnych — aplikacja na unii jest wyłącznie "
                    f"nazwana: `{h} o {przykład} Typ`")
            bound = {
                "".join(ta.name): elaborate(ta.type, env, fresh_unknown,
                                            alias_args=True)
                for ta in tref.args
            } if tref.args else None
            if bound:
                znane = _union_param_names(h)
                for nm in bound:
                    if not any(nm in names for names in znane):
                        opisy = []
                        for i in range(len(znane)):
                            pname, origin = _param_pedigree(h, i)
                            if pname:
                                opisy.append(f"{pname} (z definicji "
                                             f"{origin})")
                        dostępne = ", ".join(opisy) or "brak"
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
        znane_typy = {"".join(d.name) for d in module.body
                      if isinstance(d, (ast.StructDef, ast.UnionDef,
                                        ast.TypeAlias))} | BUILTINS
        sugestie = _podobne(h, znane_typy)
        hint = (f" — czy chodziło o "
                f"{', '.join(repr(s) for s in sugestie)}?"
                if sugestie else "")
        raise TypeCheckError(
            f"nieznany typ '{h}' w deklaracji aliasu '{seen[0]}'{hint}")
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
            fname = "_".join(decl.name.surface)
            arg_types = [
                elaborate(p.type, fenv, fresh_unknown=True)
                if p.type is not None else new_type(
                    f"parametr '{'_'.join(p.name.surface)}' "
                    f"funkcji '{fname}'")
                for p in decl.params
            ]
            if decl.return_type is not None:
                ret = elaborate(decl.return_type, fenv, fresh_unknown=True)
                annotated = True
            else:
                ret = new_type(f"wynik funkcji '{fname}'")
                annotated = False
            for h, v in fenv.items():
                if isinstance(v, Zmienna) and v.etykieta is None:
                    v.etykieta = (f"parametr typu '{h}' sygnatury "
                                  f"'{fname}'")
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
            fname = "_".join(decl.name.surface)
            for h, v in fenv.items():
                if isinstance(v, Zmienna) and v.etykieta is None:
                    v.etykieta = (f"parametr typu '{h}' sygnatury "
                                  f"externa '{fname}'")
            fun_decls.append((decl.name, fdt))

    # Punkt wejścia jest JEDYNĄ funkcją o dwóch dozwolonych sygnaturach:
    # `aby działać:` (bez argumentów) albo `aby działać dla argumentów:`
    # — wtedy parametr to argumenty wywołania programu (po `--` w CLI),
    # przybite do Listy o elemencie Tekst.
    for decl, fdt in module_funcs:
        if ("działać",) not in decl.name.lemmas_set:
            continue
        if len(decl.params) > 1:
            raise TypeCheckError(
                "funkcja 'działać' przyjmuje najwyżej JEDEN parametr — "
                "listę argumentów wywołania programu (Lista o elemencie "
                "Tekst); argumenty CLI podaje się po znaczniku `--`")
        if len(decl.params) == 1:
            if (find_union_def(("Lista",)) is None
                    or find_type_alias(("Tekst",)) is None):
                raise TypeCheckError(
                    "parametr 'działać' to argumenty wywołania programu "
                    "typu Lista o elemencie Tekst — wymaga typów Lista "
                    "i Tekst (uwzględnij przygrywka.ć)")
            _set_note("argumenty wywołania programu (parametr 'działać')")
            typ = elaborate(ast.TypeRef(head=("Lista",), args=[
                ast.TypeArg(prep=("o",), case=None, name=("element",),
                            type=ast.TypeRef(head=("Tekst",), args=[]))
            ]), {})
            ogranicz(typ, fdt.arg_types[0])
            ogranicz(fdt.arg_types[0], typ)

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
                try:
                    ogranicz(Konkret("Nic"), fdt.ret_type)
                except TypeCheckError as e:
                    raise TypeCheckError(
                        f"funkcja '{_ctx_fun}' jest częściowa: któraś "
                        f"ścieżka nie kończy się `zwróć`, więc zwraca "
                        f"Nic — dopisz `zwróć` na końcu albo zadeklaruj "
                        f"unię z Nic — {e}") from None
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
                # Klasyfikacja przyczyny po kształcie grafu granic.
                przyczyna = ""
                rada = "użyj wartości strukturalnie albo dodaj adnotację typu"
                zrzut = ""
                if isinstance(t, Zmienna):
                    if (not t.dolne and not t.górne
                            and t.alternatywy is None and not t.ślad):
                        przyczyna = ("nigdzie nie otrzymuje wartości ani "
                                     "nie jest wymagana — martwa zmienna? ")
                        rada = ("usuń ją albo nadaj jej wartość")
                    elif not any(isinstance(d, Konkret) or
                                 isinstance(d, Zmienna)
                                 for d, _ in t.dolne) and t.górne:
                        przyczyna = "znana wyłącznie z wymagań — "
                        rada = ("domyślkowanie niejednoznaczne; dodaj "
                                "adnotację typu")
                    if t.dolne or t.górne or t.alternatywy is not None:
                        zrzut = "\n" + _poszlakownik(t)
                raise TypeCheckError(
                    f"nie można wywnioskować konkretnego typu zmiennej "
                    f"'{'_'.join(ident.surface)}' (linia {line}); "
                    f"{przyczyna}pozostało {t!r}{źródło}"
                    f"{zrzut}\n  — {rada}")


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

def _nota_o_głowie(t, głowa):
    """Nota granicy, która wprowadziła daną głowę na zmienną — „skąd
    wiadomo, że wartość jest tego typu"."""
    if not isinstance(t, Zmienna):
        return None
    for d, n in list(t.dolne) + list(t.górne):
        if isinstance(d, Konkret) and d.głowa == głowa and n:
            return n
    for d, _ in t.dolne:
        if isinstance(d, Zmienna):
            n = _nota_o_głowie(d, głowa)
            if n:
                return n
    return None


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


def _liście_gałęzi(b):
    return członkowie_przechodni(b) or {b}


def _union_for_match(subject_t, branch_heads, line):
    branch_set = set(branch_heads)
    # Wyczerpujące dopasowanie w hierarchii: gałęzie (struktury albo
    # pod-unie) muszą ROZŁĄCZNIE pokrywać wszystkie liście unii —
    # {Kot, Pies} i {Kot, Labrador, Chihuahua} pokrywają Zwierzę.
    cands = []
    for decl in module.body:
        if not isinstance(decl, ast.UnionDef):
            continue
        liście_u = członkowie_przechodni("".join(decl.name))
        pokryte = set()
        ok = True
        for b in branch_set:
            lb = _liście_gałęzi(b)
            if not lb <= liście_u or pokryte & lb:
                ok = False
                break
            pokryte |= lb
        if ok and pokryte == liście_u:
            cands.append(decl)
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
            czł = członkowie_przechodni(głowa)
            if czł is not None:
                pokryte, nakładki = set(), []
                for b in sorted(branch_set):
                    lb = _liście_gałęzi(b)
                    if pokryte & lb:
                        nakładki.append(b)
                    pokryte |= lb
                if nakładki:
                    raise TypeCheckError(
                        f"dopasowanie 'jest:' (linia {line}) ma "
                        f"nakładające się gałęzie — "
                        f"{', '.join(nakładki)} pokrywa warianty ujęte "
                        f"już w innej gałęzi (np. pod-unia obok jej "
                        f"członka); usuń węższą albo szerszą gałąź")
                brakuje = czł - pokryte
                nadmiar = pokryte - czł
                skąd = _nota_o_głowie(subject_t, głowa)
                pochodzenie = (f" (podmiot jest "
                               f"'{_unia_ze_składem(głowa)}'"
                               + (f"; skąd: {skąd}" if skąd else "") + ")")
                if brakuje:
                    raise TypeCheckError(
                        f"dopasowanie 'jest:' (linia {line}) na wartości "
                        f"typu '{głowa}'{pochodzenie} — brakuje gałęzi: "
                        f"{', '.join(sorted(brakuje))} (dopisz je albo "
                        f"dodaj `inaczej:`)")
                if nadmiar:
                    raise TypeCheckError(
                        f"dopasowanie 'jest:' (linia {line}) ma gałęzie "
                        f"spoza unii: {', '.join(sorted(nadmiar))}"
                        f"{pochodzenie}")
        # Prawie-trafienia: unie o niepustym przecięciu z gałęziami.
        blisko = []
        for decl in module.body:
            if not isinstance(decl, ast.UnionDef):
                continue
            czł = {"".join(m) for m in decl.members}
            if czł & branch_set:
                braki = sorted(czł - branch_set)
                nadmiar = sorted(branch_set - czł)
                opis = _unia_ze_składem("".join(decl.name))
                szczegóły = []
                if braki:
                    szczegóły.append(f"brakuje: {', '.join(braki)}")
                if nadmiar:
                    szczegóły.append(f"nadmiarowe: {', '.join(nadmiar)}")
                blisko.append(f"    • {opis} — {'; '.join(szczegóły)}")
        podpowiedź = ("\n  najbliżej:\n" + "\n".join(blisko[:4])
                      if blisko else "")
        raise TypeCheckError(
            f"gałęzie dopasowania 'jest:' (linia {line}) — "
            f"{', '.join(sorted(branch_set))} — nie odpowiadają członkom "
            f"żadnego zadeklarowanego typu wariantowego{podpowiedź}")
    opts = ", ".join(sorted("".join(c.name) for c in cands))
    raise TypeCheckError(
        f"dopasowanie 'jest:' (linia {line}) pasuje do wielu typów "
        f"wariantowych: {opts} — dodaj adnotację typu")


def _unions_for_partial_match(subject_t, branch_heads, line):
    branch_set = set(branch_heads)
    cands = [
        decl for decl in module.body
        if isinstance(decl, ast.UnionDef)
        and all(czy_głowa_podtypem(b, "".join(decl.name))
                for b in branch_set)
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
                subject_t.alternatywy_nota = (
                    f"dopasowanie z 'inaczej:' (linia {node.line})")
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
            # Gałąź bez struktury: wbudowane Nic albo POD-UNIA
            # (hierarchia) — pod-unia zawęża podmiot do siebie i dzieli
            # niejawne argumenty z unią podmiotu (po nazwach).
            br_scope = scope.child_for(br, "body")
            głowa_br = "".join(br.type_name)
            if członkowie(głowa_br) is not None:
                inst = _unia_applied(głowa_br)
                if linked is not None:
                    for i, j in _mapowanie_członka(głowa_br, linked.głowa):
                        ogranicz(inst.args[i], linked.args[j])
                        ogranicz(linked.args[j], inst.args[i])
                if br.alias is not None:
                    br_scope.declare(br.alias, inst)
                subject = node.subject.resolved
                if isinstance(subject, ast.Identifier):
                    br_scope.declare_shadow(subject, inst)
            elif br.alias is not None:
                br_scope.declare(br.alias, Konkret(głowa_br))
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
                pola = ", ".join(
                    f"{'_'.join(pf.name.surface)} "
                    f"({'_'.join(pf.type.head)})"
                    for pf in sd.fields) or "brak pól"
                sugestia = _podobne(
                    "_".join(fid.surface),
                    ["_".join(pf.name.surface) for pf in sd.fields])
                hint = (f"; czy chodziło o "
                        f"{', '.join(repr(s) for s in sugestia)}?"
                        if sugestia else "")
                raise TypeCheckError(
                    f"'{'_'.join(fid.surface)}' nie jest polem struktury "
                    f"'{'_'.join(br.type_name)}' (linia {br.line}) — "
                    f"{'_'.join(br.type_name)} ma pola: {pola}{hint}")
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
    if isinstance(node, ast.Bind):
        return resolve_bind(node, scope)
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
        try:
            ogranicz(t, slot)
        except TypeCheckError as e:
            if f"wywołania '{fname}'" in str(e).splitlines()[0]:
                raise
            oczekiwano = _render_typu(slot)
            otrzymano = _render_typu(t)
            kontrast = ""
            if oczekiwano != "?" and otrzymano != "?":
                kontrast = (f": oczekiwano {oczekiwano}, "
                            f"otrzymano {otrzymano}")
            raise TypeCheckError(
                f"argument {i + 1} wywołania '{fname}'{kontrast} — {e}"
            ) from None
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


def resolve_bind(node, scope):
    """`zwiąż F z X` — bejcowanie: ogranicza pierwsze k slotów strzałki
    odbiorcy, typem wartości jest strzałka pozostałych slotów.

    Odbiorca MUSI materializować się do konkretnej strzałki (referencja
    gerundialna albo zmienna z już ustaloną strzałką): „strzałka o co
    najmniej k argumentach" wymagałaby polimorfizmu wierszowego, którego
    solver nie ma — wiązanie na nieustalonej wartości funkcyjnej (np. na
    parametrze generycznym) jest odrzucane wprost."""
    t_f = resolve_expression(node.fn, scope)
    m = _zmaterializuj(t_f)
    if m is None or m.głowa != ARROW:
        otrzymano = _render_typu(t_f)
        kontrast = f" (otrzymano: {otrzymano})" if otrzymano != "?" else ""
        raise TypeCheckError(
            f"'zwiąż' (linia {node.line}) wymaga wartości funkcyjnej "
            f"o znanej strzałce{kontrast} — użyj referencji gerundialnej "
            f"(np. 'zwiąż dodanie z dwa') albo zmiennej, której funkcyjność "
            f"jest już ustalona")
    n = len(m.args) - 1
    k = len(node.args)
    if k > n:
        raise TypeCheckError(
            f"'zwiąż' (linia {node.line}) wiąże {k} argument(ów), "
            f"a funkcja przyjmuje {n}")
    for i, w in enumerate(node.args):
        t = resolve_expression(w.value, scope)
        _set_note(f"argument {i + 1} wiązania 'zwiąż' (linia {node.line})")
        ogranicz(t, m.args[i])
    return Konkret(ARROW, m.args[k:])


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


def _różnica_pól(a, b, sloty):
    """Pierwsza różnica między typami pola z dwóch wariantów; None, gdy
    typy są WSPÓLNE. Wspólne są: ta sama zmienna (jeden slot unii),
    konkrety o tej samej głowie i wspólnych argumentach oraz dwie zmienne
    ŚWIEŻE per wystąpienie (obie spoza slotów — pole „luźne", jak przy
    odczycie ze struktury bez zadeklarowanego parametru).

    Zwrócona para dwóch Zmiennych to niewspółdzielony slot parametru
    (slot śledzi argument per instancja unii, świeża nie — dlatego slot
    kontra świeża też jest różnicą); każda inna para to różnica
    strukturalna."""
    if a is b:
        return None
    if isinstance(a, Zmienna) and isinstance(b, Zmienna):
        if id(a) not in sloty and id(b) not in sloty:
            return None
        return (a, b)
    if (isinstance(a, Konkret) and isinstance(b, Konkret)
            and a.głowa == b.głowa and len(a.args) == len(b.args)):
        for x, y in zip(a.args, b.args):
            r = _różnica_pól(x, y, sloty)
            if r is not None:
                return r
        return None
    return (a, b)


def _opis_slotu(inst, var):
    """Nazwa i rodowód slotu parametru unii; zmienna spoza slotów to
    parametr wolny (pole bez zadeklarowanego parametru w definicji)."""
    for i, a in enumerate(inst.args):
        if a is var:
            nazwa, origin = _param_pedigree(inst.głowa, i)
            if nazwa is not None:
                return f"'{nazwa}' (z definicji '{origin}')"
    return "wolny (pole nie wiąże go z parametrem swojej definicji)"


def _typ_pola(inst, ident):
    """Typ pola `ident` czytanego z Konkretu `inst`.

    Struktura → typ pola w env instancji. Unia → pole WSPÓLNE wszystkim
    liściom (przechodnio), o typie IDENTYCZNYM w env współdzielonych
    slotów unii — parametry o tej samej nazwie u członków to jeden slot,
    więc identyczność wychodzi naturalnie, a parametry nazwane różnie
    dają różne sloty i czytelny błąd.

    → (typ, None) przy sukcesie; (None, diagnoza) gdy pole nie daje się
    czytać przez unię (diagnoza = pełny komunikat); (None, None) gdy
    `inst` w ogóle nie ma pola (kandydat pada cicho)."""
    nazwa_pola = "_".join(ident.surface)
    sd = find_struct_def((inst.głowa,))
    if sd is not None:
        f = _find_field_for_ident(sd, ident)
        if f is None:
            return None, None
        return elaborate(f.type, _env_z_instancji(sd, inst.args)), None
    liście = członkowie_przechodni(inst.głowa)
    if liście is None:
        return None, None
    typy = {}
    brakujące = []
    for m in sorted(liście):
        msd = find_struct_def((m,))
        if msd is None:  # Nic — nie ma pól
            brakujące.append(m)
            continue
        f = _find_field_for_ident(msd, ident)
        if f is None:
            brakujące.append(m)
            continue
        # Parametry członka wskazują współdzielone sloty unii (po nazwie).
        wybrane = [inst.args[j] for _i, j in _mapowanie_członka(m, inst.głowa)]
        typy[m] = elaborate(f.type, _env_z_instancji(msd, wybrane))
    unia_opis = _unia_ze_składem(inst.głowa)
    if brakujące:
        nic = (" — wariant Nic nie ma pól (wartość może być Niczym)"
               if "Nic" in brakujące else "")
        mają = f" mają je: {', '.join(sorted(typy))};" if typy else ""
        return None, (
            f"pole '{nazwa_pola}' nie jest wspólne wariantom unii "
            f"'{unia_opis}' —{mają} brakuje go w: "
            f"{', '.join(sorted(brakujące))}{nic}; czytanie pola przez "
            f"unię wymaga pola w każdym wariancie (o identycznym typie) "
            f"— zawęź dopasowaniem `jest:`")
    sloty = {id(a) for a in inst.args}
    wzorzec_m, wzorzec = next(iter(typy.items()))
    for m, t in typy.items():
        różnica = _różnica_pól(t, wzorzec, sloty)
        if różnica is None:
            continue
        if all(isinstance(x, Zmienna) for x in różnica):
            slot_a = _opis_slotu(inst, różnica[0])
            slot_b = _opis_slotu(inst, różnica[1])
            return None, (
                f"pole '{nazwa_pola}' jest wspólne wariantom unii "
                f"'{unia_opis}', ale jego parametr nie jest "
                f"współdzielony: parametr {slot_b} i parametr {slot_a} "
                f"to osobne sloty unii — sloty łączą się po NAZWIE "
                f"parametru; nazwij parametry jednakowo we wszystkich "
                f"wariantach, żeby pole miało wspólny typ")
        return None, (
            f"pole '{nazwa_pola}' jest wspólne wariantom unii "
            f"'{unia_opis}' z nazwy, ale nie z typu: "
            f"{wzorzec_m} ma '{_render_typu(wzorzec)}', "
            f"{m} ma '{_render_typu(t)}' — czytanie pola przez unię "
            f"wymaga identycznego typu we wszystkich wariantach; "
            f"zawęź dopasowaniem `jest:` albo ujednolić typy pól")
    return wzorzec, None


def _chain_przez_deklarację(chain, decl):
    """Prowadzi łańcuch (bez ostatniego słowa, od zewnątrz) przez
    deklarację `decl` — strukturę ALBO unię z polami wspólnymi.

    → (instancja bazy, typ wyniku, None) gdy łańcuch się domyka;
      (None, None, powód) gdy pęka — powód to pełne zdanie diagnozy,
      jedyne źródło prawdy o przyczynie dla wszystkich komunikatów."""
    if isinstance(decl, ast.StructDef):
        cur, _ = _instancja_struktury(decl)
    else:
        cur = _unia_applied("".join(decl.name))
    base_inst = cur
    poprzednie = "_".join(decl.name)
    result_t = None
    for ident in reversed(chain):
        nazwa = "_".join(ident.surface)
        if not isinstance(cur, Konkret):
            return None, None, (
                f"'{poprzednie}' nie jest strukturą — nie można "
                f"czytać z niego pola '{nazwa}'")
        result_t, diag = _typ_pola(cur, ident)
        if result_t is None:
            if diag is not None:
                return None, None, diag
            sd = find_struct_def((cur.głowa,))
            if sd is None:
                return None, None, (
                    f"'{poprzednie}' ({cur.głowa}) nie jest strukturą — "
                    f"nie można czytać z niego pola '{nazwa}'")
            pola = ", ".join("_".join(pf.name.surface)
                             for pf in sd.fields) or "brak"
            return None, None, (
                f"struktura '{cur.głowa}' nie ma pola '{nazwa}' "
                f"(ma: {pola})")
        poprzednie = nazwa
        cur = result_t if isinstance(result_t, Konkret) else None
    return base_inst, result_t, None


def resolve_getter_chain(node, scope):
    penultimate_word = node.chain[-2]
    structs = _struktury_z_polem(penultimate_word)
    # Kandydaci łańcucha: struktury z polem + KAŻDA unia (pole wspólne
    # wszystkim liściom, o identycznym typie, czyta się i pisze przez
    # unię bez zawężania). Powody odpadnięcia zbierane per deklaracja —
    # jedno źródło dla wszystkich komunikatów poniżej.
    unie = [d for d in module.body if isinstance(d, ast.UnionDef)]
    candidates = []
    diagnozy = {}
    for decl in structs + unie:
        inst, result_t, powód = _chain_przez_deklarację(
            node.chain[:-1], decl)
        if inst is not None:
            candidates.append((decl, inst, result_t))
        else:
            diagnozy["".join(decl.name)] = powód
    field_surface = "_".join(penultimate_word.surface)
    line = getattr(node.chain[0], "line", None)
    if not candidates:
        surfaces = " ".join("_".join(w.surface) for w in node.chain)
        if structs:
            cand = ", ".join(sorted("_".join(s.name) for s in structs))
            powody = "\n".join(
                f"    • {'_'.join(s.name)}: {diagnozy[''.join(s.name)]}"
                for s in structs[:4])
            detail = (f"pole '{field_surface}' mają struktury: {cand}, "
                      f"ale żadna nie domyka dalszej części łańcucha:\n"
                      f"{powody}")
        else:
            wszystkie_pola = {
                "_".join(pf.name.surface)
                for decl in module.body if isinstance(decl, ast.StructDef)
                for pf in decl.fields}
            sugestie = _podobne(field_surface, wszystkie_pola)
            hint = (f"; czy chodziło o "
                    f"{', '.join(repr(s) for s in sugestie)}?"
                    if sugestie else "")
            detail = (f"żadna struktura nie ma pola "
                      f"'{field_surface}'{hint}")
        raise TypeCheckError(
            f"nie można zresolvować łańcucha dopełniaczowego '{surfaces}' "
            f"(linia {line}) — {detail}")
    base_t = scope.get_type(node.chain[-1])
    znane = _fakty_dolne(base_t)
    if not znane and isinstance(base_t, Zmienna):
        # Górna granica o głowie będącej kandydatem rozstrzyga wprost:
        # adnotacja/wymaganie mówi „czytaj przez ten typ" — dla unii to
        # jedyny odczyt poprawny dla KAŻDEGO możliwego mieszkańca.
        głowy_górnych = {g.głowa for g, _ in base_t.górne
                         if isinstance(g, Konkret)}
        dokładni = [c for c in candidates
                    if "".join(c[0].name) in głowy_górnych]
        if len(dokładni) == 1:
            candidates = dokładni
        elif głowy_górnych:
            # Brak faktów — górne granice działają jak FILTR kandydatów
            # (`x ≤ Gałąź` dopuszcza członków unii, nie orzeka, że x nią
            # jest).
            dozwolone = set(głowy_górnych)
            for g in głowy_górnych:
                dozwolone |= (członkowie_przechodni(g) or set())
            przefiltrowani = [c for c in candidates
                              if "".join(c[0].name) in dozwolone]
            if przefiltrowani:
                candidates = przefiltrowani
    if znane:
        przeżyli = [c for c in candidates if "".join(c[0].name) in znane]
        if not przeżyli:
            # Chain przez wartość znanego typu, który odpadł z kandydatów
            # — powód z przebiegu mówi dokładnie dlaczego (brak pola
            # w wariancie / typ niewspólny / slot niewspółdzielony /
            # łańcuch pęka głębiej).
            for głowa in znane:
                if głowa in diagnozy:
                    skąd = _nota_o_głowie(base_t, głowa)
                    pochodzenie = (
                        f"; wartość stała się unią: {skąd}"
                        if skąd and członkowie(głowa) is not None else "")
                    raise TypeCheckError(
                        f"{diagnozy[głowa]} (linia {line})"
                        f"{pochodzenie}")
            zrzut = ("\n" + _poszlakownik(base_t)
                     if isinstance(base_t, Zmienna)
                     and (base_t.dolne or base_t.górne) else "")
            pola_typu = ""
            for głowa in sorted(znane):
                sd_znany = find_struct_def((głowa,))
                if sd_znany is not None:
                    pola_typu = (f"; '{głowa}' ma pola: "
                                 + (", ".join(
                                     "_".join(pf.name.surface)
                                     for pf in sd_znany.fields) or "brak"))
            raise TypeCheckError(
                f"pole '{field_surface}' (linia {line}) nie występuje "
                f"w typie {sorted(znane)} podstawy łańcucha"
                f"{pola_typu}{zrzut}")
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
        base_t.alternatywy_nota = (f"łańcuch '{field_surface} …' "
                                   f"(linia {line})")
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
    wynik = new_type(f"wynik łańcucha '{field_surface} …' (linia {line})")
    wynik.alternatywy_nota = (f"łańcuch '{field_surface} …' o wielu "
                              f"kandydatach (linia {line})")
    for _, _, rt in candidates:
        m = rt if isinstance(rt, Konkret) else _zmaterializuj(rt)
        if m is not None:
            if wynik.alternatywy is None:
                wynik.alternatywy = {}
            wynik.alternatywy.setdefault(m.głowa, m)
    return wynik
