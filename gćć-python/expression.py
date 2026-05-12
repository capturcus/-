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
    StructDef, FunctionDef, ExternFunctionDef,
    IntLit, StrLit, BinOp, UnaryOp, And, Or, Not,
    FunctionCall, GetterChain, Subscript, StructCreation, StructArg, StructCtx,
    ResolveError, Word, LOGICAL_OPS,
    Assignment, If, While, For, Return, Phrase,
)
from identifier import make_identifier, is_prep


_ADJ_LIKE_POS = ("adj", "pact", "ppas")


def _describe_tok(t):
    """Czytelny opis tokenu do komunikatów błędów (bez analiz/MorphAnalysis)."""
    if t is None:
        return "koniec wyrażenia"
    kind = t[0].name
    if len(t) > 1 and t[1] is not None:
        return f"{kind} {t[1]!r}"
    return kind


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


class _Scope:
    """Symbol table dla zmiennych. Chain w górę przez `parent`.

    `variables` to set[tuple[str, ...]] — wszystkich możliwych lemma
    interpretacji każdej zadeklarowanej zmiennej (dodajemy całe lemmas_set
    identyfikatora). To pozwala odwołać się do zmiennej w dowolnej formie
    morfologicznej."""

    def __init__(self, parent=None):
        self.variables = set()
        self.parent = parent

    def add(self, ident):
        self.variables |= ident.lemmas_set

    def has_var(self, segs):
        if segs in self.variables:
            return True
        return self.parent.has_var(segs) if self.parent else False


# ---------- wolne helpery (używane przez ExpressionParser i pre-collect) ----------


def _ident_is_field(ident, field_names):
    """True jeśli któryś wariant identyfikatora pasuje do field_names."""
    return bool(ident.lemmas_set & field_names)


def _is_gen_word(token, preps):
    """True jeśli token to WORD niebędący prep-em z gen w którymś wariancie."""
    if token is None or token[0] is not lexer.Token.WORD:
        return False
    if is_prep(token, preps):
        return False
    ident = make_identifier(token)
    if not ident.variants:
        return False
    return any("gen" in case for _, case, _ in ident.variants)


def _starts_chain(head_ident, next_token, field_names, preps):
    """Ta sama logika co ExpressionParser._can_start_chain, ale bez self."""
    return _ident_is_field(head_ident, field_names) and _is_gen_word(next_token, preps)


def _field_canonical_lemma(field_name):
    """Jedna kanoniczna forma nazwy pola.

    Wymaga `nom` (konwencja: pola deklarujemy w mianowniku).
    Preferuje min rest_length (krótszy passthrough po subst-głowie) —
    `[adj+][subst]` (rest=0) bije `[subst][rest...]` (rest≥1).
    Konwencja masc-sg-nom dla adj jest automatyczna: SGJP lemmy
    przymiotników są masc nom sg, więc `pierwsze`/`pierwsza` w gałęzi
    adj dają lemma `pierwszy`.

    Jeśli po filtrze min-rest zostaje >1 unikalnych `segs` → ResolveError
    z listą opcji. Atom (no variants) zwraca jedyny element `lemmas_set`."""
    if not field_name.variants:
        ls = field_name.lemmas_set
        if len(ls) != 1:
            opts = ", ".join(sorted("_".join(s) for s in ls))
            raise ResolveError(
                f"nazwa pola '{'_'.join(field_name.surface)}' jest "
                f"niejednoznaczna: {opts}",
                line=field_name.line,
            )
        return next(iter(ls))
    nom_variants = [(s, c, r) for s, c, r in field_name.variants if "nom" in c]
    if not nom_variants:
        raise ResolveError(
            f"pole struct-a '{'_'.join(field_name.surface)}' nie ma formy "
            f"mianownika; pola deklaruj w nom",
            line=field_name.line,
        )
    min_rest = min(r for _, _, r in nom_variants)
    candidates = {s for s, _, r in nom_variants if r == min_rest}
    if len(candidates) > 1:
        opts = ", ".join(sorted("_".join(s) for s in candidates))
        raise ResolveError(
            f"nazwa pola '{'_'.join(field_name.surface)}' jest niejednoznaczna "
            f"— pasuje do wielu opcji o tej samej długości reszty: {opts}",
            line=field_name.line,
        )
    return next(iter(candidates))


def _collect_target_var(target_phrase, scope, field_names, preps):
    """Dodaje pierwsze WORD targetu jako zmienną, chyba że to chain (field write)."""
    tokens = target_phrase.tokens
    if not tokens or tokens[0][0] is not lexer.Token.WORD:
        return
    head_ident = make_identifier(tokens[0])
    next_token = tokens[1] if len(tokens) > 1 else None
    if _starts_chain(head_ident, next_token, field_names, preps):
        return  # chain LHS — to field write, nie deklaracja zmiennej
    scope.add(head_ident)


def _collect_bindings_in_stmt(stmt, scope, field_names, preps):
    """Bindings z While/If/For bodies leakują do enclosing scope (For-var
    dodawany oddzielnie w _resolve_stmt do for-scope)."""
    if isinstance(stmt, Assignment):
        _collect_target_var(stmt.target, scope, field_names, preps)
    elif isinstance(stmt, (While, For)):
        for sub in stmt.body:
            _collect_bindings_in_stmt(sub, scope, field_names, preps)
    elif isinstance(stmt, If):
        for sub in stmt.then_body:
            _collect_bindings_in_stmt(sub, scope, field_names, preps)
        for sub in stmt.else_body:
            _collect_bindings_in_stmt(sub, scope, field_names, preps)


class ExpressionParser:
    def __init__(self, tokens, ctx, preps, scope):
        self.tokens = tokens
        self.pos = 0
        self.ctx = ctx
        self.preps = preps
        self.scope = scope
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
        return self.parse_subscript()

    def parse_subscript(self):
        left = self.parse_primary()
        while self.peek() and self.peek()[0] is lexer.Token.POD:
            pod_tok = self.advance()
            if self.peek() is None:
                raise ResolveError(
                    "operator 'pod' wymaga prawego operandu (indeksu)",
                    line=getattr(pod_tok, "line", None),
                )
            left = Subscript(target=left, index=self.parse_primary())
        return left

    def parse_primary(self):
        t = self.peek()
        if t is None:
            raise ResolveError(
                "nieoczekiwany koniec wyrażenia w primary",
                line=self._last_line(),
            )
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
        raise ResolveError(
            f"nieoczekiwany token w primary: {_describe_tok(t)}",
            line=getattr(t, "line", None),
        )

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
        # Jeśli from_head zsucceeded ale żadna lemma nie matchuje — fallback
        # do identifier_ref (może być lokalna zmienna).
        try:
            name = FunctionIdentifier.from_head(head_ident)
        except FunctionIdentifierError:
            return self._narrow_to_variable(head_ident)
        matched_lemma = next(
            (lemma for lemma in name.lemmas_set if lemma in self.ctx.function_defs),
            None,
        )
        if matched_lemma is None:
            return self._narrow_to_variable(head_ident)
        return self._parse_function_call(name, matched_lemma)

    def _narrow_to_variable(self, ident):
        """Zostaw tylko warianty, których lemmy są zadeklarowanymi zmiennymi
        w scope. NIE wybiera 'najlepszego' — disambiguację dla > 1 wariantu
        zostawia późniejszemu kontekstowi (fcall slot, type checker)."""
        if not ident.variants:
            return ident
        matches = tuple(
            (s, c, r) for s, c, r in ident.variants if self.scope.has_var(s)
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
                    f"argument funkcji '{'_'.join(name.surface)}' "
                    f"nie pasuje do żadnego wolnego parametru w trybie pozycyjnym",
                    line=getattr(name, "line", None),
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
        return _ident_is_field(ident, self.ctx.field_names)

    def _find_in_set(self, ident, target_set, exclude=frozenset(),
                     required_case=None):
        """Wyszukuje wariant z `segments in target_set` (i opcjonalnie z
        `required_case in case`), wykluczając te w `exclude`.
        Po filtrach preferuje min `rest_length` (krótszy passthrough po
        subst-głowie) — to eliminuje fałszywe duplikaty `segs` z różnych
        ścieżek backtrackowania.
        Jeśli po min-rest zostaje >1 wariantów → ResolveError (ambiguity).
        Zwraca dopasowane segments lub None gdy brak matchu."""
        matches = []
        for segs, case, rest_len in ident.variants:
            if segs in exclude:
                continue
            if segs not in target_set:
                continue
            if required_case is not None and required_case not in case:
                continue
            matches.append((segs, case, rest_len))
        # Fallback: identyfikator bez wariantów (atom) — użyj lemmas_set.
        if not matches and not ident.variants and required_case is None:
            for segs in ident.lemmas_set:
                if segs in target_set and segs not in exclude:
                    matches.append((segs, None, 0))
        if not matches:
            return None
        # Preferuj wariant z najkrótszą "resztą" — np. dla `pierwszym polu`
        # gałąź adj+subst (rest=0) bije gałąź subst-głowa+rest (rest=1),
        # nawet gdy obie dają to samo `segs`.
        min_rest = min(r for _, _, r in matches)
        matches = [m for m in matches if m[2] == min_rest]
        if len(matches) > 1:
            opts = ", ".join(sorted("_".join(s) for s, _, _ in matches))
            raise ResolveError(
                f"identyfikator '{'_'.join(ident.surface)}' jest niejednoznaczny "
                f"w tym kontekście — pasuje do wielu opcji: {opts}",
                line=getattr(ident, "line", None),
            )
        return matches[0][0]

    # ---------- getter chain ----------

    def _can_start_chain(self, head_ident):
        return _starts_chain(head_ident, self.peek(), self.ctx.field_names, self.preps)

    def _is_gen_word(self, tok):
        return _is_gen_word(tok, self.preps)

    def _parse_getter_chain(self, head_ident):
        chain = [head_ident, make_identifier(self.advance())]
        while self._is_gen_word(self.peek()) and self._ident_is_field(chain[-1]):
            chain.append(make_identifier(self.advance()))
        return GetterChain(chain=chain)

    # ---------- struct creation ----------

    def _starts_struct_creation(self, head_ident):
        """Zwraca dopasowane type_segments jeśli head zaczyna struct creation,
        inaczej None."""
        if ("nowy",) not in head_ident.lemmas_set:
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
                            f"wymaga wartości",
                            line=self._last_line(),
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
                try:
                    lemma = _field_canonical_lemma(f.name)
                except ResolveError as e:
                    if e.extra_context is None and node.line is not None:
                        e.extra_context = (
                            f"w deklaracji struktury '{'_'.join(node.name)}' "
                            f"(linia {node.line})"
                        )
                    raise
                fbt.add(lemma)
                field_names.add(lemma)
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
    overlap = field_names & set(function_defs.keys())
    if overlap:
        names = ", ".join("_".join(n) for n in sorted(overlap))
        raise ResolveError(
            f"konflikt nazw: identyfikator nie może być jednocześnie "
            f"polem i funkcją: {names}"
        )
    return _Ctx(function_defs, types, fields_by_type, field_names)


def resolve_phrase(phrase, ctx, preps, scope):
    if not phrase.tokens:
        phrase.resolved = None
        return
    parser = ExpressionParser(phrase.tokens, ctx, preps, scope)
    phrase.resolved = parser.parse_phrase()
    if parser.peek() is not None:
        leftover = parser.peek()
        raise ResolveError(
            f"po sparsowaniu frazy pozostały niesparsowane tokeny "
            f"(pierwszy: {_describe_tok(leftover)})",
            line=getattr(leftover, "line", None) or phrase.line,
        )


def _resolve(phrase, ctx, preps, scope):
    """Alias dla resolve_phrase z miłą krótką nazwą do tree-walka."""
    resolve_phrase(phrase, ctx, preps, scope)


def _resolve_stmt(stmt, ctx, preps, scope):
    if isinstance(stmt, Assignment):
        _resolve(stmt.target, ctx, preps, scope)
        _resolve(stmt.value, ctx, preps, scope)
    elif isinstance(stmt, For):
        _resolve(stmt.collection, ctx, preps, scope)
        for_scope = _Scope(parent=scope)
        for_scope.add(stmt.var)
        for sub in stmt.body:
            _resolve_stmt(sub, ctx, preps, for_scope)
    elif isinstance(stmt, While):
        _resolve(stmt.cond, ctx, preps, scope)
        for sub in stmt.body:
            _resolve_stmt(sub, ctx, preps, scope)
    elif isinstance(stmt, If):
        _resolve(stmt.cond, ctx, preps, scope)
        for sub in stmt.then_body:
            _resolve_stmt(sub, ctx, preps, scope)
        for sub in stmt.else_body:
            _resolve_stmt(sub, ctx, preps, scope)
    elif isinstance(stmt, Return):
        if stmt.value is not None:
            _resolve(stmt.value, ctx, preps, scope)
    elif isinstance(stmt, Phrase):
        _resolve(stmt, ctx, preps, scope)
    # Break: no phrase


def _resolve_body(body, ctx, preps, scope):
    """Zbiera bindings (assignments w body + zagnieżdżonych If/While/For)
    do obecnego scope'u, potem rezolwuje każdy statement."""
    for stmt in body:
        _collect_bindings_in_stmt(stmt, scope, ctx.field_names, preps)
    for stmt in body:
        _resolve_stmt(stmt, ctx, preps, scope)


def resolve_module(module, preps=None):
    ctx = _build_ctx(module)
    preps = preps or {}
    module_scope = _Scope()
    # Pre-collect: top-level assignment targets
    for node in module.body:
        if isinstance(node, Assignment):
            _collect_target_var(node.target, module_scope, ctx.field_names, preps)
    # Resolve module-level
    for node in module.body:
        if isinstance(node, Assignment):
            _resolve(node.target, ctx, preps, module_scope)
            _resolve(node.value, ctx, preps, module_scope)
        elif isinstance(node, FunctionDef):
            fn_scope = _Scope(parent=module_scope)
            for p in node.params:
                fn_scope.add(p.name)
            _resolve_body(node.body, ctx, preps, fn_scope)
        elif isinstance(node, Phrase):
            _resolve(node, ctx, preps, module_scope)
        # StructDef: brak fraz
    return module
