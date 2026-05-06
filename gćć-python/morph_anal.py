import sys
import time

import lexer

CASES = {"nom", "gen", "dat", "acc", "inst", "loc", "voc"}
EXCLUDED_QUALIFIERS = ("daw.", "gwar.", "przest.")
PARTICIPLE_POS = {"pact", "ppas"}


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
                parts = tp.split(".")
                cases_here = frozenset(p for p in parts if p in CASES)
                if cases_here:
                    case = cases_here
                    break
            db.setdefault(form, []).append((pos, case, lemma))
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
        for i, (pos, case, lemma) in enumerate(anas):
            if pos in PARTICIPLE_POS:
                anas[i] = (pos, case, citation.get((pos, lemma), lemma))
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
        pool = [a for a in anas if a[0] in _ADJ_LIKE_POS] or anas
        chosen = next((a for a in pool if a[2] == seg), pool[0])
        out.append(chosen[2])
    return tuple(out)
