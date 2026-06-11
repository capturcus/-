"""Pass 2: parser wyrażeń wewnątrz `Phrase.tokens`.

Pełna gramatyka:

  phrase     := or_expr
  or_expr    := and_expr ("lub" and_expr)*
  and_expr   := not_expr ("i"  not_expr)*
  not_expr   := "nie" not_expr | cmp_expr
  cmp_expr   := arith [CMP_OP arith]
  arith      := term (ARITH_OP term)*       # +, -
  term       := factor (TERM_OP factor)*    # *
  factor     := [ARITH_OP] primary          # unary +/-
  primary    := atom [ "(" TYPE_WORD ")" ]  # opcjonalny sufiks typu
  atom       := INT_LIT | TEXT | "(" phrase ")"
              | function_call | getter_chain | struct_creation
              | identifier_ref

Sufiks typu `(Typ)` wiąże najmocniej z atomem bezpośrednio przed nim:
`f od x (Tekst)` daje `FCall(f, [Typed(x, Tekst)])`, NIE `Typed(FCall(...), Tekst)`.
Otypowanie szerszego pod-wyrażenia wymaga grupowania: `(f od x) (Tekst)`.
Wyzwalany TYLKO gdy WORD w nawiasach jest capitalized (pierwszy segment z
wielką literą); lowercase `(x)` po atomie nie jest sufiksem — zostawiany
do leftover-diagnostic. Capitalized WORD który NIE jest znanym typem rzuca
ResolveError (nie fallback do grupowania).

Argumenty function_call są ograniczone do `primary` (lewostronne wiązanie),
żeby `weź dla X plus 7` parsowało się jako `BinOp(+, FCall(weź, [X]), 7)`.
Wartości pól w struct_creation są pełnymi `phrase` (boundary: kolejny `o/z`
matchujący niezajęte pole z aktywnego StructCtx).
"""

from itertools import product

import lexer
from morph_anal import canonical
from ast_nodes import (
    Identifier, FunctionIdentifier, FunctionIdentifierError,
    StructDef, FunctionDef, ExternFunctionDef, UnionDef, Match,
    IntLit, StrLit, BoolLit, BinOp, UnaryOp, And, Or, Not,
    FunctionCall, GetterChain, StructCreation, StructArg, StructCtx, TryCall,
    Typed, ResolveError, Word, LOGICAL_OPS,
    Assignment, If, While, For, Return, Phrase,
    scope_key_matches,
)
from identifier import (
    make_identifier, is_prep, canonical_type, canonical_identity,
    _format_scope_key,
)
import type_parser
from type_parser import parse_type


def _lemma_key(v):
    """Default key_fn dla find_in_set — używane dla typów (lemma-only)."""
    return v.lemmas


def _full_key(v):
    """key_fn dla find_in_set wyciągający pełen klucz (lemmas, number, gender).
    Używane dla pól struktur."""
    return (v.lemmas, v.number, v.gender)


def _describe_key(k):
    """Czytelny opis klucza w komunikatach błędów — działa zarówno dla
    lemma-tuple (typy) jak i pełnego klucza (pola/scope)."""
    if isinstance(k, tuple) and len(k) == 3 and isinstance(k[0], tuple):
        return _format_scope_key(k)
    return "_".join(k)


def _describe_tok(t):
    """Czytelny opis tokenu do komunikatów błędów (bez analiz/MorphAnalysis).
    WORD jest surface'em '_'.join'owany dla czytelności (`WORD 'autor_postu'`),
    inne kindy pokazują value w `repr`."""
    if t is None:
        return "koniec wyrażenia"
    kind = t[0]
    kind_name = kind.name
    if len(t) > 1 and t[1] is not None:
        if kind is lexer.Token.WORD and isinstance(t[1], tuple):
            return f"WORD '{'_'.join(t[1])}'"
        return f"{kind_name} {t[1]!r}"
    return kind_name


class _Ctx:
    """Statyczny kontekst rezolucji.

    - `function_defs`: dict[lemma_tuple → FunctionDef] (funkcje keyed po
      lemma; rodzaj/liczba nie różnicują funkcji).
    - `types`: set[lemma_tuple] (typy capitalized, lemma-only; struktury,
      unie i builtins).
    - `fields_by_type`: dict[type_name → set[(lemmas, num, g)]] — pełne
      klucze pól per struktura, służą do dopasowania referencji. Klucze
      tego dicta to wyłącznie STRUKTURY (unie/builtins nie mają pól).
    - `field_lemmas`: set[lemma_tuple] — projekcja `fields_by_type` po
      lemmie, do szybkiego "czy ten token to w ogóle field" w detekcji
      chain. Konkretne dopasowanie (number/gender) robi `find_in_set`."""
    def __init__(self, function_defs, types, fields_by_type, field_lemmas):
        self.function_defs = function_defs
        self.types = types
        self.fields_by_type = fields_by_type
        self.field_lemmas = field_lemmas


class _Scope:
    """Symbol table dla zmiennych. Chain w górę przez `parent`.

    Block scoping: scope odpowiada blokowi (moduł → funkcja → ciało
    `jeśli`/`dopóki`/`dla`/gałęzi dopasowania `jest:`). Zmienna trafia do scope'u
    w momencie przypisania i jest widoczna do końca bloku; deklaracje
    z bloku-dziecka NIE są widoczne po bloku. Przypisanie do zmiennej
    widocznej z przodka to reasignacja (bez przesłaniania).

    `variables` to set[(lemmas_tuple, number, gender)] — pełnych kluczy
    zadeklarowanych zmiennych. To rozróżnia np. "kotek" (sg, m) od "kotka"
    (sg, f) i "forma" (sg, f) od "formy" (pl, f). `add` dodaje
    `ident.scope_keys` (dla deklaracji niewalidowanych — np. for-var, param
    — wszystkie warianty; LHS przypisania waliduje nom-uniqueness osobno).

    Atom-compat: atomy (single-letter, brak analiz) mają klucz
    (lemma, None, None). `has_var` dopuszcza match takich kluczy po samej
    lemmie z dowolnym wpisem scope o tej samej lemmie."""

    def __init__(self, parent=None):
        self.variables = set()
        self.parent = parent

    def add(self, ident):
        self.variables |= ident.scope_keys

    def add_key(self, key):
        self.variables.add(key)

    def has_var(self, key):
        if any(scope_key_matches(key, k) for k in self.variables):
            return True
        return self.parent.has_var(key) if self.parent else False


# ---------- wolne helpery (używane przez ExpressionParser i pre-collect) ----------


def _ident_is_field(ident, field_lemmas):
    """True jeśli któryś wariant identyfikatora ma lemma w `field_lemmas`.

    Używa lemma-only comparison (nie pełnego klucza scope) — pozwala na
    detekcję "to jest field" niezależnie od liczby/rodzaju surface'u.
    Faktyczne dopasowanie do konkretnego pola (z liczbą i rodzajem) robi
    `find_in_set` z pełnym key_fn."""
    return bool(ident.lemmas_set & field_lemmas)


def _is_gen_word(token, preps):
    """True jeśli token to WORD niebędący prep-em z gen w którymś wariancie."""
    if token is None or token[0] is not lexer.Token.WORD:
        return False
    if is_prep(token, preps):
        return False
    ident = make_identifier(token)
    if not ident.variants:
        return False
    return any("gen" in v.case for v in ident.variants)


def _starts_chain(head_ident, next_token, field_lemmas, preps):
    """Ta sama logika co ExpressionParser._can_start_chain, ale bez self."""
    return _ident_is_field(head_ident, field_lemmas) and _is_gen_word(next_token, preps)


def _has_cond_reading(ident):
    """Czy którykolwiek segment identyfikatora ma analizę w trybie
    przypuszczającym (`cond`) — znacznik wywołania z obsługą błędu."""
    return any(
        a.pos == "cond" for anas in ident.analyses for a in anas
    )


def find_in_set(ident, target_set, exclude=frozenset(),
                required_case=None, key_fn=_lemma_key):
    """Wyszukuje wariant którego klucz (`key_fn(v)`) jest w `target_set`
    (i opcjonalnie ma `required_case in case`), wykluczając te w `exclude`.

    `key_fn` (default = lemma-only) wyciąga klucz porównawczy z wariantu.
    Dla typów używamy `_lemma_key`, dla pól `_full_key` (lemmas, number,
    gender).

    Po filtrach preferuje min `rest_length` (krótszy passthrough po
    subst-głowie) — eliminuje fałszywe duplikaty z różnych ścieżek
    backtrackowania. Jeśli po min-rest zostaje >1 unikalnych kluczy →
    ResolveError (ambiguity). Zwraca dopasowany klucz lub None."""
    matches = []
    for v in ident.variants:
        k = key_fn(v)
        if k in exclude:
            continue
        if k not in target_set:
            continue
        if required_case is not None and required_case not in v.case:
            continue
        matches.append((k, v.case, v.rest_length))
    # Fallback dla atomu (brak variants): porównuj lemma-tuple bezpośrednio
    # z target_set. Sensowne tylko gdy key_fn jest lemma-only — pełne
    # klucze pól mają number/gender, których atom nie ma.
    if (not matches and not ident.variants and required_case is None
            and key_fn is _lemma_key):
        for segs in ident.lemmas_set:
            if segs in target_set and segs not in exclude:
                matches.append((segs, None, 0))
    if not matches:
        return None
    # Preferuj wariant z najkrótszą "resztą" — np. dla `pierwszym polu`
    # gałąź adj+subst (rest=0) bije gałąź subst-głowa+rest (rest=1).
    min_rest = min(r for _, _, r in matches)
    matches = [m for m in matches if m[2] == min_rest]
    uniq_keys = list({m[0] for m in matches})
    if len(uniq_keys) > 1:
        opts = ", ".join(sorted(_describe_key(k) for k in uniq_keys))
        raise ResolveError(
            f"identyfikator '{'_'.join(ident.surface)}' jest niejednoznaczny "
            f"w tym kontekście — pasuje do wielu opcji: {opts}",
            line=getattr(ident, "line", None),
        )
    return uniq_keys[0]


def _narrow_to_key(ident, key):
    """Zawęża identyfikator do wariantów o pełnym kluczu == `key` (rezultat
    dopasowania `find_in_set`). Atom (brak wariantów) wraca bez zmian."""
    matches = tuple(
        v for v in ident.variants if (v.lemmas, v.number, v.gender) == key
    )
    if not matches:
        return ident
    return Identifier(
        surface=ident.surface, analyses=ident.analyses,
        variants=matches, line=ident.line,
    )


def _field_canonical_lemma(field_name):
    """Kanoniczny klucz pola (lemmas, number, gender).

    Wymaga `nom` (konwencja: pola deklarujemy w mianowniku) oraz
    jednoznaczności pełnego klucza (lemmas, number, gender). Splittowanie
    wariantów per (lemma, number, gender) gwarantuje że `kotki` (pole
    deklarowane z l.mn. nom) byłoby ambiguous: (kotek, pl, m) i (kotka,
    pl, f) — error.

    Preferuje subst-głowę nad pure-adj (typowo nazwy pól to rzeczowniki),
    potem min rest_length (krótszy passthrough po subst-głowie) —
    `[adj+][subst]` (rest=0) bije `[subst][rest...]` (rest≥1).
    Atom (no variants) zwraca (jedyny lemma, None, None)."""
    if not field_name.variants:
        ls = field_name.lemmas_set
        if len(ls) != 1:
            opts = ", ".join(sorted("_".join(s) for s in ls))
            raise ResolveError(
                f"nazwa pola '{'_'.join(field_name.surface)}' jest "
                f"niejednoznaczna: {opts}",
                line=field_name.line,
            )
        return (next(iter(ls)), None, None)
    return canonical_identity(
        field_name, required_case="nom", label="nazwa pola",
        missing_hint="; pola deklaruj w mianowniku",
    )


def _declare_target_var(target_phrase, scope, field_lemmas, preps):
    """Deklaruje LHS przypisania w bieżącym (blokowym) scope — wywoływane
    SEKWENCYJNIE w miejscu przypisania (block scoping; zmienna jest widoczna
    od przypisania do końca bloku). Waliduje, że LHS jest w mianowniku
    i jednoznaczny w (lemmas, number, gender).

    Nie deklaruje chain-LHS (zapis do pola). Jeśli zmienna jest już
    widoczna (w tym z przodka), to reasignacja — bez nowej deklaracji,
    żeby gałąź nie przesłaniała zmiennej z zewnątrz."""
    tokens = target_phrase.tokens
    if not tokens or tokens[0][0] is not lexer.Token.WORD:
        return
    head_ident = make_identifier(tokens[0])
    next_token = tokens[1] if len(tokens) > 1 else None
    if _starts_chain(head_ident, next_token, field_lemmas, preps):
        return  # chain LHS — to field write, nie deklaracja zmiennej
    # Atom (single-letter, brak analiz) — bez nom validation, dodaj jak jest.
    if not head_ident.variants:
        if not any(scope.has_var(k) for k in head_ident.scope_keys):
            scope.add(head_ident)
        return
    # Ten sam pipeline co dla pól i typów: głowa w mianowniku, reszta
    # passthrough, min-rest tie-break (`nowa_analiza` → adj `nowy`+subst
    # `analiza`, nie subst `nowa`+passthrough `analiza`).
    key = canonical_identity(
        head_ident, required_case="nom", label="lewa strona przypisania",
        missing_hint="; zmienne deklaruj w mianowniku",
    )
    if not scope.has_var(key):
        scope.add_key(key)


class ExpressionParser:
    def __init__(self, tokens, ctx, preps, scope):
        self.tokens = tokens
        self.pos = 0
        self.ctx = ctx
        self.preps = preps
        self.scope = scope
        self.struct_stack = []  # lista StructCtx aktywnych struct_creation
        # Ostatnia konsumująca produkcja — używane przez _diagnose_leftover gdy
        # `resolve_phrase` napotka niesparsowane tokeny. Każda produkcja która
        # konsumuje ≥1 token ustawia to przed return. Dict z polem "kind" +
        # produkcyjnym contextem (zob. _diagnose_leftover).
        self.last_production = None

    def peek(self, offset=0):
        i = self.pos + offset
        return self.tokens[i] if i < len(self.tokens) else None

    def advance(self):
        t = self.peek()
        self.pos += 1
        return t

    def expect(self, kind):
        t = self.advance()
        if t is None or t[0] is not kind:
            line = getattr(t, "line", None) if t is not None else self._last_line()
            raise ResolveError(
                f"oczekiwano {kind.name}, otrzymano {_describe_tok(t)}",
                line=line,
            )
        return t

    def _current_line(self):
        """Line bieżącego tokenu (jeśli istnieje), w przeciwnym razie line
        ostatniego widzianego tokenu."""
        if self.pos < len(self.tokens):
            return getattr(self.tokens[self.pos], "line", None)
        return self._last_line()

    def _last_line(self):
        if self.pos > 0 and self.pos - 1 < len(self.tokens):
            return getattr(self.tokens[self.pos - 1], "line", None)
        if self.tokens:
            return getattr(self.tokens[-1], "line", None)
        return None

    # ---------- detekcja słów kluczowych logicznych ----------

    def _is_logical_lemma(self, lemma):
        t = self.peek()
        if t is None or t[0] is not lexer.Token.WORD:
            return False
        return canonical(t) == (lemma,)

    # ---------- gramatyka wyrażeń ----------

    def parse_phrase(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self._is_logical_lemma("lub"):
            self.advance()
            left = Or(left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self._is_logical_lemma("i"):
            self.advance()
            left = And(left, self.parse_not())
        return left

    def parse_not(self):
        if self._is_logical_lemma("nie"):
            self.advance()
            return Not(self.parse_not())
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_arith()
        if self.peek() and self.peek()[0] is lexer.Token.CMP_OP:
            op = self.advance()[1]
            return BinOp(op, left, self.parse_arith())
        return left

    def parse_arith(self):
        left = self.parse_term()
        while self.peek() and self.peek()[0] is lexer.Token.ARITH_OP:
            op = self.advance()[1]
            left = BinOp(op, left, self.parse_term())
        return left

    def parse_term(self):
        left = self.parse_factor()
        while self.peek() and self.peek()[0] is lexer.Token.TERM_OP:
            op = self.advance()[1]
            left = BinOp(op, left, self.parse_factor())
        return left

    def parse_factor(self):
        if self.peek() and self.peek()[0] is lexer.Token.ARITH_OP:
            op = self.advance()[1]
            return UnaryOp(op, self.parse_factor())
        return self.parse_primary()

    def parse_primary(self):
        return self._maybe_typed(self._parse_atom())

    def _parse_atom(self):
        t = self.peek()
        if t is None:
            raise ResolveError(
                "nieoczekiwany koniec wyrażenia w primary",
                line=self._last_line(),
            )
        kind = t[0]
        if kind is lexer.Token.INT_LIT:
            self.advance()
            self.last_production = {"kind": "literal", "type": "int"}
            return IntLit(t[1])
        if kind is lexer.Token.TEXT:
            self.advance()
            self.last_production = {"kind": "literal", "type": "text"}
            return StrLit(t[1])
        if kind is lexer.Token.BOOL_LIT:
            self.advance()
            self.last_production = {"kind": "literal", "type": "bool"}
            return BoolLit(t[1])
        if kind is lexer.Token.LPAREN:
            self.advance()
            inner = self.parse_phrase()
            self.expect(lexer.Token.RPAREN)
            self.last_production = {"kind": "parens"}
            return inner
        if kind is lexer.Token.WORD:
            return self._parse_word_primary()
        raise ResolveError(
            f"nieoczekiwany token w primary: {_describe_tok(t)}",
            line=getattr(t, "line", None),
        )

    def _maybe_typed(self, node):
        """Opcjonalny sufiks typu `(Typ ...)` przyklejający się do atomu.

        Aktywuje się GDY: kolejny token to LPAREN, a po nim WORD z pierwszym
        segmentem wielką literą — tak odróżniamy adnotację typu od zwykłego
        wyrażenia w nawiasach (zmienne są małą literą). Typ może być
        parametryzowany (`(Mapa z klucza na wartość)`) i zagnieżdżony —
        parsuje go współdzielony `parse_type` aż do RPAREN. Walidujemy
        tylko GŁOWĘ wobec ctx.types (wiązanie argumentów odroczone do
        typecheckera). Lowercase WORD zostawiamy — to nie sufiks-typ.
        """
        if self.peek() is None or self.peek()[0] is not lexer.Token.LPAREN:
            return node
        inner = self.peek(1)
        if inner is None or inner[0] is not lexer.Token.WORD:
            return node
        first_seg = inner[1][0] if inner[1] else ""
        if not first_seg or not first_seg[0].isupper():
            return node
        lparen_line = getattr(self.peek(), "line", None)
        self.advance()  # LPAREN
        type = parse_type(self, self.preps, terminator=lexer.Token.RPAREN)
        self.expect(lexer.Token.RPAREN)
        if type.head not in self.ctx.types:
            known = ", ".join(sorted("_".join(t) for t in self.ctx.types)) or "(brak)"
            raise ResolveError(
                f"sufiks typu '({'_'.join(inner[1])})' odnosi się do nieznanego "
                f"typu '{'_'.join(type.head)}'; znane typy: {known}",
                line=getattr(inner, "line", None),
            )
        self.last_production = {"kind": "type_suffix", "type": type.head}
        return Typed(expr=node, line=lparen_line, type=type)

    # ---------- WORD-primary dispatcher ----------

    def _parse_word_primary(self):
        head_tok = self.advance()
        head_ident = make_identifier(head_tok)
        # Struct creation: head sam jest znanym typem (capitalized lemma)
        type_segs = self._starts_struct_creation(head_ident)
        if type_segs is not None:
            return self._parse_struct_creation(type_segs)
        # Getter chain: field + następne słowo w gen
        if self._can_start_chain(head_ident):
            return self._parse_getter_chain(head_ident)
        # Function call: head jest czasownikiem zdefiniowanym jako fname.
        # Jeśli from_head zsucceeded ale żadna lemma nie matchuje — fallback
        # do identifier_ref (może być lokalna zmienna).
        try:
            name = FunctionIdentifier.from_head(head_ident)
        except FunctionIdentifierError:
            return self._finish_as_ident_ref(head_ident)
        matched_lemma = next(
            (lemma for lemma in name.lemmas_set if lemma in self.ctx.function_defs),
            None,
        )
        if matched_lemma is None:
            return self._finish_as_ident_ref(head_ident)
        call = self._parse_function_call(name, matched_lemma)
        if _has_cond_reading(head_ident):
            # Tryb przypuszczający otwiera wywołanie z obsługą błędu,
            # a '?' je domyka — oba znaczniki są obowiązkowe.
            nxt = self.peek()
            if nxt is None or nxt[0] is not lexer.Token.QUESTION:
                raise ResolveError(
                    f"wywołanie w trybie przypuszczającym "
                    f"'{'_'.join(head_ident.surface)}' wymaga '?' po "
                    f"argumentach (wywołanie z obsługą błędu)",
                    line=head_ident.line,
                )
            self.advance()  # '?' domyka wywołanie
            return TryCall(call=call, line=head_ident.line)
        return call

    def _ident_in_scope(self, ident):
        """Czy któryś wariant identyfikatora wskazuje zadeklarowaną zmienną
        (atomy porównywane lemma-only)."""
        if not ident.variants:
            return any(
                self.scope.has_var((l, None, None)) for l in ident.lemmas_set
            )
        return any(
            self.scope.has_var((v.lemmas, v.number, v.gender))
            for v in ident.variants
        )

    def _finish_as_ident_ref(self, head_ident):
        """Fallback dispatcher — head nie jest struct creation, chain ani fcall.
        Block scoping: referencja MUSI wskazywać zadeklarowaną zmienną
        (przypisanie wcześniej w tym lub nadrzędnym bloku, parametr, zmienna
        `dla`, pole związane w gałęzi dopasowania `jest:`) — inaczej ResolveError."""
        if not self._ident_in_scope(head_ident):
            raise ResolveError(
                self._describe_undeclared(head_ident),
                line=head_ident.line,
            )
        self.last_production = {
            "kind": "ident_ref",
            "surface": head_ident.surface,
        }
        return self._narrow_to_variable(head_ident)

    def _describe_undeclared(self, head_ident):
        """Komunikat o referencji do niezadeklarowanej zmiennej, z hintami
        opartymi o ctx (pole? typ? zmienna widoczna tylko w innym bloku?)."""
        surface = "_".join(head_ident.surface)
        msg = f"'{surface}' nie jest zadeklarowaną zmienną w tym miejscu"
        if head_ident.lemmas_set & self.ctx.field_lemmas:
            msg += (
                f"; '{surface}' jest polem struktury — odczyt pola to "
                f"'{surface} <obiektu-w-dopełniaczu>'"
            )
        elif head_ident.lemmas_set & self.ctx.types:
            msg += f"; '{surface}' jest typem, nie wartością"
        else:
            msg += (
                "; zmienna jest widoczna od swojego przypisania do końca "
                "bloku — przypisanie w gałęzi 'jeśli'/dopasowania 'jest:' lub w ciele "
                "pętli nie jest widoczne po bloku (zadeklaruj ją przed blokiem)"
            )
        return msg

    def _narrow_to_variable(self, ident):
        """Zostaw tylko warianty, których pełny klucz (lemmas, number, gender)
        jest zadeklarowaną zmienną w scope. NIE wybiera 'najlepszego' —
        disambiguację dla > 1 wariantu zostawia późniejszemu kontekstowi
        (fcall slot, type checker)."""
        if not ident.variants:
            return ident
        matches = tuple(
            v for v in ident.variants
            if self.scope.has_var((v.lemmas, v.number, v.gender))
        )
        if not matches or matches == ident.variants:
            return ident
        return Identifier(
            surface=ident.surface,
            analyses=ident.analyses,
            variants=matches,
        )

    # ---------- function call ----------

    def _parse_function_call(self, name, matched_lemma):
        fdef = self.ctx.function_defs[matched_lemma]
        sig = tuple(fdef.params)
        n_slots = len(sig)
        arg_meta = []
        for _ in range(n_slots):
            if self.peek() is None:
                raise ResolveError(
                    f"funkcja '{'_'.join(name.surface)}' wymaga "
                    f"{n_slots} argumentów, otrzymała {len(arg_meta)}",
                    line=name.line if hasattr(name, "line") else self._last_line(),
                )
            prep, value, case = self._parse_arg()
            arg_meta.append((prep, case, value))
        slot_to_arg = self._match_args_to_slots(arg_meta, sig, name)
        params = []
        for slot_i in range(n_slots):
            arg_i = slot_to_arg[slot_i]
            prep, case, value = arg_meta[arg_i]
            params.append(Word(prep=prep, value=value, case=case))
        # Ustaw last_production NA KOŃCU (przed return), bo _parse_arg →
        # parse_primary nadpisuje state. Outer-most produkcja musi zostać
        # zachowana dla diagnostyki leftover.
        self.last_production = {
            "kind": "fcall",
            "name_surface": name.surface,
            "n_slots": n_slots,
            "fname_lemma": matched_lemma,
        }
        return FunctionCall(name=name, params=params)

    def _parse_arg(self):
        """Pojedynczy argument fcall: opcjonalny prep + primary value.

        Wartością jest TYLKO primary, nie pełne wyrażenie — żeby operatory
        (`plus`, `mniejsze od`, …) wiązały się na zewnątrz fcall.
        """
        prep = None
        p = self.peek()
        if p is not None and p[0] is lexer.Token.WORD and is_prep(p, self.preps):
            prep = canonical(self.advance())
        value = self.parse_primary()
        case = self._infer_case(value)
        return prep, value, case

    @staticmethod
    def _infer_case(value):
        if isinstance(value, Identifier):
            return value.case
        return None

    def _match_args_to_slots(self, arg_meta, sig, name):
        return type_parser.match_args_to_slots(
            arg_meta, sig,
            on_error=lambda: ResolveError(
                f"argument funkcji '{'_'.join(name.surface)}' "
                f"nie pasuje do żadnego wolnego parametru w trybie pozycyjnym",
                line=getattr(name, "line", None),
            ),
        )

    @staticmethod
    def _slot_matches(tok_prep, tok_case, param):
        return type_parser.slot_matches(tok_prep, tok_case, param)

    # ---------- helpery wariantów ----------

    def _ident_is_field(self, ident):
        return _ident_is_field(ident, self.ctx.field_lemmas)

    # ---------- getter chain ----------

    def _can_start_chain(self, head_ident):
        return _starts_chain(head_ident, self.peek(), self.ctx.field_lemmas, self.preps)

    def _is_gen_word(self, tok):
        return _is_gen_word(tok, self.preps)

    def _parse_getter_chain(self, head_ident):
        chain = [head_ident, make_identifier(self.advance())]
        while self._is_gen_word(self.peek()) and self._ident_is_field(chain[-1]):
            chain.append(make_identifier(self.advance()))
        # Block scoping: podstawa łańcucha (ostatnie ogniwo) to odczyt
        # zmiennej — musi być zadeklarowana.
        base = chain[-1]
        if not self._ident_in_scope(base):
            chain_str = _format_chain_surfaces([c.surface for c in chain])
            raise ResolveError(
                f"podstawa łańcucha '{chain_str}' — "
                f"'{'_'.join(base.surface)}' — nie jest zadeklarowaną "
                f"zmienną w tym miejscu",
                line=base.line,
            )
        # Diagnostyka leftover: rejestruj czy ostatnie ogniwo było polem
        # (czyli czy chain MOŻE iść dalej) — to rozróżnia "user pomyłka"
        # (last=value, leftover=gen-word) od "naturalny koniec chain'a".
        self.last_production = {
            "kind": "chain",
            "chain_surfaces": [c.surface for c in chain],
            "last_is_field": self._ident_is_field(chain[-1]),
        }
        return GetterChain(chain=chain)

    # ---------- struct creation ----------

    def _starts_struct_creation(self, head_ident):
        """Zwraca dopasowane type_segments jeśli head sam jest znanym typem —
        konstrukcja struktury to nazwa typu [+ argumenty pól]. Typy mają
        capitalized lemmy, a zmienne/pola/funkcje małą literę, więc wielka
        litera jednoznacznie odróżnia konstruktor od referencji i wywołania."""
        return find_in_set(head_ident, self.ctx.types)

    def _parse_struct_creation(self, type_name):
        ctx = StructCtx(type_name=type_name)
        self.struct_stack.append(ctx)
        args = []
        try:
            while True:
                kind = self._next_struct_arg_kind(ctx)
                if kind is None:
                    break
                prep_canon, field_name, is_shorthand = kind
                self.advance()  # consume "o" / "z"
                field_tok = self.advance()  # consume field word
                ctx.assigned.add(field_name)
                if is_shorthand:
                    # Skrót `z polem` czyta zmienną o nazwie pola — block
                    # scoping wymaga, żeby była zadeklarowana.
                    if not self.scope.has_var(field_name):
                        raise ResolveError(
                            f"skrót 'z {'_'.join(field_tok[1])}' wymaga "
                            f"zadeklarowanej zmiennej "
                            f"'{_format_scope_key(field_name)}' — przypisz ją "
                            f"przed użyciem albo podaj wartość jawnie: "
                            f"'o polu wartość'",
                            line=getattr(field_tok, "line", None),
                        )
                    args.append(StructArg(field_name=field_name, value=None))
                else:
                    if self.peek() is None:
                        raise ResolveError(
                            f"pole '{'_'.join(field_name)}' wprowadzone przez 'o' "
                            f"wymaga wartości",
                            line=self._last_line(),
                        )
                    args.append(StructArg(
                        field_name=field_name,
                        value=self.parse_phrase(),
                    ))
        finally:
            self.struct_stack.pop()
        self.last_production = {
            "kind": "struct",
            "type_name": type_name,
            "assigned_keys": tuple(ctx.assigned),
            "available_keys": tuple(self.ctx.fields_by_type.get(type_name, set())),
        }
        return StructCreation(type_name=type_name, args=args)

    def _next_struct_arg_kind(self, ctx):
        """Zwraca (prep_canon, field_name, is_shorthand) jeśli kolejny token to
        struct arg; inaczej None.

        Iteruje po wariantach identyfikatora pola — szuka wariantu z
        `required_case in case` i `segments in fields_by_type[type_name]`.
        Tiebreak: największy case-set (najmniej zawężona interpretacja)."""
        p1 = self.peek()
        p2 = self.peek(1)
        if p1 is None or p1[0] is not lexer.Token.WORD:
            return None
        if p2 is None or p2[0] is not lexer.Token.WORD:
            return None
        prep_canon = canonical(p1)
        if prep_canon == ("o",):
            required_case = "loc"
            is_shorthand = False
        elif prep_canon == ("z",):
            required_case = "inst"
            is_shorthand = True
        else:
            return None
        field_ident = make_identifier(p2)
        # .get — typ bez pól (unia/builtin) nie ma wpisu; żadne pole nie
        # zmatchuje i leftover-diagnostyka opisze problem.
        field_set = self.ctx.fields_by_type.get(ctx.type_name, frozenset())
        matched = find_in_set(
            field_ident, field_set,
            exclude=frozenset(ctx.assigned),
            required_case=required_case,
            key_fn=_full_key,
        )
        if matched is None:
            return None
        return prep_canon, matched, is_shorthand


# ---------- module-level resolver ----------

builtin_types = [("Tekst",), ("Liczba",), ("Przełącznik",), ("Znak",), ("Nic",)]

def _build_ctx(module):
    function_defs = {}
    types = set(builtin_types)
    fields_by_type = {}
    field_lemmas = set()
    unions = {}
    for node in module.body:
        if isinstance(node, UnionDef):
            if node.name in unions:
                raise ResolveError(
                    f"typ wariantowy '{'_'.join(node.name)}' zadeklarowany "
                    f"dwukrotnie",
                    line=node.line,
                )
            unions[node.name] = node
            types.add(node.name)
        elif isinstance(node, StructDef):
            types.add(node.name)
            fbt = fields_by_type.setdefault(node.name, set())
            for f in node.fields:
                try:
                    key = _field_canonical_lemma(f.name)
                except ResolveError as e:
                    if e.extra_context is None and node.line is not None:
                        e.extra_context = (
                            f"w deklaracji struktury '{'_'.join(node.name)}' "
                            f"(linia {node.line})"
                        )
                    raise
                if key in fbt:
                    raise ResolveError(
                        f"pole '{_format_scope_key(key)}' zadeklarowane "
                        f"dwukrotnie w strukturze '{'_'.join(node.name)}'",
                        line=node.line,
                    )
                fbt.add(key)
                field_lemmas.add(key[0])
        elif isinstance(node, (FunctionDef, ExternFunctionDef)):
            for lemma in node.name.lemmas_set:
                existing = function_defs.get(lemma)
                if existing is not None and existing is not node:
                    extra = None
                    if existing.line is not None:
                        extra = (
                            f"konflikt z definicją "
                            f"'{'_'.join(existing.name.surface)}' "
                            f"w linii {existing.line}"
                        )
                    raise ResolveError(
                        f"konflikt nazw funkcji: '{'_'.join(lemma)}' "
                        f"pasuje do wielu definicji "
                        f"('{'_'.join(existing.name.surface)}' i "
                        f"'{'_'.join(node.name.surface)}')",
                        line=node.line,
                        extra_context=extra,
                    )
                function_defs[lemma] = node
    overlap = field_lemmas & set(function_defs.keys())
    if overlap:
        names = ", ".join("_".join(n) for n in sorted(overlap))
        raise ResolveError(
            f"konflikt nazw: identyfikator nie może być jednocześnie "
            f"polem i funkcją: {names}"
        )
    _validate_unions(unions, fields_by_type)
    return _Ctx(function_defs, types, fields_by_type, field_lemmas)


def _validate_unions(unions, fields_by_type):
    """Walidacja deklaracji typów wariantowych (po zebraniu całego modułu,
    więc niezależna od kolejności deklaracji): nazwa unii nie koliduje
    z istniejącym typem, a każdy wariant to zdefiniowana struktura albo
    wbudowane `Nic` (nie unia, nie inny builtin, bez duplikatów). `Nic`
    jest jedynym typem zero-argumentowym — zamiast deklarować własne puste
    struktury, unie mogą brać wbudowane `Nic`."""
    for ud in unions.values():
        name = "_".join(ud.name)
        if ud.name in fields_by_type or ud.name in builtin_types:
            raise ResolveError(
                f"nazwa typu wariantowego '{name}' koliduje z istniejącym "
                f"typem",
                line=ud.line,
            )
        seen = set()
        for m in ud.members:
            m_name = "_".join(m)
            if m in seen:
                raise ResolveError(
                    f"wariant '{m_name}' powtórzony w typie wariantowym "
                    f"'{name}'",
                    line=ud.line,
                )
            seen.add(m)
            if m == ("Nic",):
                continue  # wbudowany wariant pusty — zawsze dozwolony
            if m in unions:
                raise ResolveError(
                    f"wariant '{m_name}' typu wariantowego '{name}' sam "
                    f"jest typem wariantowym — zagnieżdżanie unii jest "
                    f"niedozwolone",
                    line=ud.line,
                )
            if m not in fields_by_type:
                raise ResolveError(
                    f"wariant '{m_name}' typu wariantowego '{name}' nie "
                    f"jest zdefiniowaną strukturą — wariantem może być "
                    f"tylko struktura z 'definicja'",
                    line=ud.line,
                )


def _describe_leftover(tokens, max_show=3):
    """Sformatowana lista pierwszych `max_show` tokenów do error-messages.
    Reszta sygnalizowana wielokropkiem `…`."""
    shown = [_describe_tok(t) for t in tokens[:max_show]]
    suffix = " …" if len(tokens) > max_show else ""
    return ", ".join(shown) + suffix


def _format_field_options(ctx, type_name, exclude):
    """Lista dostępnych pól struktury `type_name` (jeszcze nie przypisanych)
    jako czytelny string."""
    fbt = ctx.fields_by_type.get(type_name, set())
    remaining = fbt - set(exclude)
    if not remaining:
        return "(brak — wszystkie pola już przypisane)"
    return ", ".join(sorted(_format_scope_key(k) for k in remaining))


def _format_chain_surfaces(surfaces):
    """`[('autor',), ('post',)]` → `'autor postu'`-style czytelny opis chain'a."""
    return " ".join("_".join(s) for s in surfaces)


def _diagnose_leftover(parser, phrase):
    """Buduje kontekstowy komunikat błędu dla niesparsowanych tokenów.

    Wybiera narrację zależną od `parser.last_production.kind` — ostatniej
    produkcji która konsumowała tokeny. Dorzuca hint'y oparte o aktualny
    ctx (dostępne pola struct'a, czy ident jest w scope, etc.)."""
    leftover_tokens = parser.tokens[parser.pos:]
    leftover_str = _describe_leftover(leftover_tokens)
    line = (
        getattr(leftover_tokens[0], "line", None) or phrase.line
        if leftover_tokens else phrase.line
    )
    lp = parser.last_production or {}
    kind = lp.get("kind")
    bullets = []

    if kind == "chain":
        chain_str = _format_chain_surfaces(lp["chain_surfaces"])
        last_surface = "_".join(lp["chain_surfaces"][-1])
        bullets.append(
            f"po getter chain '{chain_str}' nie spodziewałem się dalszych "
            f"tokenów (oczekiwałem operatora lub końca wyrażenia)"
        )
        first = leftover_tokens[0] if leftover_tokens else None
        if first is not None and _is_gen_word(first, parser.preps):
            if not lp["last_is_field"]:
                bullets.append(
                    f"token {_describe_tok(first)} wygląda jak rozszerzenie "
                    f"chain'a, ale '{last_surface}' nie jest polem żadnej "
                    f"struktury — chain nie może iść dalej"
                )

    elif kind == "fcall":
        name = "_".join(lp["name_surface"])
        bullets.append(
            f"funkcja '{name}' przyjęła {lp['n_slots']} argument(ów); "
            f"po niej nie spodziewałem się więcej tokenów (oczekiwałem operatora lub końca wyrażenia)"
        )
        first = leftover_tokens[0] if leftover_tokens else None
        if first is not None and first[0] is lexer.Token.QUESTION:
            bullets.append(
                "'?' tworzy wywołanie z obsługą błędu tylko przy czasowniku "
                "w trybie przypuszczającym (np. 'wybrałbyś' zamiast 'wybierz')"
            )

    elif kind == "struct":
        type_str = "_".join(lp["type_name"])
        assigned_str = (
            ", ".join(sorted(_format_scope_key(k) for k in lp["assigned_keys"]))
            or "(żadne)"
        )
        available_str = _format_field_options(
            parser.ctx, lp["type_name"], lp["assigned_keys"],
        )
        bullets.append(
            f"tworzenie struktury '{type_str}' z polami: {assigned_str}"
        )
        first = leftover_tokens[0] if leftover_tokens else None
        second = leftover_tokens[1] if len(leftover_tokens) > 1 else None
        if first is not None and first[0] is lexer.Token.WORD:
            prep_canon = canonical(first)
            if prep_canon in (("o",), ("z",)) and second is not None and second[0] is lexer.Token.WORD:
                bullets.append(
                    f"token {_describe_tok(second)} (po {_describe_tok(first)}) "
                    f"nie jest polem struktury '{type_str}' w wymaganym "
                    f"przypadku. Dostępne pola: {available_str}"
                )
            else:
                bullets.append(
                    f"spodziewałem się 'o <pole>' (longhand) lub "
                    f"'z <pole>' (shorthand). Dostępne pola: {available_str}"
                )

    elif kind == "ident_ref":
        # Referencja przeszła check zadeklarowania (inaczej _finish_as_ident_ref
        # rzuciłby wcześniej) — leftover to nadmiarowe tokeny po niej.
        surface = "_".join(lp["surface"])
        bullets.append(
            f"po referencji do '{surface}' spodziewałem się operatora "
            f"lub końca wyrażenia"
        )

    elif kind in ("parens", "literal"):
        bullets.append(
            "spodziewałem się operatora lub końca wyrażenia"
        )

    elif kind == "type_suffix":
        type_str = "_".join(lp["type"])
        bullets.append(
            f"po sufiksie typu '({type_str})' spodziewałem się operatora "
            f"lub końca wyrażenia"
        )

    else:
        bullets.append(
            "nie udało się rozpoznać ostatnio sparsowanej produkcji "
            "(diagnostyka niedostępna)"
        )

    detail = "\n".join(f"  · {b}" for b in bullets)
    raise ResolveError(
        f"niesparsowane tokeny po wyrażeniu: {leftover_str}\n{detail}",
        line=line,
    )


def resolve_phrase(phrase, ctx, preps, scope):
    if not phrase.tokens:
        phrase.resolved = None
        return
    parser = ExpressionParser(phrase.tokens, ctx, preps, scope)
    phrase.resolved = parser.parse_phrase()
    if parser.peek() is not None:
        _diagnose_leftover(parser, phrase)


def _resolve(phrase, ctx, preps, scope):
    """Alias dla resolve_phrase z miłą krótką nazwą do tree-walka."""
    resolve_phrase(phrase, ctx, preps, scope)


def _resolve_stmt(stmt, ctx, preps, scope):
    """Block scoping, sekwencyjnie: zmienna jest widoczna od swojego
    przypisania do końca bloku. RHS rezolwowany PRZED deklaracją LHS
    (`x to x` bez wcześniejszego `x` to błąd), ciała `jeśli`/`dopóki`/
    `dla`/gałęzi dopasowania `jest:` dostają scope-dziecko — deklaracje z gałęzi
    nie są widoczne po bloku. Przypisanie do zmiennej już widocznej
    (także z przodka) to reasignacja, nie nowa deklaracja."""
    if isinstance(stmt, Assignment):
        _resolve(stmt.value, ctx, preps, scope)
        _declare_target_var(stmt.target, scope, ctx.field_lemmas, preps)
        _resolve(stmt.target, ctx, preps, scope)
    elif isinstance(stmt, For):
        _resolve(stmt.collection, ctx, preps, scope)
        for_scope = _Scope(parent=scope)
        for_scope.add(stmt.var)
        for sub in stmt.body:
            _resolve_stmt(sub, ctx, preps, for_scope)
    elif isinstance(stmt, While):
        _resolve(stmt.cond, ctx, preps, scope)
        body_scope = _Scope(parent=scope)
        for sub in stmt.body:
            _resolve_stmt(sub, ctx, preps, body_scope)
    elif isinstance(stmt, If):
        _resolve(stmt.cond, ctx, preps, scope)
        then_scope = _Scope(parent=scope)
        for sub in stmt.then_body:
            _resolve_stmt(sub, ctx, preps, then_scope)
        else_scope = _Scope(parent=scope)
        for sub in stmt.else_body:
            _resolve_stmt(sub, ctx, preps, else_scope)
    elif isinstance(stmt, Match):
        _resolve_match(stmt, ctx, preps, scope)
    elif isinstance(stmt, UnionDef):
        raise ResolveError(
            f"typ wariantowy '{'_'.join(stmt.name)}' można zadeklarować "
            f"tylko na poziomie modułu",
            line=stmt.line,
        )
    elif isinstance(stmt, Return):
        if stmt.value is not None:
            _resolve(stmt.value, ctx, preps, scope)
    elif isinstance(stmt, Phrase):
        _resolve(stmt, ctx, preps, scope)
    # Break: no phrase


def _resolve_match(stmt, ctx, preps, scope):
    """Rezolucja dopasowania `X jest:`: subject w bieżącym scope; każda gałąź
    waliduje swój wariant (zdefiniowana struktura) i pola (narzędnik po `z`,
    pole tej struktury), wiąże je w scope gałęzi i rezolwuje body.
    Identyfikatory pól są zawężane in-place do dopasowanego klucza —
    typechecker czyta z nich jednoznaczny scope-key."""
    _resolve(stmt.subject, ctx, preps, scope)
    for br in stmt.branches:
        type_str = "_".join(br.type_name)
        if br.type_name == ("Nic",):
            field_set = frozenset()  # wbudowane Nic — brak pól do związania
        elif br.type_name not in ctx.fields_by_type:
            raise ResolveError(
                f"wariant '{type_str}' w dopasowaniu 'jest:' nie jest zdefiniowaną "
                f"strukturą",
                line=br.line,
            )
        else:
            field_set = ctx.fields_by_type[br.type_name]
        br_scope = _Scope(parent=scope)
        bound = set()
        for i, fid in enumerate(br.fields):
            key = find_in_set(
                fid, field_set, exclude=frozenset(bound),
                required_case="inst", key_fn=_full_key,
            )
            if key is None:
                options = ", ".join(
                    sorted(_format_scope_key(k) for k in field_set - bound)
                ) or "(brak)"
                raise ResolveError(
                    f"'{'_'.join(fid.surface)}' nie pasuje do żadnego wolnego "
                    f"pola struktury '{type_str}' (wymagany narzędnik po 'z'); "
                    f"dostępne pola: {options}",
                    line=fid.line,
                )
            br.fields[i] = _narrow_to_key(fid, key)
            bound.add(key)
            br_scope.add_key(key)
        for sub in br.body:
            _resolve_stmt(sub, ctx, preps, br_scope)


def resolve_module(module, preps=None):
    ctx = _build_ctx(module)
    preps = preps or {}
    module_scope = _Scope()
    # Sekwencyjnie — top-level przypisania deklarują zmienne w miejscu
    # wystąpienia (block scoping), bez pre-collectu.
    for node in module.body:
        if isinstance(node, (Assignment, Match, Phrase)):
            _resolve_stmt(node, ctx, preps, module_scope)
        elif isinstance(node, FunctionDef):
            fn_scope = _Scope(parent=module_scope)
            for p in node.params:
                fn_scope.add(p.name)
            for stmt in node.body:
                _resolve_stmt(stmt, ctx, preps, fn_scope)
        # StructDef / UnionDef / ExternFunctionDef: brak fraz
    return module
