import sys
import time
from dataclasses import dataclass, replace

import lexer

CASES = {"nom", "gen", "dat", "acc", "inst", "loc", "voc"}
EXCLUDED_QUALIFIERS = ("daw.", "gwar.", "przest.")
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


@dataclass(frozen=True)
class VerbForm:
    pos: str
    mood: str = None
    aspect: str = None
    number: str = None
    person: str = None
    gender: str = None


@dataclass(frozen=True)
class MorphAnalysis:
    pos: str
    case: frozenset
    lemma: str
    verb_form: VerbForm = None  # not None iff pos in VERB_POS


# Mapowanie POS → pozycje sub-tagów po `pos:` w tagu SGJP.
_VERB_TAG_LAYOUT = {
    "inf":    {"aspect": 0},
    "imps":   {"aspect": 0},
    "pcon":   {"aspect": 0},
    "impt":   {"number": 0, "person": 1, "aspect": 2},
    "fin":    {"number": 0, "person": 1, "aspect": 2},
    "bedzie": {"number": 0, "person": 1, "aspect": 2},
    "fut":    {"number": 0, "person": 1, "aspect": 2},
    "praet":  {"number": 0, "gender": 1, "aspect": 2},
    "winien": {"number": 0, "gender": 1, "aspect": 2},
    "cond":   {"number": 0, "gender": 1, "person": 2, "aspect": 3},
}


def _parse_verb_form(pos, tag_parts):
    if pos not in VERB_POS:
        return None
    layout = _VERB_TAG_LAYOUT.get(pos, {})
    sub = tag_parts[1:]
    fields = {}
    for name, idx in layout.items():
        fields[name] = sub[idx] if idx < len(sub) else None
    return VerbForm(pos=pos, mood=MOOD_BY_POS.get(pos), **fields)


def load(path):
    print(f"Loading {path}...", file=sys.stderr)
    t0 = time.time()
    db = {}
    preps = {}
    citation = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            form, lemma_field, tag = parts[0], parts[1], parts[2]
            qualifiers = parts[4] if len(parts) > 4 else ""
            lemma = lemma_field.partition(":")[0]
            tag_parts = tag.split(":")
            pos = tag_parts[0]
            case = None
            for tp in tag_parts[1:]:
                cases_here = frozenset(p for p in tp.split(".") if p in CASES)
                if cases_here:
                    case = cases_here
                    break
            verb_form = _parse_verb_form(pos, tag_parts)
            db.setdefault(form, []).append(
                MorphAnalysis(pos=pos, case=case, lemma=lemma, verb_form=verb_form)
            )
            if pos == "prep" and case and not any(q in qualifiers for q in EXCLUDED_QUALIFIERS):
                preps.setdefault(lemma, set()).update(case)
            if (
                pos in PARTICIPLE_POS
                and len(tag_parts) >= 4
                and tag_parts[1] == "sg"
                and "nom" in tag_parts[2].split(".")
                and "m1" in tag_parts[3].split(".")
                and tag_parts[-1] == "aff"
            ):
                citation[(pos, lemma)] = form
    for anas in db.values():
        for i, ana in enumerate(anas):
            if ana.pos in PARTICIPLE_POS:
                anas[i] = replace(ana, lemma=citation.get((ana.pos, ana.lemma), ana.lemma))
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
