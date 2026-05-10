"""Pass 2: parser wyrażeń wewnątrz `Phrase.tokens`.

Pełna gramatyka:

  phrase     := or_expr
  or_expr    := and_expr ("lub" and_expr)*
  and_expr   := not_expr ("i"  not_expr)*
  not_expr   := "nie" not_expr | cmp_expr
  cmp_expr   := arith [CMP_OP arith]
  arith      := term (ARITH_OP term)*       # +, -
  term       := factor (TERM_OP factor)*    # *
  factor     := [ARITH_OP] subscript        # unary +/-
  subscript  := primary ("pod" primary)*    # left-assoc, postfix
  primary    := INT_LIT | TEXT | "(" phrase ")"
              | function_call | getter_chain | struct_creation
              | identifier_ref

Argumenty function_call są ograniczone do `primary` (lewostronne wiązanie),
żeby `weź dla X plus 7` parsowało się jako `BinOp(+, FCall(weź, [X]), 7)`.
W szczególności argumenty NIE wchodzą na poziom `subscript` — `f od listy
pod indeksem` daje `Subscript(FCall(f, [listy]), indeksem)`, a żeby wepchnąć
subscript do argumentu trzeba parens: `f od (listy pod indeksem)`.
Wartości pól w struct_creation są pełnymi `phrase` (boundary: kolejny `o/z`
matchujący niezajęte pole z aktywnego StructCtx).
"""

from itertools import product

import lexer
from morph_anal import canonical
from ast_nodes import (
    Identifier, FunctionIdentifier, FunctionIdentifierError,
    StructDef, FunctionDef,
    IntLit, StrLit, BinOp, UnaryOp, And, Or, Not,
    FunctionCall, GetterChain, Subscript, StructCreation, StructArg, StructCtx,
    ResolveError, Word, LOGICAL_OPS,
)
from identifier import make_identifier, is_prep


_ADJ_LIKE_POS = ("adj", "pact", "ppas")


def _adj_cases_from_analyses(analyses):
    if not analyses:
        return frozenset()
    out = frozenset()
    for ana in analyses[0]:
        if ana.pos in _ADJ_LIKE_POS and ana.case:
            out |= ana.case
    return out


class _Ctx:
    def __init__(self, function_defs, types, fields_by_type, field_names):
        self.function_defs = function_defs
        self.types = types
        self.fields_by_type = fields_by_type
        self.field_names = field_names


class ExpressionParser:
    def __init__(self, tokens, ctx, preps):
        self.tokens = tokens
        self.pos = 0
        self.ctx = ctx
        self.preps = preps
        self.struct_stack = []  # lista StructCtx aktywnych struct_creation

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
            raise ResolveError(f"oczekiwano {kind}, otrzymano {t}")
        return t

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
        return self.parse_subscript()

    def parse_subscript(self):
        left = self.parse_primary()
        while self.peek() and self.peek()[0] is lexer.Token.POD:
            self.advance()
            if self.peek() is None:
                raise ResolveError(
                    "operator 'pod' wymaga prawego operandu (indeksu)"
                )
            left = Subscript(target=left, index=self.parse_primary())
        return left

    def parse_primary(self):
        t = self.peek()
        if t is None:
            raise ResolveError("nieoczekiwany koniec wyrażenia w primary")
        kind = t[0]
        if kind is lexer.Token.INT_LIT:
            self.advance()
            return IntLit(t[1])
        if kind is lexer.Token.TEXT:
            self.advance()
            return StrLit(t[1])
        if kind is lexer.Token.LPAREN:
            self.advance()
            inner = self.parse_phrase()
            self.expect(lexer.Token.RPAREN)
            return inner
        if kind is lexer.Token.WORD:
            return self._parse_word_primary()
        raise ResolveError(f"nieoczekiwany token w primary: {t}")

    # ---------- WORD-primary dispatcher ----------

    def _parse_word_primary(self):
        head_tok = self.advance()
        head_ident = make_identifier(head_tok)
        # Struct creation: "nowy" + <typ>
        type_segs = self._starts_struct_creation(head_ident)
        if type_segs is not None:
            return self._parse_struct_creation(head_ident, type_segs)
        # Getter chain: field + następne słowo w gen
        if self._can_start_chain(head_ident):
            return self._parse_getter_chain(head_ident)
        # Function call: head jest czasownikiem zdefiniowanym jako fname.
        # Jeśli from_head zsucceeded ale funkcja nie istnieje — fallback do
        # identifier_ref (może być lokalna zmienna; na tym etapie nie wiemy).
        try:
            name = FunctionIdentifier.from_head(head_ident)
        except FunctionIdentifierError:
            return head_ident
        if name.segments not in self.ctx.function_defs:
            return head_ident
        return self._parse_function_call(name)

    # ---------- function call ----------

    def _parse_function_call(self, name):
        fdef = self.ctx.function_defs[name.segments]
        sig = tuple(fdef.params)
        n_slots = len(sig)
        arg_meta = []
        for _ in range(n_slots):
            if self.peek() is None:
                raise ResolveError(
                    f"funkcja '{'_'.join(name.segments)}' wymaga "
                    f"{n_slots} argumentów, otrzymała {len(arg_meta)}"
                )
            prep, value, case = self._parse_arg()
            arg_meta.append((prep, case, value))
        slot_to_arg = self._match_args_to_slots(arg_meta, sig, name)
        params = []
        for slot_i in range(n_slots):
            arg_i = slot_to_arg[slot_i]
            prep, case, value = arg_meta[arg_i]
            params.append(Word(prep=prep, value=value, case=case))
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
        n_slots = len(sig)
        candidates = [
            {si for si, p in enumerate(sig) if self._slot_matches(prep, case, p)}
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
                raise ResolveError(
                    f"argument funkcji '{'_'.join(name.segments)}' "
                    f"nie pasuje do żadnego wolnego parametru w trybie pozycyjnym"
                )
            assigned[ai] = si
            used.add(si)
        return {assigned[ai]: ai for ai in range(n_slots)}

    @staticmethod
    def _slot_matches(tok_prep, tok_case, param):
        if param.prep != tok_prep:
            return False
        if param.case is None or tok_case is None:
            return True
        return bool(param.case & tok_case)

    # ---------- helpery wariantów ----------

    def _ident_is_field(self, ident):
        """Czy KTÓRYŚ wariant identyfikatora jest field-em w obecnym ctx."""
        for segs, _ in ident.variants:
            if segs in self.ctx.field_names:
                return True
        return ident.segments in self.ctx.field_names

    def _find_in_set(self, ident, target_set, exclude=frozenset(),
                     required_case=None):
        """Wyszukuje wariant z `segments in target_set` (i opcjonalnie z
        `required_case in case`), wykluczając te w `exclude`. Tiebreak:
        największy case-set. Zwraca dopasowane segments lub None.
        """
        matches = []
        for segs, case in ident.variants:
            if segs in exclude:
                continue
            if segs not in target_set:
                continue
            if required_case is not None and required_case not in case:
                continue
            matches.append((segs, case))
        if matches:
            segs, _ = max(matches, key=lambda v: len(v[1]))
            return segs
        # Fallback: identyfikator bez wariantów (atom). Default segments
        # mogą trafić w target_set tylko gdy required_case=None (atom nie
        # ma case'u do dopasowania).
        if not ident.variants and required_case is None:
            if ident.segments in target_set and ident.segments not in exclude:
                return ident.segments
        return None

    # ---------- getter chain ----------

    def _can_start_chain(self, head_ident):
        if not self._ident_is_field(head_ident):
            return False
        nxt = self.peek()
        return self._is_gen_word(nxt)

    def _is_gen_word(self, tok):
        if tok is None or tok[0] is not lexer.Token.WORD:
            return False
        # Przyimki (np. `z`, `do`) mają wśród analiz `prep:gen:…` — same w sobie
        # mają „gen" w case, ale są granicą argumentu fcall, nie kontynuacją
        # chain. Wyklucz je z detekcji.
        if is_prep(tok, self.preps):
            return False
        ident = make_identifier(tok)
        # Wystarczy że KTÓRYŚ wariant ma 'gen'. Identifier.case to union
        # wariantów, więc w atomach bez wariantów case=None → False.
        if ident.variants:
            return any("gen" in case for _, case in ident.variants)
        return False

    def _parse_getter_chain(self, head_ident):
        chain = [head_ident, make_identifier(self.advance())]
        while self._is_gen_word(self.peek()) and self._ident_is_field(chain[-1]):
            chain.append(make_identifier(self.advance()))
        return GetterChain(chain=chain)

    # ---------- struct creation ----------

    def _starts_struct_creation(self, head_ident):
        """Zwraca dopasowane type_segments jeśli head zaczyna struct creation,
        inaczej None."""
        if head_ident.segments != ("nowy",):
            return None
        nxt = self.peek()
        if nxt is None or nxt[0] is not lexer.Token.WORD:
            return None
        nxt_ident = make_identifier(nxt)
        type_segs = self._find_in_set(nxt_ident, self.ctx.types)
        if type_segs is None:
            return None
        if not self._cases_overlap(head_ident, nxt_ident):
            return None
        return type_segs

    @staticmethod
    def _cases_overlap(nowy_ident, type_ident):
        nowy_cases = _adj_cases_from_analyses(nowy_ident.analyses)
        type_cases = type_ident.case
        if not nowy_cases or not type_cases:
            return True
        return bool(nowy_cases & type_cases)

    def _parse_struct_creation(self, _nowy_ident, type_name):
        self.advance()  # consume token typu (już zwalidowany w `_starts_struct_creation`)
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
                self.advance()  # consume field word
                ctx.assigned.add(field_name)
                if is_shorthand:
                    args.append(StructArg(field_name=field_name, value=None))
                else:
                    if self.peek() is None:
                        raise ResolveError(
                            f"pole '{'_'.join(field_name)}' wprowadzone przez 'o' "
                            f"wymaga wartości"
                        )
                    args.append(StructArg(
                        field_name=field_name,
                        value=self.parse_phrase(),
                    ))
        finally:
            self.struct_stack.pop()
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
        field_set = self.ctx.fields_by_type[ctx.type_name]
        matched = self._find_in_set(
            field_ident, field_set,
            exclude=frozenset(ctx.assigned),
            required_case=required_case,
        )
        if matched is None:
            return None
        return prep_canon, matched, is_shorthand


# ---------- module-level resolver ----------


def _build_ctx(module):
    function_defs = {}
    types = set()
    fields_by_type = {}
    field_names = set()
    for node in module.body:
        if isinstance(node, StructDef):
            types.add(node.name)
            fbt = fields_by_type.setdefault(node.name, set())
            for f in node.fields:
                fbt.add(f.name.segments)
                field_names.add(f.name.segments)
        elif isinstance(node, FunctionDef):
            function_defs[node.name.segments] = node
    overlap = field_names & set(function_defs.keys())
    if overlap:
        names = ", ".join("_".join(n) for n in sorted(overlap))
        raise ResolveError(
            f"konflikt nazw: identyfikator nie może być jednocześnie "
            f"polem i funkcją: {names}"
        )
    return _Ctx(function_defs, types, fields_by_type, field_names)


def resolve_phrase(phrase, ctx, preps):
    parser = ExpressionParser(phrase.tokens, ctx, preps)
    if not phrase.tokens:
        phrase.resolved = None
        return
    phrase.resolved = parser.parse_phrase()
    if parser.peek() is not None:
        raise ResolveError(
            f"po sparsowaniu frazy pozostały niesparsowane tokeny "
            f"(pierwszy: {parser.peek()})"
        )


def resolve_module(module, preps=None):
    ctx = _build_ctx(module)
    for phrase in module.phrases:
        resolve_phrase(phrase, ctx, preps or {})
    return module
