"""Konstrukcja `Identifier` z tokenu morfologicznego oraz walidacja przypadka.

Wyciągnięte z dawnego `Parser._ident` / `_validate_identifier_case`, żeby parser
strukturalny i parser ekspresji mogły dzielić tę samą logikę.
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
    _, surface, analyses = tok
    segments = canonical(tok)
    analyses_t = tuple(tuple(a) for a in analyses)
    case = _validate_identifier_case(surface, analyses_t)
    return Identifier(
        segments=segments, surface=surface, case=case, analyses=analyses_t,
    )


def _validate_identifier_case(surface, analyses):
    # Jeśli któryś segment ma POS czasownikową ALE nie ma żadnej rzeczownikowej
    # (subst/adj/pact/ppas), identyfikator MUSI być wyrażeniem czasownikowym
    # (nazwą funkcji) — czasownik nie ma gramatycznego przypadka, więc case=None.
    for seg, anas in zip(surface, analyses):
        if not anas or len(seg) == 1:
            continue
        poses = {a.pos for a in anas}
        if poses & VERB_POS and not (poses & _NOUN_LIKE):
            return None
    adj_per_seg = []
    subst_per_seg = []
    has_morph = False
    for seg, anas in zip(surface, analyses):
        if len(seg) == 1 or not anas:
            adj_per_seg.append(None)
            subst_per_seg.append(None)
            continue
        has_morph = True
        adj_cases = frozenset()
        subst_cases = frozenset()
        for ana in anas:
            if not ana.case:
                continue
            if ana.pos in _ADJ_LIKE:
                adj_cases |= ana.case
            elif ana.pos == "subst":
                subst_cases |= ana.case
        adj_per_seg.append(adj_cases)
        subst_per_seg.append(subst_cases)
    if not has_morph:
        return None
    cases = None
    had_subst = False
    prefix_len = 0
    n_segs = len(adj_per_seg)
    for i, (adj, sub) in enumerate(zip(adj_per_seg, subst_per_seg)):
        if adj is None and sub is None:
            prefix_len = i + 1
            continue
        if had_subst:
            seg_cases = adj
        elif n_segs == 1:
            seg_cases = adj | sub
        elif adj:
            seg_cases = adj
        else:
            seg_cases = sub
        if not seg_cases:
            break
        new_cases = seg_cases if cases is None else (cases & seg_cases)
        if not new_cases:
            break
        cases = new_cases
        prefix_len = i + 1
        chose_subst_head = sub and (n_segs == 1 or not adj)
        if chose_subst_head:
            had_subst = True
            break
    if prefix_len == 0:
        if len(surface) == 1:
            return None
        raise IdentifierError(_ident_err(
            surface,
            f"pierwszy segment '{surface[0]}' nie jest ani przymiotnikiem, "
            f"ani rzeczownikiem, ani identyfikatorem funkcji",
        ))
    if cases is None:
        return None
    return cases


def _ident_err(surface, reason):
    return (
        f"Niepoprawny identyfikator '{'_'.join(surface)}': {reason}. "
        f"Oczekiwana forma: [przymiotnik...] [rzeczownik] [reszta], "
        f"gdzie przymiotniki i rzeczownik zgadzają się w przypadku."
    )
