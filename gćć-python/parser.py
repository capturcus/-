"""Parser strukturalny (Pass 1).

Rozpoznaje top-level konstrukcje: definicje funkcji/struktur, struktury sterujące
(if/while/break/return), assignment. Wszystko, co nie jest słowem kluczowym
strukturalnym, trafia do `Phrase` jako surowy strumień tokenów.

Treść `Phrase` (matematyka, function calls, getter chains, struct creation)
jest parsowana w drugim przebiegu przez `expression.resolve_module`.
"""

import lexer
from morph_anal import canonical
from ast_nodes import (
    Module, FunctionIdentifier, FunctionDef, Param, StructDef, Field,
    Phrase, Assignment, If, While, Break, Return,
)
from identifier import make_identifier, is_prep


_PHRASE_END_KINDS = frozenset({
    lexer.Token.NEWLINE,
    lexer.Token.COLON,
    lexer.Token.ARROW,
    lexer.Token.INDENT,
    lexer.Token.DEDENT,
    lexer.Token.ASSIGN,
})


class Parser:
    def __init__(self, tokens, preps=None):
        self.tokens = tokens
        self.pos = 0
        self.preps = preps or {}
        self.phrases = []  # zbierane na potrzeby drugiego przebiegu

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
            raise SyntaxError(f"Expected {kind}, got {t}")
        return t

    def _skip_newlines(self):
        while self.peek() and self.peek()[0] is lexer.Token.NEWLINE:
            self.advance()

    def collect_phrase(self):
        """Zbiera surowe tokeny od bieżącej pozycji do granicy statementu.

        Granica (poza nawiasami): NEWLINE/COLON/ARROW/INDENT/DEDENT/ASSIGN
        lub niezbalansowane RPAREN. ARITH_OP/CMP_OP/`i`/`lub`/`nie` SĄ
        częścią Phrase — drugi przebieg buduje z nich wyrażenia.
        """
        tokens = []
        paren_depth = 0
        while self.peek() is not None:
            t = self.peek()
            kind = t[0]
            if paren_depth == 0 and kind in _PHRASE_END_KINDS:
                break
            if kind is lexer.Token.LPAREN:
                paren_depth += 1
            elif kind is lexer.Token.RPAREN:
                if paren_depth == 0:
                    break
                paren_depth -= 1
            tokens.append(t)
            self.advance()
        phrase = Phrase(tokens=tokens)
        self.phrases.append(phrase)
        return phrase

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
                return Return(value=self.collect_phrase())
        lhs = self.collect_phrase()
        if self.peek() and self.peek()[0] is lexer.Token.ASSIGN:
            self.advance()
            return Assignment(target=lhs, value=self.collect_phrase())
        return lhs

    def parse_if(self):
        self.expect(lexer.Token.WORD)  # jeśli
        cond = self.collect_phrase()
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
        cond = self.collect_phrase()
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
        return Field(name=make_identifier(name_tok), type=type_)

    def parse_param(self):
        prep = None
        if is_prep(self.peek(), self.preps):
            prep = canonical(self.advance())
        name_tok = self.expect(lexer.Token.WORD)
        type_ = None
        if self.peek() and self.peek()[0] is lexer.Token.LPAREN:
            self.advance()
            type_ = canonical(self.expect(lexer.Token.WORD))
            self.expect(lexer.Token.RPAREN)
        name = make_identifier(name_tok)
        return Param(prep=prep, name=name, case=name.case, type=type_)


def parse(tokens, preps=None):
    return Parser(tokens, preps).parse_module()
