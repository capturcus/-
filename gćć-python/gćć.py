#!/usr/bin/env python3
import argparse
import sys

import includes
import lexer
import morph_anal
import preprocess
import parser
import expression
import pretty
import typechecker
import executor
from ast_nodes import InterpreterError


def main():
    argp = argparse.ArgumentParser()
    argp.add_argument("input", nargs="?", default=None,
                      help="plik .ć (domyślnie stdin)")
    argp.add_argument("--sgjp", default="../sgjp.tab")
    argp.add_argument("--redis", action="store_true",
                      help="lematyzuj przez lokalny Redis (zero ładowania; "
                           "wymaga migracji: sgjp_do_redisa.py)")
    argp.add_argument("--redis-url", default="redis://localhost:6379/0")
    args = argp.parse_args()

    # Pass 0: scalenie plików (dyrektywa `uwzględnij`) — na czystym
    # tekście, zanim ruszy reszta maszynerii. Dalej `text` to jeden
    # program; maszyneria operuje na scalonych numerach linii, a mapa
    # w `scalony` tłumaczy je na oryginalne pliki przy prezentacji błędów.
    filename = args.input if args.input is not None else "<stdin>"
    scalony = None
    try:
        if args.input is not None:
            scalony = includes.resolve(args.input)
        else:
            scalony = includes.resolve_stdin(sys.stdin.read())
    except InterpreterError as e:
        _print_error(filename, "", e)
        sys.exit(1)
    text = scalony.text

    try:
        if args.redis:
            db, preps = morph_anal.load_redis(args.redis_url)
        else:
            db, preps = morph_anal.load(args.sgjp)
    except InterpreterError as e:
        _print_error(filename, text, e, scalony)
        sys.exit(1)

    try:
        tokens = lexer.lex(text)
        morphs = morph_anal.analyze(tokens, db)
        morphs = preprocess.preprocess(morphs)
        module = parser.parse(morphs, preps)
        expression.resolve_module(module, preps)
    except InterpreterError as e:
        _print_error(filename, text, e, scalony)
        sys.exit(1)

    pretty.pretty(module)
    try:
        typechecker.resolve_module(module)
    except typechecker.TypeCheckError as e:
        # TypeCheckError nie niesie `.line` — lokalizacje siedzą w treści
        # ("linia N") i są tłumaczone na oryginalne pliki przez regex.
        msg = str(e)
        if scalony is not None:
            msg = scalony.translate(msg, filename)
        print(f"{filename}: TypeCheckError: {msg}", file=sys.stderr)
        sys.exit(1)

    # po prostu to odpal, to python. jak się otypowało w poprzednim kroku to będzie git.
    # nie potrzeba żadnych informacji dotyczących typów do wykonania programu
    executor.execute(module)



def _print_error(filename, source, err, scalony=None):
    """Formatuje błąd jako `plik:linia: ErrorClass: message` + opcjonalny
    structural context + snippet linii źródła. Z mapą `scalony` numery
    linii (nagłówek, ramka snippetu oraz odwołania „linia N" w treści)
    są tłumaczone na oryginalne pliki źródłowe; snippet bierze treść ze
    scalonego tekstu — linie są verbatim, więc to ta sama treść."""
    lines = source.split("\n")
    cls = type(err).__name__
    msg = err.args[0] if err.args else str(err)
    extra = err.extra_context
    err_file, err_line = filename, err.line
    if scalony is not None:
        org = scalony.origin(err.line)
        if org is not None:
            err_file, err_line = org
        msg = scalony.translate(msg, err_file)
        if extra:
            extra = scalony.translate(extra, err_file)
    if err_line is None:
        print(f"{err_file}: {cls}: {msg}", file=sys.stderr)
    else:
        print(f"{err_file}:{err_line}: {cls}: {msg}", file=sys.stderr)
    if extra:
        for line in extra.splitlines():
            print(f"  | {line}", file=sys.stderr)
    if err.line is not None and 1 <= err.line <= len(lines):
        snippet = lines[err.line - 1]
        print(f"  | {err_line:>3} | {snippet}", file=sys.stderr)


if __name__ == "__main__":
    main()
