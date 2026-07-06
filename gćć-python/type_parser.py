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
from ast_nodes import TypeRef, TypeArg, InterpreterError


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
    """arg_meta: list[(prep, case, payload)]; sig: list[Param];
    on_error: (arg_index=int) -> Exception — dostaje indeks argumentu,
    który nie pasuje (do tabelki slotów w komunikacie).
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
            raise on_error(arg_index=ai)
        assigned[ai] = si
        used.add(si)
    return {assigned[ai]: ai for ai in range(n_slots)}


def parse_alias_target(cursor, preps, *, terminator=None):
    """Cel deklaracji aliasu typu:  HEAD ("o" NAZWA wartość)*  — jedyne
    miejsce jawnej aplikacji parametrów typowych. Wiązanie wyłącznie PO
    NAZWIE parametru; nazwa w miejscowniku po `o`, wartość w apozycji
    mianownikowej (`o elemencie Znak` jak „o imieniu Jan"). Gołe argumenty
    pozycyjne (`Lista Znaków`) są NIElegalne — głośny błąd z podpowiedzią.
    wartość := WORD (mianownik) | "(" cel ")" (zagnieżdżona aplikacja).
    Parametry niezwiązane zostają wolne. Nie konsumuje terminatora."""
    head_tok = cursor.expect(lexer.Token.WORD)
    head = canonical_type(head_tok, required_case="nom")
    args = []
    while cursor.peek() is not None and (
            terminator is None or cursor.peek()[0] is not terminator):
        pair_tok = cursor.peek()
        prep = read_prep(cursor, preps)
        if prep != ("o",):
            raise InterpreterError(
                f"aplikacja parametru typu w aliasie wymaga formy "
                f"'o NAZWIE Typ' (np. 'o elemencie Znak'); "
                f"otrzymano '{_surface(pair_tok)}'",
                line=getattr(pair_tok, "line", None),
            )
        name_tok = cursor.expect(lexer.Token.WORD)
        name = canonical_type(name_tok, required_case="loc",
                              label="nazwa parametru typu")
        if cursor.peek() is not None and cursor.peek()[0] is lexer.Token.LPAREN:
            cursor.advance()
            val = parse_alias_target(cursor, preps,
                                     terminator=lexer.Token.RPAREN)
            cursor.expect(lexer.Token.RPAREN)
        else:
            val_tok = cursor.expect(lexer.Token.WORD)
            val = TypeRef(head=canonical_type(val_tok, required_case="nom"),
                          args=[], line=getattr(val_tok, "line", None))
        args.append(TypeArg(prep=prep, type=val, case=None, name=name))
    return TypeRef(head=head, args=args, line=getattr(head_tok, "line", None))


def _surface(tok):
    if tok is None:
        return "koniec wyrażenia"
    if tok[0] is lexer.Token.WORD and isinstance(tok[1], tuple):
        return "_".join(tok[1])
    return repr(tok[1]) if len(tok) > 1 else tok[0].name


def parse_type(cursor, preps, *, terminator, head_case="nom"):
    """Sparsuj  HEAD ([prep] arg | "o" NAZWA wartość)*  aż do (nie
    konsumując) `terminator` (rodzaj tokenu lexer.Token; COLON dla
    nagłówka/typu zwracanego, RPAREN dla pola/parametru/adnotacji). GŁOWA
    kanonizowana wg `head_case` (mianownik w pozycjach aplikacji; None przy
    rekursji w zagnieżdżony argument, bo głowy argumentów są bezprzypadkowe).
    Każdy ARGUMENT pozycyjny kanonizowany bezprzypadkowo
    (`required_case=None`). APLIKACJA NAZWANA (`o elemencie Tekst`, jak
    w celu aliasu) rozpoznawana po wzorcu: `o` + słowo + wartość
    (słowo lub nawias) — wiąże parametr typu po nazwie także w adnotacjach
    (np. `-> Rezultat o elemencie Tekst`). Czysta składnia: brak walidacji
    istnienia typu (parser.py nie ma ctx). Zwraca `TypeRef`; nie konsumuje
    terminatora."""
    head_tok = cursor.expect(lexer.Token.WORD)
    head = canonical_type(head_tok, required_case=head_case)
    args = []
    while cursor.peek() is not None and cursor.peek()[0] is not terminator:
        prep = read_prep(cursor, preps)
        nxt, nxt2 = cursor.peek(), cursor.peek(1)
        if (prep == ("o",) and nxt is not None
                and nxt[0] is lexer.Token.WORD
                and nxt2 is not None and nxt2[0] is not terminator
                and (nxt2[0] is lexer.Token.LPAREN
                     or (nxt2[0] is lexer.Token.WORD
                         and not is_prep(nxt2, preps)))):
            # Aplikacja nazwana: nazwa parametru w miejscowniku po `o`,
            # wartość w apozycji mianownikowej albo w nawiasie.
            name_tok = cursor.advance()
            name = canonical_type(name_tok, required_case="loc",
                                  label="nazwa parametru typu")
            if cursor.peek()[0] is lexer.Token.LPAREN:
                cursor.advance()
                val = parse_type(cursor, preps, terminator=lexer.Token.RPAREN,
                                 head_case=None)
                cursor.expect(lexer.Token.RPAREN)
            else:
                val_tok = cursor.expect(lexer.Token.WORD)
                val = TypeRef(
                    head=canonical_type(val_tok, required_case="nom"),
                    args=[], line=getattr(val_tok, "line", None))
            args.append(TypeArg(prep=prep, type=val, case=None, name=name))
            continue
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
