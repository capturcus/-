"""Parser strukturalny (Pass 1).

Rozpoznaje top-level konstrukcje: definicje funkcji/struktur, struktury sterujące
(if/while/for/break/return), assignment. Wszystko, co nie jest słowem kluczowym
strukturalnym, trafia do `Phrase` jako surowy strumień tokenów.

Treść `Phrase` (matematyka, function calls, getter chains, struct creation,
subscript) jest parsowana w drugim przebiegu przez `expression.resolve_module`.

Gramatyka Pass 1:

  module     := stmt*
  stmt       := func_def | extern_def | struct_def
              | if_stmt | while_stmt | for_stmt
              | "stop" | "dalej" | "zwrócić" [phrase]
              | assignment | expr_stmt
  func_def   := "aby" function_name param* ["->" type] ":" INDENT stmt+ DEDENT
  extern_def := "można" function_name param* ["->" type] NEWLINE
  struct_def := "definicja" type_name ":" INDENT field+ DEDENT
  field      := identifier "(" type ")"
  param      := [prep] identifier ["(" type ")"]
  if_stmt    := "jeśli" phrase ":" INDENT stmt+ DEDENT
                [ "inaczej" ( if_stmt | ":" INDENT stmt+ DEDENT ) ]
  while_stmt := "dopóki" phrase ":" INDENT stmt+ DEDENT
  for_stmt   := "dla" identifier "w" phrase ":" INDENT stmt+ DEDENT
  assignment := phrase "to" phrase
  expr_stmt  := phrase

`identifier` w param/field/for_stmt to WORD przepuszczony przez
`make_identifier` — wymaga formy `[adj]+ [subst] [reszta]` (multi-seg bez
valid noun-prefiksu rzuca `IdentifierError`). Single-seg verb-only nazwy są
tolerowane (variants=()), ale referowanie ich w body nie ma sensu — to ta
sama semantyka co istniejące params/fields.

`dla` jest STRUKTURALNYM keyword'em TYLKO na pierwszej pozycji statementu;
wewnątrz `phrase` (np. argumenty fcall: `weź dla użytkownika`) `dla`
pozostaje zwykłym przyimkiem rozpoznawanym przez `expression.py`.

`extern_def` deklaruje sygnaturę funkcji zewnętrznej (analog `extern` z C);
nagłówek identyczny z `aby`, ale brak `:` i brak ciała — cała deklaracja
mieści się w jednej linii.
"""

import lexer
from morph_anal import canonical
from ast_nodes import (
    Module, FunctionIdentifier, FunctionDef, ExternFunctionDef, Param,
    StructDef, Field, Phrase, Assignment, If, While, For, Break, Continue,
    Return, InterpreterError,
)
from identifier import make_identifier, is_prep, canonical_type


_PHRASE_END_KINDS = frozenset({
    lexer.Token.NEWLINE,
    lexer.Token.COLON,
    lexer.Token.ARROW,
    lexer.Token.INDENT,
    lexer.Token.DEDENT,
    lexer.Token.ASSIGN,
})


def _describe_tok(t):
    """Czytelny opis tokenu do komunikatów błędów (bez analiz/MorphAnalysis)."""
    if t is None:
        return "koniec pliku"
    kind = t[0].name
    if len(t) > 1 and t[1] is not None:
        return f"{kind} {t[1]!r}"
    return kind


class Parser:
    def __init__(self, tokens, preps=None):
        self.tokens = tokens
        self.pos = 0
        self.preps = preps or {}

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
            line = getattr(t, "line", None) if t is not None else self._last_seen_line()
            raise InterpreterError(
                f"oczekiwano {kind.name}, otrzymano {_describe_tok(t)}",
                line=line,
            )
        return t

    def _last_seen_line(self):
        if self.pos > 0 and self.pos - 1 < len(self.tokens):
            return getattr(self.tokens[self.pos - 1], "line", None)
        return None

    def _skip_newlines(self):
        while self.peek() and self.peek()[0] is lexer.Token.NEWLINE:
            self.advance()

    def collect_phrase(self):
        """Zbiera surowe tokeny od bieżącej pozycji do granicy statementu.

        Granica (poza nawiasami): NEWLINE/COLON/ARROW/INDENT/DEDENT/ASSIGN
        lub niezbalansowane RPAREN. ARITH_OP/CMP_OP/`i`/`lub`/`nie` SĄ
        częścią Phrase — drugi przebieg (`expression.resolve_module`) chodzi
        po AST i wywołuje resolwer dla każdej Phrase w kontekście jej scope'u.
        """
        tokens = []
        paren_depth = 0
        first_line = None
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
            if first_line is None:
                first_line = getattr(t, "line", None)
            tokens.append(t)
            self.advance()
        return Phrase(tokens=tokens, line=first_line)

    def parse_module(self):
        body = []
        self._skip_newlines()
        while self.peek() is not None:
            body.append(self.parse_stmt())
            self._skip_newlines()
        return Module(body=body)

    def parse_stmt(self):
        t = self.peek()
        if t[0] is lexer.Token.WORD:
            canon = canonical(t)
            if canon == ("aby",):
                return self.parse_func_def()
            if canon == ("definicja",):
                return self.parse_struct_def()
            # `można` canonicalizuje się do ("możny",) (adj-priority w canonical
            # bije reading pred), więc dopasowujemy surface — i tak nie chcemy
            # żeby parsowanie extern wyzwalały inne formy adj `możny`.
            if t[1] == ("można",):
                return self.parse_extern_def()
            if canon == ("jeśli",):
                return self.parse_if()
            if canon == ("dopóki",):
                return self.parse_while()
            if canon == ("dla",):
                return self.parse_for()
            if canon == ("stop",):
                self.advance()
                return Break()
            if canon == ("dalej",):
                self.advance()
                nxt = self.peek()
                if nxt is None or nxt[0] in (lexer.Token.NEWLINE, lexer.Token.DEDENT):
                    return Continue()
                raise InterpreterError(
                    f"po 'dalej' (continue) oczekiwano końca linii, "
                    f"otrzymano {_describe_tok(nxt)}",
                    line=getattr(nxt, "line", None),
                )
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

    def parse_for(self):
        self.expect(lexer.Token.WORD)  # dla
        var_tok = self.expect(lexer.Token.WORD)
        var = make_identifier(var_tok)
        w_tok = self.expect(lexer.Token.WORD)
        if canonical(w_tok) != ("w",):
            raise InterpreterError(
                f"w pętli 'dla X w Y:' oczekiwano 'w' po zmiennej, "
                f"otrzymano {_describe_tok(w_tok)}",
                line=getattr(w_tok, "line", None),
            )
        collection = self.collect_phrase()
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        body = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            body.append(self.parse_stmt())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        return For(var=var, collection=collection, body=body)

    def parse_func_def(self):
        aby_tok = self.expect(lexer.Token.WORD)  # aby
        name_tok = self.expect(lexer.Token.WORD)
        name = FunctionIdentifier.from_token(name_tok)
        params = []
        while self.peek() and self.peek()[0] not in (lexer.Token.COLON, lexer.Token.ARROW):
            params.append(self.parse_param())
        return_type = None
        if self.peek() and self.peek()[0] is lexer.Token.ARROW:
            self.advance()
            return_type = canonical_type(self.expect(lexer.Token.WORD), required_case="nom")
        self.expect(lexer.Token.COLON)
        self._skip_newlines()
        self.expect(lexer.Token.INDENT)
        body = []
        self._skip_newlines()
        while self.peek()[0] is not lexer.Token.DEDENT:
            body.append(self.parse_stmt())
            self._skip_newlines()
        self.expect(lexer.Token.DEDENT)
        return FunctionDef(
            name=name, params=params, body=body, return_type=return_type,
            line=getattr(aby_tok, "line", None),
        )

    def parse_extern_def(self):
        self.expect(lexer.Token.WORD)  # można
        name_tok = self.expect(lexer.Token.WORD)
        name = FunctionIdentifier.from_token(name_tok)
        params = []
        while self.peek() and self.peek()[0] not in (
            lexer.Token.NEWLINE, lexer.Token.ARROW, lexer.Token.DEDENT,
        ):
            params.append(self.parse_param())
        return_type = None
        if self.peek() and self.peek()[0] is lexer.Token.ARROW:
            self.advance()
            return_type = canonical_type(self.expect(lexer.Token.WORD), required_case="nom")
        nxt = self.peek()
        if nxt is not None and nxt[0] not in (lexer.Token.NEWLINE, lexer.Token.DEDENT):
            raise InterpreterError(
                f"deklaracja 'można' nie przyjmuje ciała ani dwukropka; "
                f"oczekiwano końca linii, otrzymano {_describe_tok(nxt)}",
                line=getattr(nxt, "line", None),
            )
        return ExternFunctionDef(
            name=name, params=params, return_type=return_type,
            line=name.line,
        )

    def parse_struct_def(self):
        definicja_tok = self.expect(lexer.Token.WORD)  # definicja
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
        return StructDef(
            name=canonical_type(name_tok, required_case="gen", label="nazwa struktury"),
            fields=fields,
            line=getattr(definicja_tok, "line", None),
        )

    def parse_field(self):
        name_tok = self.expect(lexer.Token.WORD)
        self.expect(lexer.Token.LPAREN)
        type_ = canonical_type(self.expect(lexer.Token.WORD), required_case="nom")
        self.expect(lexer.Token.RPAREN)
        return Field(
            name=make_identifier(name_tok), type=type_,
            line=getattr(name_tok, "line", None),
        )

    def parse_param(self):
        prep = None
        if is_prep(self.peek(), self.preps):
            prep = canonical(self.advance())
        name_tok = self.expect(lexer.Token.WORD)
        type_ = None
        if self.peek() and self.peek()[0] is lexer.Token.LPAREN:
            self.advance()
            type_ = canonical_type(self.expect(lexer.Token.WORD), required_case="nom")
            self.expect(lexer.Token.RPAREN)
        name = make_identifier(name_tok)
        return Param(prep=prep, name=name, case=name.case, type=type_)


def parse(tokens, preps=None):
    return Parser(tokens, preps).parse_module()
