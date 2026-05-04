import sys
import time

import lexer

CASES = {"nom", "gen", "dat", "acc", "inst", "loc", "voc"}
EXCLUDED_QUALIFIERS = ("daw.", "gwar.", "przest.")


def load(path):
    print(f"Loading {path}...", file=sys.stderr)
    t0 = time.time()
    db = {}
    preps = {}
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


def canonical(token):
    _, value, analyses = token
    out = []
    for seg, anas in zip(value, analyses):
        if not anas or len(seg) == 1:
            out.append(seg)
            continue
        chosen = next((a for a in anas if a[2] == seg), anas[0])
        out.append(chosen[2])
    return tuple(out)
