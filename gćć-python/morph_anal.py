import sys
import time
from typing import NamedTuple

import lexer

CASES = {"nom", "gen", "dat", "acc", "inst", "loc", "voc"}
PARTICIPLE_POS = {"pact", "ppas"}
VERB_POS = frozenset({
    "fin", "impt", "inf", "imps", "praet", "pcon",
    "winien", "bedzie", "fut", "cond",
})

MOOD_BY_POS = {
    "impt":   "rozkazujący",
    "cond":   "przypuszczający",
    "fin":    "oznajmujący",
    "praet":  "oznajmujący",
    "bedzie": "oznajmujący",
    "fut":    "oznajmujący",
    # inf, imps, pcon, winien — formy niefinitywne, brak trybu
}


class VerbForm(NamedTuple):
    pos: str
    mood: str = None
    aspect: str = None
    number: str = None
    person: str = None
    gender: str = None


_VERB_FORM_CACHE = {}


def _build_verb_form(pos, tag_parts):
    mood = MOOD_BY_POS.get(pos)
    n = len(tag_parts) - 1
    if pos == "inf" or pos == "imps" or pos == "pcon":
        return VerbForm(pos, mood, tag_parts[1] if n > 0 else None)
    if pos == "impt" or pos == "fin" or pos == "bedzie" or pos == "fut":
        return VerbForm(
            pos, mood,
            tag_parts[3] if n > 2 else None,  # aspect
            tag_parts[1] if n > 0 else None,  # number
            tag_parts[2] if n > 1 else None,  # person
        )
    if pos == "praet" or pos == "winien":
        return VerbForm(
            pos, mood,
            tag_parts[3] if n > 2 else None,  # aspect
            tag_parts[1] if n > 0 else None,  # number
            None,                              # person
            tag_parts[2] if n > 1 else None,  # gender
        )
    if pos == "cond":
        return VerbForm(
            pos, mood,
            tag_parts[4] if n > 3 else None,  # aspect
            tag_parts[1] if n > 0 else None,  # number
            tag_parts[3] if n > 2 else None,  # person
            tag_parts[2] if n > 1 else None,  # gender
        )
    return None


def _verb_form_for(pos, tag):
    """Lazy lookup z cache'em — unikalnych tagów czasownikowych jest ~100,
    więc kolejne wywołania trafiają w cache i nie alokują VerbForm."""
    if pos not in VERB_POS:
        return None
    cached = _VERB_FORM_CACHE.get(tag)
    if cached is not None:
        return cached
    vf = _build_verb_form(pos, tag.split(":"))
    _VERB_FORM_CACHE[tag] = vf
    return vf


class MorphAnalysis(NamedTuple):
    pos: str
    case: frozenset
    lemma: str
    tag: str  # surowy tag SGJP, np. "fin:sg:pri:imperf"

    @property
    def verb_form(self):
        return _verb_form_for(self.pos, self.tag)


def _case_for_tag(tag, tag_parts, cache):
    """Wyciąga frozenset casów z tagu, cache'ując po surowym tagu.
    SGJP ma ~tysiąc unikalnych tagów, ale 5M wpisów — cache hit rate ~99%."""
    cached = cache.get(tag)
    if cached is not _SENTINEL:
        return cached
    case = None
    for tp in tag_parts[1:]:
        cases_here = frozenset(p for p in tp.split(".") if p in CASES)
        if cases_here:
            case = cases_here
            break
    cache[tag] = case
    return case


_SENTINEL = object()


def load(path):
    print(f"Loading {path}...", file=sys.stderr)
    t0 = time.time()
    db = {}
    preps = {}
    citation = {}
    case_cache = {}
    case_cache_get = case_cache.get
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
            # Cache po tagu — Python sam wyhashuje string.
            case = case_cache_get(tag, _SENTINEL)
            tag_parts = None  # leniwe — split tylko gdy potrzebny
            if case is _SENTINEL:
                tag_parts = tag.split(":")
                case = None
                if pos not in verb_pos:
                    for tp in tag_parts[1:]:
                        cases_here = frozenset(p for p in tp.split(".") if p in CASES)
                        if cases_here:
                            case = cases_here
                            break
                case_cache[tag] = case
            # tuple.__new__ omija NamedTuple.__new__ (walidację argumentów),
            # wraca do konstruktora w C — istotne przy 5M wpisach.
            db.setdefault(form, []).append(
                tuple_new(Ma, (pos, case, lemma, tag))
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
    for kind, value in tokens:
        if kind is lexer.Token.WORD:
            seg_analyses = [db.get(seg, []) for seg in value]
            out.append((kind, value, seg_analyses))
        else:
            out.append((kind, value, None))
    return out


_ADJ_LIKE_POS = {"adj", "pact", "ppas"}


def canonical(token):
    _, value, analyses = token
    out = []
    for seg, anas in zip(value, analyses):
        if not anas or len(seg) == 1:
            out.append(seg)
            continue
        # Preferuj analizy adj-like (adj/pact/ppas) — dla form dwuznacznych jak
        # `zielonego` (adj `zielony` vs substantywizowane subst `zielone`)
        # wybieramy formę przymiotnikową rodzaju męskiego.
        pool = [a for a in anas if a.pos in _ADJ_LIKE_POS] or anas
        chosen = next((a for a in pool if a.lemma == seg), pool[0])
        out.append(chosen.lemma)
    return tuple(out)
