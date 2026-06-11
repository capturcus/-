#!/usr/bin/env python3
import argparse
import sys

import lexer
import morph_anal
import preprocess
import parser
import expression
import pretty
import typechecker
from ast_nodes import InterpreterError


def main():
    argp = argparse.ArgumentParser()
    argp.add_argument("input", nargs="?", type=argparse.FileType("r"), default=sys.stdin)
    argp.add_argument("--sgjp", default="../sgjp.tab")
    argp.add_argument("--redis", action="store_true",
                      help="lematyzuj przez lokalny Redis (zero ładowania; "
                           "wymaga migracji: sgjp_do_redisa.py)")
    argp.add_argument("--redis-url", default="redis://localhost:6379/0")
    args = argp.parse_args()

    text = args.input.read()
    filename = getattr(args.input, "name", "<stdin>")
    try:
        if args.redis:
            db, preps = morph_anal.load_redis(args.redis_url)
        else:
            db, preps = morph_anal.load(args.sgjp)
    except InterpreterError as e:
        _print_error(filename, text, e)
        sys.exit(1)

    try:
        tokens = lexer.lex(text)
        morphs = morph_anal.analyze(tokens, db)
        morphs = preprocess.preprocess(morphs)
        module = parser.parse(morphs, preps)
        expression.resolve_module(module, preps)
    except InterpreterError as e:
        _print_error(filename, text, e)
        sys.exit(1)

    pretty.pretty(module)
    typechecker.resolve_module(module)



def _print_error(filename, source, err):
    """Formatuje błąd jako `filename:line: ErrorClass: message` + opcjonalny
    structural context + snippet linii źródła."""
    lines = source.split("\n")
    cls = type(err).__name__
    msg = err.args[0] if err.args else str(err)
    if err.line is None:
        print(f"{filename}: {cls}: {msg}", file=sys.stderr)
    else:
        print(f"{filename}:{err.line}: {cls}: {msg}", file=sys.stderr)
    if err.extra_context:
        for line in err.extra_context.splitlines():
            print(f"  | {line}", file=sys.stderr)
    if err.line is not None and 1 <= err.line <= len(lines):
        snippet = lines[err.line - 1]
        print(f"  | {err.line:>3} | {snippet}", file=sys.stderr)


if __name__ == "__main__":
    main()
