"""Konstrukcja `Identifier` z tokenu morfologicznego.

Identyfikator multi-segment ma postać `[adj/pact/ppas]+ [subst]? [reszta]`.
Każdy segment z adj-readings I subst-readings może być interpretowany na dwa
sposoby — adj-czytanie kontynuuje prefix przymiotnikowy, subst-czytanie
zamyka prefix jako głowa rzeczownikowa.

`_enumerate_variants` produkuje WSZYSTKIE spójne interpretacje (każda z
parą lemma + case). Dispatcher kontekstowy w `expression.py` wybiera ten
wariant, który domyka lokalny konstrukt (struct arg, chain step, fcall slot).

Brak wariantów ≠ błąd identyfikatora — może oznaczać identyfikator funkcji
(verbal segment bez noun-like) lub atom bez form (single letter, single seg
bez analiz). Multi-seg z brakiem valid prefiksu jest błędem syntaktycznym.
"""

import lexer
from morph_anal import canonical, VERB_POS
from ast_nodes import Identifier, IdentifierError


_NOUN_LIKE = {"subst", "adj", "pact", "ppas"}
_ADJ_LIKE = ("adj", "pact", "ppas")


def is_prep(token, preps):
    if token is None or token[0] is not lexer.Token.WORD:
        return False
    canon = canonical(token)
    return len(canon) == 1 and canon[0] in preps


def make_identifier(tok):
    _, surface, analyses = tok[0], tok[1], tok[2]
    line = getattr(tok, "line", None)
    analyses_t = tuple(tuple(a) for a in analyses)
    try:
        variants = _enumerate_variants(surface, analyses_t)
    except IdentifierError as e:
        if e.line is None:
            e.line = line
        raise
    return Identifier(
        surface=surface,
        analyses=analyses_t,
        variants=variants,
        line=line,
    )


def _enumerate_variants(surface, analyses):
    """Wszystkie spójne interpretacje identyfikatora.

    Zwraca tuple[(lemmas_tuple, case_frozenset, rest_length), ...].
    `rest_length` = liczba passthrough-segmentów po subst-głowie
    (0 dla `[adj+][subst]`, 0 dla pure-adj bez subst, ≥1 gdy po subst
    są jeszcze segmenty doklejane jako reszta).
    Pusta krotka → identyfikator funkcji (verbal-only segment) lub atom
    bez form (single-seg opaque). Multi-seg z brakiem valid prefiksu →
    raise IdentifierError.
    """
    n_segs = len(surface)
    # Step 1: verb-only segment ⇒ identyfikator funkcji, brak wariantów.
    for seg, anas in zip(surface, analyses):
        if not anas or len(seg) == 1:
            continue
        poses = {a.pos for a in anas}
        if poses & VERB_POS and not (poses & _NOUN_LIKE):
            return ()

    # Step 2: per-seg readings — pogrupowane po (pos-grupa, lemma).
    # Każda unikalna lemma w grupie adj-like i subst dostaje osobny wybór
    # (z sumarycznymi cases ze swoich analiz). Dzięki temu np. "imieniem"
    # (lemmy "imienie" i "imię") generuje dwa warianty subst-czytania.
    seg_data = []
    for seg, anas in zip(surface, analyses):
        if len(seg) == 1 or not anas:
            seg_data.append({"opaque": True, "lemma": seg})
            continue
        adj_groups = {}    # lemma → cases (frozenset)
        subst_groups = {}
        for a in anas:
            if not a.case:
                continue
            if a.pos in _ADJ_LIKE:
                adj_groups[a.lemma] = adj_groups.get(a.lemma, frozenset()) | a.case
            elif a.pos == "subst":
                subst_groups[a.lemma] = subst_groups.get(a.lemma, frozenset()) | a.case
        adj_choices = list(adj_groups.items())   # [(lemma, cases), ...]
        subst_choices = list(subst_groups.items())
        # Lemma fallback dla „reszty" (segmenty po subst-głowie) — canonical-style.
        rest_pool = [a for a in anas if a.pos in _ADJ_LIKE] or list(anas)
        rest_lemma = next(
            (a.lemma for a in rest_pool if a.lemma == seg),
            rest_pool[0].lemma if rest_pool else seg,
        )
        seg_data.append({
            "opaque": False,
            "adj_choices": adj_choices,
            "subst_choices": subst_choices,
            "rest_lemma": rest_lemma,
        })

    # Step 3: backtrack.
    variants = []

    def backtrack(seg_i, lemmas, cases, had_subst, subst_at):
        if had_subst:
            # Reszta segmentów: passthrough z canonical-style lemma; case bez zmian.
            rest_lemmas = list(lemmas)
            for j in range(seg_i, n_segs):
                d = seg_data[j]
                rest_lemmas.append(d["lemma"] if d["opaque"] else d["rest_lemma"])
            rest_length = n_segs - subst_at - 1
            variants.append((tuple(rest_lemmas), cases, rest_length))
            return
        if seg_i == n_segs:
            # Doszliśmy do końca prefiksu bez subst-głowy. Akceptujemy gdy
            # cases niepuste — to single-seg adj/pact/ppas alone (np.
            # "obserwującego") albo multi-seg z adj-only (rzadkie ale OK).
            if cases is not None:
                variants.append((tuple(lemmas), cases, 0))
            return
        d = seg_data[seg_i]
        if d["opaque"]:
            # Opaque (single-letter lub bez analiz): passthrough, bez wpływu na case.
            backtrack(seg_i + 1, lemmas + [d["lemma"]], cases, had_subst, subst_at)
            return
        # Wariant: adj-czytanie (kontynuuje prefix). Jedna gałąź per unikalna lemma.
        for adj_lemma, adj_cases in d["adj_choices"]:
            new_cases = adj_cases if cases is None else (cases & adj_cases)
            if new_cases:
                backtrack(seg_i + 1, lemmas + [adj_lemma], new_cases, had_subst, subst_at)
        # Wariant: subst-czytanie (zamyka prefix jako głowa). Jedna gałąź per lemma.
        for subst_lemma, subst_cases in d["subst_choices"]:
            new_cases = subst_cases if cases is None else (cases & subst_cases)
            if new_cases:
                backtrack(seg_i + 1, lemmas + [subst_lemma], new_cases, had_subst=True, subst_at=seg_i)

    backtrack(0, [], None, False, None)

    if not variants:
        # Brak żadnej spójnej interpretacji.
        if n_segs == 1:
            # Single-seg atom — np. interj "och", qub bez noun-like form.
            # Zwracamy () — Identifier.case=None, segments=canonical (jak dotychczas).
            return ()
        # Multi-seg bez valid prefiksu — błąd syntaktyczny.
        raise IdentifierError(_ident_err(
            surface,
            f"pierwszy segment '{surface[0]}' nie jest ani przymiotnikiem, "
            f"ani rzeczownikiem, ani identyfikatorem funkcji",
        ))
    return tuple(variants)


def _ident_err(surface, reason):
    return (
        f"Niepoprawny identyfikator '{'_'.join(surface)}': {reason}. "
        f"Oczekiwana forma: [przymiotnik...] [rzeczownik] [reszta], "
        f"gdzie przymiotniki i rzeczownik zgadzają się w przypadku."
    )
