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
    Typed, ResolveError, Word, LOGICAL_OPS,
    Assignment, If, While, For, Return, Phrase,
)
from identifier import make_identifier, is_prep


_ADJ_LIKE_POS = ("adj", "pact", "ppas")


def _lemma_key(v):
    """Default key_fn dla _find_in_set — używane dla typów (lemma-only)."""
    return v.lemmas


def _full_key(v):
    """key_fn dla _find_in_set wyciągający pełen klucz (lemmas, number, gender).
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


def _adj_cases_from_analyses(analyses):
    if not analyses:
        return frozenset()
    out = frozenset()
    for ana in analyses[0]:
        if ana.pos in _ADJ_LIKE_POS and ana.case:
            out |= ana.case
    return out


class _Ctx:
    """Statyczny kontekst rezolucji.

    - `function_defs`: dict[lemma_tuple → FunctionDef] (funkcje keyed po
      lemma; rodzaj/liczba nie różnicują funkcji).
    - `types`: set[lemma_tuple] (typy capitalized, lemma-only).
    - `fields_by_type`: dict[type_name → set[(lemmas, num, g)]] — pełne
      klucze pól per struktura, służą do dopasowania referencji.
    - `field_lemmas`: set[lemma_tuple] — projekcja `fields_by_type` po
      lemmie, do szybkiego "czy ten token to w ogóle field" w detekcji
      chain. Konkretne dopasowanie (number/gender) robi `_find_in_set`."""
    def __init__(self, function_defs, types, fields_by_type, field_lemmas):
        self.function_defs = function_defs
        self.types = types
        self.fields_by_type = fields_by_type
        self.field_lemmas = field_lemmas


class _Scope:
    """Symbol table dla zmiennych. Chain w górę przez `parent`.

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
        if key in self.variables:
            return True
        # Atom-compat: klucz z None matchuje dowolny scope-key o tej samej lemmie.
        lemmas, number, gender = key
        if number is None and gender is None:
            for k in self.variables:
                if k[0] == lemmas:
                    return True
        else:
            # Symetrycznie: jeśli scope ma wpis atomowy (None, None), też matchuj.
            if (lemmas, None, None) in self.variables:
                return True
        return self.parent.has_var(key) if self.parent else False


# ---------- wolne helpery (używane przez ExpressionParser i pre-collect) ----------


def _ident_is_field(ident, field_lemmas):
    """True jeśli któryś wariant identyfikatora ma lemma w `field_lemmas`.

    Używa lemma-only comparison (nie pełnego klucza scope) — pozwala na
    detekcję "to jest field" niezależnie od liczby/rodzaju surface'u.
    Faktyczne dopasowanie do konkretnego pola (z liczbą i rodzajem) robi
    `_find_in_set` z pełnym key_fn."""
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


def _format_scope_key(key):
    """Czytelny opis klucza scope (lemmas, number, gender) do błędów."""
    lemmas, number, gender = key
    name = "_".join(lemmas)
    parts = [p for p in (number, gender) if p is not None]
    return f"{name} ({', '.join(parts)})" if parts else name


def _prefer_subst(variants):
    """Jeśli istnieje wariant z subst-głową, odrzuć pure-adj variants.

    Pure-adj readings (np. `częsty` dla surface `części`) to typowo
    fałszywi przyjaciele — w Polskim nazwy zmiennych/pól to rzeczowniki,
    nie przymiotniki. Bez tej preferencji `części` jako LHS byłoby
    niejednoznaczne `(częsty, pl, m)` vs `(część, pl, f)`. Pure-adj
    pozostają wybierane TYLKO gdy nie ma żadnego subst-readingu (np.
    `obserwującego` jest tylko ppas, brak subst)."""
    subst_variants = [v for v in variants if v.had_subst]
    return subst_variants if subst_variants else variants


def _prefer_mainstream(variants):
    """Preferuj warianty mainstream (specialized=False) nad qualified.

    SGJP oznacza specjalistyczne/regionalne/przestarzałe znaczenia
    qualifierami (np. `wiersza` "ryb." dla rybackiego określenia ryby).
    Te warianty istnieją w wynikach (nie są filtrowane całkowicie — wciąż
    są w `ident.variants` dla downstream resolution), ale przy walidacji
    jednoznaczności LHS/pola wybieramy mainstream. Fallback do specialized
    tylko gdy nie ma żadnego mainstream-readingu."""
    mainstream = [v for v in variants if not v.specialized]
    return mainstream if mainstream else variants


def _canonical_priority(key):
    """Priorytet dla wyboru kanonicznego klucza spośród same-lemma wariantów.
    Najbardziej naturalna forma to sg m (l.poj. r. męski) — typowa lemma-citation.
    Kolejno: sg m > sg f > sg n > pl m > pl f > pl n."""
    lemmas, number, gender = key
    return (
        number != "sg",
        gender != "m",
        gender != "f",
        gender != "n",
        number or "",
        gender or "",
        lemmas,
    )


def _collapse_same_lemma(keys):
    """Jeśli wszystkie klucze (lemmas, num, gender) mają tę samą lemmę,
    zwróć jeden kanoniczny (preferuje sg m). Inaczej zwróć oryginalne keys.

    Pure-adj surface jak `zebrane` produkuje wiele nom wariantów
    `(zebrany, *, *)` (po splitcie gender-frozensetu) — to ta sama "rzecz"
    w intencji użytkownika (nominalizacja). Subst-only ambiguity
    (np. `kotki`: kotek vs kotka) NIE jest collapsed — różne lematy
    oznaczają różne zmienne."""
    if len(keys) <= 1:
        return keys
    lemmas = {k[0] for k in keys}
    if len(lemmas) == 1:
        return {min(keys, key=_canonical_priority)}
    return keys


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
    nom_variants = [v for v in field_name.variants if "nom" in v.case]
    if not nom_variants:
        raise ResolveError(
            f"pole struct-a '{'_'.join(field_name.surface)}' nie ma formy "
            f"mianownika; pola deklaruj w nom",
            line=field_name.line,
        )
    nom_variants = _prefer_subst(nom_variants)
    nom_variants = _prefer_mainstream(nom_variants)
    min_rest = min(v.rest_length for v in nom_variants)
    candidates = _collapse_same_lemma({
        (v.lemmas, v.number, v.gender)
        for v in nom_variants if v.rest_length == min_rest
    })
    if len(candidates) > 1:
        opts = ", ".join(sorted(_format_scope_key(k) for k in candidates))
        raise ResolveError(
            f"nazwa pola '{'_'.join(field_name.surface)}' jest niejednoznaczna "
            f"w mianowniku — pasuje do wielu opcji: {opts}",
            line=field_name.line,
        )
    return next(iter(candidates))


def _collect_target_var(target_phrase, scope, field_lemmas, preps):
    """Dodaje pierwsze WORD targetu jako zmienną w scope, walidując że LHS
    jest w mianowniku i jednoznaczny w (lemmas, number, gender)."""
    tokens = target_phrase.tokens
    if not tokens or tokens[0][0] is not lexer.Token.WORD:
        return
    head_ident = make_identifier(tokens[0])
    next_token = tokens[1] if len(tokens) > 1 else None
    if _starts_chain(head_ident, next_token, field_lemmas, preps):
        return  # chain LHS — to field write, nie deklaracja zmiennej
    # Atom (single-letter, brak analiz) — bez nom validation, dodaj jak jest.
    if not head_ident.variants:
        scope.add(head_ident)
        return
    nom_variants = [v for v in head_ident.variants if "nom" in v.case]
    if not nom_variants:
        raise ResolveError(
            f"lewa strona przypisania '{'_'.join(head_ident.surface)}' nie "
            f"ma formy mianownika; zmienne deklaruj w mianowniku",
            line=head_ident.line,
        )
    nom_variants = _prefer_subst(nom_variants)
    nom_variants = _prefer_mainstream(nom_variants)
    # Min-rest preferencja: `[adj+][subst]` (rest=0) bije `[subst][rest...]`
    # (rest≥1) — np. `nowa_analiza` parsuje się jako adj `nowy`+subst `analiza`,
    # nie subst `nowa`+passthrough `analiza`.
    min_rest = min(v.rest_length for v in nom_variants)
    nom_variants = [v for v in nom_variants if v.rest_length == min_rest]
    nom_keys = _collapse_same_lemma(
        {(v.lemmas, v.number, v.gender) for v in nom_variants}
    )
    if len(nom_keys) > 1:
        opts = ", ".join(sorted(_format_scope_key(k) for k in nom_keys))
        raise ResolveError(
            f"lewa strona przypisania '{'_'.join(head_ident.surface)}' "
            f"jest niejednoznaczna w mianowniku — pasuje do wielu opcji: "
            f"{opts}. Użyj jednoznacznej formy.",
            line=head_ident.line,
        )
    scope.add_key(next(iter(nom_keys)))


def _collect_bindings_in_stmt(stmt, scope, field_lemmas, preps):
    """Bindings z While/If/For bodies leakują do enclosing scope (For-var
    dodawany oddzielnie w _resolve_stmt do for-scope)."""
    if isinstance(stmt, Assignment):
        _collect_target_var(stmt.target, scope, field_lemmas, preps)
    elif isinstance(stmt, (While, For)):
        for sub in stmt.body:
            _collect_bindings_in_stmt(sub, scope, field_lemmas, preps)
    elif isinstance(stmt, If):
        for sub in stmt.then_body:
            _collect_bindings_in_stmt(sub, scope, field_lemmas, preps)
        for sub in stmt.else_body:
            _collect_bindings_in_stmt(sub, scope, field_lemmas, preps)


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
        return self.parse_subscript()

    def parse_subscript(self):
        left = self.parse_primary()
        had_pod = False
        while self.peek() and self.peek()[0] is lexer.Token.POD:
            had_pod = True
            pod_tok = self.advance()
            if self.peek() is None:
                raise ResolveError(
                    "operator 'pod' wymaga prawego operandu (indeksu)",
                    line=getattr(pod_tok, "line", None),
                )
            left = Subscript(target=left, index=self.parse_primary())
        if had_pod:
            self.last_production = {"kind": "subscript"}
        return left

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
        """Opcjonalny sufiks typu `(Typ)` przyklejający się do atomu.

        Aktywuje się GDY: kolejne tokeny to LPAREN WORD RPAREN i WORD ma
        pierwszy segment z wielką literą. Dla capitalized WORD rzuca
        ResolveError jeśli lemma ∉ ctx.types (nie ma legalnego znaczenia
        capitalized identyfikatora w samotnych parens poza nazwą typu).
        Lowercase WORD zostawia bez konsumpcji — to nie sufiks-typ.
        """
        if self.peek() is None or self.peek()[0] is not lexer.Token.LPAREN:
            return node
        inner = self.peek(1)
        closer = self.peek(2)
        if (inner is None or inner[0] is not lexer.Token.WORD
                or closer is None or closer[0] is not lexer.Token.RPAREN):
            return node
        first_seg = inner[1][0] if inner[1] else ""
        if not first_seg or not first_seg[0].isupper():
            return node
        lparen_line = getattr(self.peek(), "line", None)
        type_tuple = canonical(inner, required_case="nom")
        if type_tuple not in self.ctx.types:
            known = ", ".join(sorted("_".join(t) for t in self.ctx.types)) or "(brak)"
            raise ResolveError(
                f"sufiks typu '({'_'.join(inner[1])})' odnosi się do nieznanego "
                f"typu '{'_'.join(type_tuple)}'; znane typy: {known}",
                line=getattr(inner, "line", None),
            )
        self.advance()  # LPAREN
        self.advance()  # WORD
        self.advance()  # RPAREN
        self.last_production = {"kind": "type_suffix", "type": type_tuple}
        return Typed(expr=node, type=type_tuple, line=lparen_line)

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
            return self._finish_as_ident_ref(head_ident)
        matched_lemma = next(
            (lemma for lemma in name.lemmas_set if lemma in self.ctx.function_defs),
            None,
        )
        if matched_lemma is None:
            return self._finish_as_ident_ref(head_ident)
        return self._parse_function_call(name, matched_lemma)

    def _finish_as_ident_ref(self, head_ident):
        """Fallback dispatcher — head nie jest struct creation, chain ani fcall.
        Zapisz produkcję jako ident_ref z metadanymi (czy w scope, czy field,
        czy typ, czy funkcja-lemma) — używane przez _diagnose_leftover gdy
        zostaną niesparsowane tokeny."""
        narrowed = self._narrow_to_variable(head_ident)
        in_scope = any(
            self.scope.has_var((v.lemmas, v.number, v.gender))
            for v in head_ident.variants
        )
        if not head_ident.variants:
            # Atom — sprawdź lemma-only.
            in_scope = any(
                self.scope.has_var((l, None, None))
                for l in head_ident.lemmas_set
            )
        is_field_lemma = bool(head_ident.lemmas_set & self.ctx.field_lemmas)
        is_known_type = bool(head_ident.lemmas_set & self.ctx.types)
        is_known_function = any(
            l in self.ctx.function_defs for l in head_ident.lemmas_set
        )
        self.last_production = {
            "kind": "ident_ref",
            "surface": head_ident.surface,
            "in_scope": in_scope,
            "is_field_lemma": is_field_lemma,
            "is_known_type": is_known_type,
            "is_known_function": is_known_function,
        }
        return narrowed

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
        return _ident_is_field(ident, self.ctx.field_lemmas)

    def _find_in_set(self, ident, target_set, exclude=frozenset(),
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

    # ---------- getter chain ----------

    def _can_start_chain(self, head_ident):
        return _starts_chain(head_ident, self.peek(), self.ctx.field_lemmas, self.preps)

    def _is_gen_word(self, tok):
        return _is_gen_word(tok, self.preps)

    def _parse_getter_chain(self, head_ident):
        chain = [head_ident, make_identifier(self.advance())]
        while self._is_gen_word(self.peek()) and self._ident_is_field(chain[-1]):
            chain.append(make_identifier(self.advance()))
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
        field_set = self.ctx.fields_by_type[ctx.type_name]
        matched = self._find_in_set(
            field_ident, field_set,
            exclude=frozenset(ctx.assigned),
            required_case=required_case,
            key_fn=_full_key,
        )
        if matched is None:
            return None
        return prep_canon, matched, is_shorthand


# ---------- module-level resolver ----------


def _build_ctx(module):
    function_defs = {}
    types = set()
    fields_by_type = {}
    field_lemmas = set()
    for node in module.body:
        if isinstance(node, StructDef):
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
    return _Ctx(function_defs, types, fields_by_type, field_lemmas)


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
            f"tokenów (oczekiwałem operatora, 'pod' lub końca wyrażenia)"
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
            f"po niej nie spodziewałem się więcej tokenów (oczekiwałem "
            f"operatora, 'pod' lub końca wyrażenia)"
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
        surface = "_".join(lp["surface"])
        if not (lp["in_scope"] or lp["is_field_lemma"]
                or lp["is_known_type"] or lp["is_known_function"]):
            bullets.append(
                f"'{surface}' nie jest zadeklarowaną zmienną, znaną funkcją, "
                f"polem żadnej struktury, ani typem — czy to literówka albo "
                f"brakująca deklaracja?"
            )
        elif lp["is_field_lemma"] and not lp["in_scope"]:
            bullets.append(
                f"'{surface}' jest polem struktury (nie zmienną w scope) — "
                f"użyj go w getter chain: '<obiekt> {surface}_w_gen'"
            )
        else:
            bullets.append(
                f"po referencji do '{surface}' spodziewałem się operatora, "
                f"'pod' lub końca wyrażenia"
            )

    elif kind in ("subscript", "parens", "literal"):
        bullets.append(
            "spodziewałem się operatora, 'pod' lub końca wyrażenia"
        )

    elif kind == "type_suffix":
        type_str = "_".join(lp["type"])
        bullets.append(
            f"po sufiksie typu '({type_str})' spodziewałem się operatora, "
            f"'pod' lub końca wyrażenia"
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
        _collect_bindings_in_stmt(stmt, scope, ctx.field_lemmas, preps)
    for stmt in body:
        _resolve_stmt(stmt, ctx, preps, scope)


def resolve_module(module, preps=None):
    ctx = _build_ctx(module)
    preps = preps or {}
    module_scope = _Scope()
    # Pre-collect: top-level assignment targets
    for node in module.body:
        if isinstance(node, Assignment):
            _collect_target_var(node.target, module_scope, ctx.field_lemmas, preps)
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
