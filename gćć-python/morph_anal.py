import sys
import time
from typing import NamedTuple

import lexer

CASES = {"nom", "gen", "dat", "acc", "inst", "loc", "voc"}
NUMBERS = {"sg", "pl"}
# SGJP rodzajowe tagi → znormalizowany rodzaj koarse (m/f/n).
# m1 (męskoosobowy), m2 (męskozwierzęcy), m3 (męskorzeczowy) → wszystkie m.
# n1/n2 → n. p1/p2/p3 (gramatyczne kategorie pluralne) ignorowane — nie są rodzajem słowa.
_GENDER_MAP = {
    "m1": "m", "m2": "m", "m3": "m", "m": "m",
    "f": "f",
    "n1": "n", "n2": "n", "n": "n",
}
PARTICIPLE_POS = {"pact", "ppas"}
VERB_POS = frozenset({
    "fin", "impt", "inf", "imps", "praet", "pcon",
    "winien", "bedzie", "fut", "cond",
})


class MorphAnalysis(NamedTuple):
    pos: str
    case: frozenset
    number: str  # "sg" / "pl" / None (verby, prep, atom)
    gender: frozenset  # frozenset znormalizowanych rodzajów (m/f/n) lub None
    lemma: str
    tag: str  # surowy tag SGJP, np. "fin:sg:pri:imperf"
    qualifier: str  # SGJP qualifier (np. "ryb.", "przest.", "pot.") lub ""


_SENTINEL = object()


def _morpho_for_tag(tag_parts):
    """Wyciąga (case, number, gender) z parts tagu SGJP.
    Iteruje raz po częściach — wykrywa po przynależności wartości do CASES,
    NUMBERS, _GENDER_MAP. Zwraca pierwsze trafienie każdej kategorii."""
    case = None
    number = None
    gender = None
    for tp in tag_parts[1:]:
        atoms = tp.split(".")
        if case is None:
            cases_here = frozenset(p for p in atoms if p in CASES)
            if cases_here:
                case = cases_here
                continue
        if number is None:
            for p in atoms:
                if p in NUMBERS:
                    number = p
                    break
            if number is not None:
                continue
        if gender is None:
            genders_here = frozenset(
                _GENDER_MAP[p] for p in atoms if p in _GENDER_MAP
            )
            if genders_here:
                gender = genders_here
                continue
    return case, number, gender


def load(path):
    print(f"Loading {path}...", file=sys.stderr)
    t0 = time.time()
    db = {}
    preps = {}
    citation = {}
    morpho_cache = {}
    morpho_cache_get = morpho_cache.get
    # Bind w lokalnej zmiennej żeby zminimalizować dispatch w gorącej pętli.
    tuple_new = tuple.__new__
    Ma = MorphAnalysis
    verb_pos = VERB_POS
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            form, lemma_field, tag = parts[0], parts[1], parts[2]
            qualifiers = parts[4] if len(parts) > 4 else ""
            lemma = lemma_field.partition(":")[0]
            # partition jest szybsze od full split gdy chcemy tylko pos
            pos = tag.partition(":")[0]
            # Cache po tagu — jeden lookup zwraca (case, number, gender).
            cached = morpho_cache_get(tag, _SENTINEL)
            tag_parts = None  # leniwe — split tylko gdy potrzebny
            if cached is _SENTINEL:
                tag_parts = tag.split(":")
                if pos in verb_pos:
                    cached = (None, None, None)
                else:
                    cached = _morpho_for_tag(tag_parts)
                morpho_cache[tag] = cached
            case, number, gender = cached
            # tuple.__new__ omija NamedTuple.__new__ (walidację argumentów),
            # wraca do konstruktora w C — istotne przy 5M wpisach.
            db.setdefault(form, []).append(
                tuple_new(Ma, (pos, case, number, gender, lemma, tag, qualifiers))
            )
            if pos == "prep" and case:
                preps.setdefault(lemma, set()).update(case)
            if pos in PARTICIPLE_POS:
                if tag_parts is None:
                    tag_parts = tag.split(":")
                if (
                    len(tag_parts) >= 4
                    and tag_parts[1] == "sg"
                    and "nom" in tag_parts[2].split(".")
                    and "m1" in tag_parts[3].split(".")
                    and tag_parts[-1] == "aff"
                ):
                    citation[(pos, lemma)] = form
    for anas in db.values():
        for i, ana in enumerate(anas):
            if ana.pos in PARTICIPLE_POS:
                anas[i] = ana._replace(lemma=citation.get((ana.pos, ana.lemma), ana.lemma))
    print(f"Loaded {len(db)} forms in {time.time() - t0:.1f}s", file=sys.stderr)
    return db, preps


def analyze(tokens, db):
    out = []
    for tok in tokens:
        kind, value = tok[0], tok[1]
        line = getattr(tok, "line", None)
        if kind is lexer.Token.WORD:
            # SGJP keyed by lowercase; surface może być mixed-case po refaktorze.
            seg_analyses = [db.get(seg.lower(), []) for seg in value]
            out.append(lexer.Tok(kind, value, seg_analyses, line=line))
        else:
            out.append(lexer.Tok(kind, value, None, line=line))
    return out


_ADJ_LIKE_POS = {"adj", "pact", "ppas"}


def _cap_lemma(lemma, surface_seg):
    """Capitalize lemma jeśli surface zaczynał się wielką literą.
    Pozwala rozróżnić typ (`Forma` → `("Forma",)`) od zmiennej (`forma` →
    `("forma",)`) w przestrzeni lemm."""
    if surface_seg and surface_seg[0].isupper() and lemma:
        return lemma[:1].upper() + lemma[1:]
    return lemma


_CASE_NAMES_LOC = {
    "nom": "mianowniku",
    "gen": "dopełniaczu",
}


def canonical(token, *, required_case=None):
    """Kanonikalizacja tokenu do tuple lemm per segment.

    Tryb lenient (`required_case=None`, default): per-segment preferuj
    analizy adj-like, matchuj citation form (`a.lemma == seg.lower()`),
    inaczej fallback do `pool[0]`. Używane dla keywordów (`canonical(t) ==
    ("aby",)`) i prepów — surface zwykle citation, fallback rzadko odpala.

    Tryb strict (`required_case="nom"` lub `"gen"`): per-segment filtruj
    analizy po `required_case in case`. Każdy segment z analizami musi mieć
    ≥1 takich analiz i wszystkie muszą mieć tę samą lemmę — inaczej
    `InterpreterError`. Używane dla nazw typów (`nom`) i nazwy struktury
    po `definicja` (`gen`).

    Segmenty bez analiz (non-Polish, single-letter) → użyj surface.
    Kapitalizacja: `_cap_lemma` aplikowane per-segment na finalny lemmat —
    typy pisane capitalized (`(Tekst)` → `("Tekst",)`) odróżniają się od
    zmiennych (`tekst`) w przestrzeni lemm."""
    from ast_nodes import InterpreterError
    _, value, analyses = token[0], token[1], token[2]
    line = getattr(token, "line", None)
    out = []
    for seg, anas in zip(value, analyses):
        if not anas or len(seg) == 1:
            out.append(seg)  # zachowaj oryginalny case (np. single-letter "X")
            continue
        if required_case is None:
            # Lenient: adj-priority + citation match + pool[0] fallback.
            # seg.lower() chroni przed pułapką homograficzną dla capital
            # surface (`Pora` → "pora", nie pool[0]="por").
            pool = [a for a in anas if a.pos in _ADJ_LIKE_POS] or anas
            chosen = next((a for a in pool if a.lemma == seg.lower()), pool[0])
            out.append(_cap_lemma(chosen.lemma, seg))
            continue
        # Strict: case-filter + uniqueness.
        case_anas = [a for a in anas if a.case and required_case in a.case]
        case_name = _CASE_NAMES_LOC.get(required_case, required_case)
        if not case_anas:
            raise InterpreterError(
                f"nazwa typu '{'_'.join(value)}' musi być w {case_name}; "
                f"segment '{seg}' nie ma formy {case_name}",
                line=line,
            )
        lemmas = {a.lemma for a in case_anas}
        if len(lemmas) > 1:
            opts = ", ".join(sorted(lemmas))
            raise InterpreterError(
                f"nazwa typu '{'_'.join(value)}' jest niejednoznaczna w "
                f"{case_name} — pasuje do wielu lemm: {opts}. "
                f"Użyj jednoznacznej formy.",
                line=line,
            )
        out.append(_cap_lemma(next(iter(lemmas)), seg))
    return tuple(out)
