"""Parser wyrażeń typu (potencjalnie parametryzowanych) — współdzielony przez
`parser.py` (`Parser`) i `expression.py` (`ExpressionParser`). Obie klasy mają
identyczny interfejs kursora (`peek(offset=0)`, `advance()`, `expect(kind)`),
więc helpery operują na duck-typed kursorze.

Składnia typu:  HEAD ([prep] arg)*  gdzie arg to pojedyncze słowo albo
zagnieżdżony `( TypeExpr )`. Tylko GŁOWA ma wymóg przypadka (mianownik przy
aplikacji; dopełniacz dla nazwy w `definicja` rozstrzyga osobno `parser.py`).
Argumenty identyfikujemy po lemmie, bezprzypadkowo (`required_case=None`)."""

import lexer
from identifier import is_prep, canonical_type, make_identifier
from morph_anal import canonical
from ast_nodes import TypeRef, TypeArg


def read_prep(cursor, preps):
    """Skonsumuj opcjonalny wiodący przyimek → krotka kanoniczna albo None.
    Współdzielone przez `parse_param` i pętlę argumentów typu (bez duplikacji)."""
    if is_prep(cursor.peek(), preps):
        return canonical(cursor.advance())
    return None


# ---------- dopasowanie argumentów do slotów (prep, case) ----------
# Współdzielony silnik: wywołania funkcji (expression.py) ORAZ argumenty typów
# parametryzowanych (typechecker.py) dopasowują argumenty do parametrów tak samo.

def slot_matches(tok_prep, tok_case, param):
    if param.prep != tok_prep:
        return False
    if param.case is None or tok_case is None:
        return True
    return bool(param.case & tok_case)


def match_args_to_slots(arg_meta, sig, on_error):
    """arg_meta: list[(prep, case, payload)]; sig: list[Param]; on_error: ()->Exception.
    Greedy: najpierw argumenty z dokładnie jednym wolnym slotem, potem pozycyjnie.
    Zwraca {slot_index: arg_index}."""
    n_slots = len(sig)
    candidates = [
        {si for si, p in enumerate(sig) if slot_matches(prep, case, p)}
        for prep, case, _ in arg_meta
    ]
    assigned = {}
    used = set()
    while True:
        progress = False
        for ai in range(n_slots):
            if ai in assigned:
                continue
            cands = candidates[ai] - used
            if len(cands) == 1:
                slot = next(iter(cands))
                assigned[ai] = slot
                used.add(slot)
                progress = True
        if not progress:
            break
    remaining_args = [ai for ai in range(n_slots) if ai not in assigned]
    free_slots = sorted(set(range(n_slots)) - used)
    for ai, si in zip(remaining_args, free_slots):
        if si not in candidates[ai]:
            raise on_error()
        assigned[ai] = si
        used.add(si)
    return {assigned[ai]: ai for ai in range(n_slots)}


def parse_type(cursor, preps, *, terminator, head_case="nom"):
    """Sparsuj  HEAD ([prep] arg)*  aż do (nie konsumując) `terminator`
    (rodzaj tokenu lexer.Token; COLON dla nagłówka/typu zwracanego, RPAREN dla
    pola/parametru/adnotacji). GŁOWA kanonizowana wg `head_case` (mianownik w
    pozycjach aplikacji; None przy rekursji w zagnieżdżony argument, bo głowy
    argumentów są bezprzypadkowe). Każdy ARGUMENT kanonizowany bezprzypadkowo
    (`required_case=None`). Czysta składnia: brak walidacji istnienia typu
    (parser.py nie ma ctx). Zwraca `TypeRef`; nie konsumuje terminatora."""
    head_tok = cursor.expect(lexer.Token.WORD)
    head = canonical_type(head_tok, required_case=head_case)
    args = []
    while cursor.peek() is not None and cursor.peek()[0] is not terminator:
        prep = read_prep(cursor, preps)
        if cursor.peek() is not None and cursor.peek()[0] is lexer.Token.LPAREN:
            cursor.advance()  # zagnieżdżony argument: (
            arg = parse_type(cursor, preps, terminator=lexer.Token.RPAREN,
                                 head_case=None)
            cursor.expect(lexer.Token.RPAREN)
            case = None  # brak pojedynczego słowa rządzącego przypadkiem
        else:
            arg_tok = cursor.expect(lexer.Token.WORD)
            arg = TypeRef(head=canonical_type(arg_tok, required_case=None), args=[],
                          line=getattr(arg_tok, "line", None))
            case = make_identifier(arg_tok).case
        args.append(TypeArg(prep=prep, type=arg, case=case))
    return TypeRef(head=head, args=args, line=getattr(head_tok, "line", None))
