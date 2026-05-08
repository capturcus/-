from dataclasses import dataclass

import lexer
from morph_anal import canonical, VERB_POS, VerbForm


@dataclass
class Module:
    body: list
    phrases: list


@dataclass(frozen=True)
class Identifier:
    segments: tuple
    surface: tuple
    case: frozenset = None


@dataclass(frozen=True)
class HeadIdentifier:
    """Niewalidowana głowa frazy. Zostanie:
    - awansowana na FunctionIdentifier (gdy fraza okaże się FunctionCall),
    - albo zostawiona jako head getter chaina (chain konsumuje .segments)."""
    segments: tuple
    surface: tuple
    analyses: tuple  # tuple[tuple[MorphAnalysis, ...], ...]


class IdentifierError(SyntaxError):
    pass


class FunctionIdentifierError(IdentifierError):
    pass


def _validate_function_name(surface, segments, analyses):
    if not analyses:
        raise FunctionIdentifierError(
            f"identyfikator funkcji '{'_'.join(surface)}' "
            f"nie ma danych morfologicznych"
        )
    for i, anas in enumerate(analyses):
        seg = surface[i]
        if not anas or len(seg) == 1:
            continue
        verb_anas = [a for a in anas if a.pos in VERB_POS]
        if not verb_anas:
            continue
        chosen = next(
            (a for a in verb_anas if a.lemma == segments[i]),
            verb_anas[0],
        )
        return i, chosen.verb_form
    raise FunctionIdentifierError(
        f"nazwa funkcji '{'_'.join(surface)}' nie zawiera czasownika; "
        f"wymagany jest co najmniej jeden segment czasownikowy "
        f"(fin, impt, inf, imps, praet, pcon, winien, będzie, fut, cond)"
    )


@dataclass(frozen=True)
class FunctionIdentifier:
    segments: tuple
    surface: tuple
    verb_index: int
    verb_form: VerbForm

    @classmethod
    def from_head(cls, head):
        verb_index, verb_form = _validate_function_name(
            head.surface, head.segments, head.analyses
        )
        return cls(
            segments=head.segments,
            surface=head.surface,
            verb_index=verb_index,
            verb_form=verb_form,
        )

    @classmethod
    def from_token(cls, tok):
        """Buduje FunctionIdentifier bezpośrednio z tokenu morfologicznego.
        Używane przez parse_func_def — definicja funkcji jest jednoznaczna,
        więc nie potrzeba etapu HeadIdentifier."""
        _, surface, analyses = tok
        segments = canonical(tok)
        analyses_t = tuple(tuple(a) for a in analyses)
        verb_index, verb_form = _validate_function_name(
            surface, segments, analyses_t
        )
        return cls(
            segments=segments,
            surface=surface,
            verb_index=verb_index,
            verb_form=verb_form,
        )


@dataclass
class FunctionDef:
    name: "FunctionIdentifier"
    params: list
    body: list
    return_type: tuple = None


@dataclass
class Param:
    prep: tuple
    name: Identifier
    case: frozenset
    type: tuple = None


@dataclass
class StructDef:
    name: tuple
    fields: list


@dataclass
class Field:
    name: Identifier
    type: tuple


@dataclass
class Phrase:
    words: list


@dataclass
class Word:
    prep: tuple
    value: object
    case: str


@dataclass
class Assignment:
    target: tuple
    value: object


@dataclass
class IntLit:
    value: int


@dataclass
class StrLit:
    value: str


@dataclass
class BinOp:
    op: str
    left: object
    right: object


@dataclass
class UnaryOp:
    op: str
    operand: object


@dataclass
class If:
    cond: object
    then_body: list
    else_body: list


@dataclass
class While:
    cond: object
    body: list


@dataclass
class Break:
    pass


@dataclass
class Return:
    value: object = None


@dataclass
class Not:
    operand: object


@dataclass
class And:
    left: object
    right: object


@dataclass
class Or:
    left: object
    right: object


LOGICAL_OPS = {("nie",), ("i",), ("lub",)}


class Parser:
    def __init__(self, tokens, preps=None):
        self.tokens = tokens
        self.pos = 0
        self.preps = preps or {}
        self.phrases = []

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
            print(self.peek(-2), self.peek(-1), self.peek(-0))
            raise SyntaxError(f"Expected {kind}, got {t}")
        return t

    def _skip_newlines(self):
        while self.peek() and self.peek()[0] is lexer.Token.NEWLINE:
            self.advance()

    def _is_prep(self, token):
        if token is None or token[0] is not lexer.Token.WORD:
            return False
        canon = canonical(token)
        return len(canon) == 1 and canon[0] in self.preps

    def _is_logical_op(self, token):
        return (
            token is not None
            and token[0] is lexer.Token.WORD
            and canonical(token) in LOGICAL_OPS
        )

    def _ident(self, tok):
        segments = canonical(tok)
        surface = tok[1]
        case = self._validate_identifier_case(tok, segments, surface)
        return Identifier(segments=segments, surface=surface, case=case)

    def _ident_head(self, tok):
        _, surface, analyses = tok
        return HeadIdentifier(
            segments=canonical(tok),
            surface=surface,
            analyses=tuple(tuple(a) for a in analyses),
        )

    def _validate_identifier_case(self, tok, segments, surface):
        _, _, analyses = tok
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
                if ana.pos in ("adj", "pact", "ppas"):
                    adj_cases |= ana.case
                elif ana.pos == "subst":
                    subst_cases |= ana.case
            adj_per_seg.append(adj_cases)
            subst_per_seg.append(subst_cases)
        if not has_morph:
            return None
        cases = None  # None = "brak ograniczeń" (jeszcze nic nie weszło do prefiksu)
        had_subst = False
        prefix_len = 0
        for i, (adj, sub) in enumerate(zip(adj_per_seg, subst_per_seg)):
            if adj is None and sub is None:
                # opaque (krótki/bez analiz) — passthrough, nie zmienia cases
                prefix_len = i + 1
                continue
            options = []
            if adj:
                options.append(adj)
            if sub and not had_subst:
                options.append(("subst", sub))
            # próbujemy każdą interpretację, preferując adj (pozwala kontynuować)
            chosen = None
            chosen_is_subst = False
            for opt in options:
                is_subst = isinstance(opt, tuple)
                cand_cases = opt[1] if is_subst else opt
                new_cases = cand_cases if cases is None else (cases & cand_cases)
                if new_cases:
                    chosen = new_cases
                    chosen_is_subst = is_subst
                    break
            if chosen is None:
                break
            cases = chosen
            prefix_len = i + 1
            if chosen_is_subst:
                had_subst = True
                # subst kończy prefix — kolejne segmenty to "reszta"
                break
        if prefix_len == 0:
            raise IdentifierError(self._ident_err(
                surface, f"pierwszy segment '{surface[0]}' nie jest ani przymiotnikiem ani rzeczownikiem"
            ))
        if cases is None:
            # cały prefix był opaque — atom z przypadkiem nieokreślonym
            return None
        return cases

    @staticmethod
    def _ident_err(surface, reason):
        return (
            f"Niepoprawny identyfikator '{'_'.join(surface)}': {reason}. "
            f"Oczekiwana forma: [przymiotnik...] [rzeczownik] [reszta], "
            f"gdzie przymiotniki i rzeczownik zgadzają się w przypadku."
        )

    def parse_module(self):
        body = []
        self._skip_newlines()
        while self.peek() is not None:
            body.append(self.parse_stmt())
            self._skip_newlines()
        return Module(body=body, phrases=self.phrases)

    def parse_stmt(self):
        t = self.peek()
        if t[0] is lexer.Token.WORD:
            canon = canonical(t)
            if canon == ("aby",):
                return self.parse_func_def()
            if canon == ("definicja",):
                return self.parse_struct_def()
            if canon == ("jeśli",):
                return self.parse_if()
            if canon == ("dopóki",):
                return self.parse_while()
            if canon == ("stop",):
                self.advance()
                return Break()
            if canon == ("zwrócić",):
                self.advance()
                nxt = self.peek()
                if nxt is None or nxt[0] in (lexer.Token.NEWLINE, lexer.Token.DEDENT):
                    return Return(value=None)
                return Return(value=self.parse_expr())
        expr = self.parse_expr()
        if self.peek() and self.peek()[0] is lexer.Token.ASSIGN:
            self.advance()
            return Assignment(target=expr, value=self.parse_expr())
        return expr

    def parse_if(self):
        self.expect(lexer.Token.WORD)  # jeśli
        cond = self.parse_expr()
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        then_body = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            then_body.append(self.parse_stmt())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        else_body = []
        t = self.peek()
        if t and t[0] is lexer.Token.WORD and canonical(t) == ("inaczej",):
            self.advance()
            t2 = self.peek()
            if t2 and t2[0] is lexer.Token.WORD and canonical(t2) == ("jeśli",):
                else_body = [self.parse_if()]
            else:
                self.expect(lexer.Token.COLON)
                self._skip_newlines()
                self.expect(lexer.Token.INDENT)
                self._skip_newlines()
                while self.peek()[0] is not lexer.Token.DEDENT:
                    else_body.append(self.parse_stmt())
                    self._skip_newlines()
                self.expect(lexer.Token.DEDENT)
        return If(cond=cond, then_body=then_body, else_body=else_body)

    def parse_while(self):
        self.expect(lexer.Token.WORD)  # dopóki
        cond = self.parse_expr()
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        body = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            body.append(self.parse_stmt())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        return While(cond=cond, body=body)

    def parse_func_def(self):
        self.expect(lexer.Token.WORD)  # aby
        name_tok = self.expect(lexer.Token.WORD)
        name = FunctionIdentifier.from_token(name_tok)
        params = []
        while self.peek() and self.peek()[0] not in (lexer.Token.COLON, lexer.Token.ARROW):
            params.append(self.parse_param())
        return_type = None
        if self.peek() and self.peek()[0] is lexer.Token.ARROW:
            self.advance()
            return_type = canonical(self.expect(lexer.Token.WORD))
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        body = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            body.append(self.parse_stmt())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        return FunctionDef(name=name, params=params, body=body, return_type=return_type)

    def parse_struct_def(self):
        self.expect(lexer.Token.WORD)  # definicja
        name_tok = self.expect(lexer.Token.WORD)
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        fields = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            fields.append(self.parse_field())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        return StructDef(name=canonical(name_tok), fields=fields)

    def parse_field(self):
        name_tok = self.expect(lexer.Token.WORD)
        self.expect(lexer.Token.LPAREN)
        type_ = canonical(self.expect(lexer.Token.WORD))
        self.expect(lexer.Token.RPAREN)
        return Field(name=self._ident(name_tok), type=type_)

    def parse_param(self):
        prep = None
        if self._is_prep(self.peek()):
            prep = canonical(self.advance())
        name_tok = self.expect(lexer.Token.WORD)
        type_ = None
        if self.peek() and self.peek()[0] is lexer.Token.LPAREN:
            self.advance()
            type_ = canonical(self.expect(lexer.Token.WORD))
            self.expect(lexer.Token.RPAREN)
        name = self._ident(name_tok)
        return Param(prep=prep, name=name, case=name.case, type=type_)

    def parse_phrase(self):
        head_tok = self.expect(lexer.Token.WORD)
        head = Word(prep=None, value=self._ident_head(head_tok), case=None)
        words = [head]
        while self._is_word_start(self.peek()):
            words.append(self.parse_simple_word())
        phrase = Phrase(words=words)
        self.phrases.append(phrase)
        return phrase

    def _is_word_start(self, t):
        if t is None:
            return False
        if self._is_logical_op(t):
            return False
        return t[0] in (
            lexer.Token.NUMBER,
            lexer.Token.TEXT,
            lexer.Token.WORD,
            lexer.Token.LPAREN,
        )

    def parse_simple_word(self):
        prep = None
        t = self.peek()
        if self._is_prep(t):
            nxt = self.peek(1)
            if nxt and nxt[0] in (
                lexer.Token.NUMBER,
                lexer.Token.TEXT,
                lexer.Token.WORD,
                lexer.Token.LPAREN,
            ):
                prep = canonical(self.advance())
        value = self.parse_simple_value()
        case = value.case if isinstance(value, Identifier) else None
        return Word(prep=prep, value=value, case=case)

    def parse_simple_value(self):
        t = self.peek()
        if t is None:
            raise SyntaxError("Unexpected end of input in word")
        if t[0] is lexer.Token.NUMBER:
            return IntLit(self.advance()[1])
        if t[0] is lexer.Token.TEXT:
            return StrLit(self.advance()[1])
        if t[0] is lexer.Token.LPAREN:
            self.advance()
            expr = self.parse_expr()
            self.expect(lexer.Token.RPAREN)
            return expr
        if t[0] is lexer.Token.WORD:
            return self._ident(self.advance())
        raise SyntaxError(f"Unexpected token in word value: {t}")

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.peek() and self._is_logical_op(self.peek()) and canonical(self.peek()) == ("lub",):
            self.advance()
            left = Or(left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.peek() and self._is_logical_op(self.peek()) and canonical(self.peek()) == ("i",):
            self.advance()
            left = And(left, self.parse_not())
        return left

    def parse_not(self):
        if self.peek() and self._is_logical_op(self.peek()) and canonical(self.peek()) == ("nie",):
            self.advance()
            return Not(self.parse_not())
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_arith()
        while self.peek() and self.peek()[0] is lexer.Token.BIN_OP and self.peek()[1] in ("<", ">", "<=", ">=", "!=", "="):
            op = self.advance()[1]
            left = BinOp(op, left, self.parse_arith())
        return left

    def parse_arith(self):
        left = self.parse_term()
        while self.peek() and self.peek()[0] is lexer.Token.BIN_OP and self.peek()[1] in ("+", "-"):
            op = self.advance()[1]
            left = BinOp(op, left, self.parse_term())
        return left

    def parse_term(self):
        left = self.parse_factor()
        while self.peek() and self.peek()[0] is lexer.Token.BIN_OP and self.peek()[1] in ("*", "/", "%"):
            op = self.advance()[1]
            left = BinOp(op, left, self.parse_factor())
        return left

    def parse_factor(self):
        t = self.peek()
        if t and t[0] is lexer.Token.BIN_OP and t[1] in ("+", "-"):
            op = self.advance()[1]
            return UnaryOp(op, self.parse_factor())
        return self.parse_primary()

    def parse_primary(self):
        t = self.peek()
        if t is None:
            raise SyntaxError("Unexpected end of input in expr")
        if t[0] is lexer.Token.NUMBER:
            return IntLit(self.advance()[1])
        if t[0] is lexer.Token.TEXT:
            return StrLit(self.advance()[1])
        if t[0] is lexer.Token.LPAREN:
            self.advance()
            expr = self.parse_expr()
            self.expect(lexer.Token.RPAREN)
            return expr
        if t[0] is lexer.Token.WORD:
            return self.parse_phrase()
        raise SyntaxError(f"Unexpected token in expr: {t}")


def parse(tokens, preps=None):
    return Parser(tokens, preps).parse_module()
