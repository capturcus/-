"""Parser wyrażeń typu (potencjalnie parametryzowanych) — współdzielony przez
`parser.py` (`Parser`) i `expression.py` (`ExpressionParser`). Obie klasy mają
identyczny interfejs kursora (`peek(offset=0)`, `advance()`, `expect(kind)`),
więc helpery operują na duck-typed kursorze.

Składnia typu:  HEAD ([prep] arg)*  gdzie arg to pojedyncze słowo albo
zagnieżdżony `( TypeExpr )`. Tylko GŁOWA ma wymóg przypadka (mianownik przy
aplikacji; dopełniacz dla nazwy w `definicja` rozstrzyga osobno `parser.py`).
Argumenty identyfikujemy po lemmie, bezprzypadkowo (`required_case=None`)."""

import lexer
from identifier import is_prep, canonical_type
from morph_anal import canonical
from ast_nodes import TypeRef, TypeArg


def read_prep(cursor, preps):
    """Skonsumuj opcjonalny wiodący przyimek → krotka kanoniczna albo None.
    Współdzielone przez `parse_param` i pętlę argumentów typu (bez duplikacji)."""
    if is_prep(cursor.peek(), preps):
        return canonical(cursor.advance())
    return None


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
        else:
            arg_tok = cursor.expect(lexer.Token.WORD)
            arg = TypeRef(head=canonical_type(arg_tok, required_case=None), args=[],
                          line=getattr(arg_tok, "line", None))
        args.append(TypeArg(prep=prep, type=arg))
    return TypeRef(head=head, args=args, line=getattr(head_tok, "line", None))
