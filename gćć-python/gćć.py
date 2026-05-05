#!/usr/bin/env python3
import argparse
import sys

import lexer, morph_anal, parser, pretty, phrase_resolver


def main():
    argp = argparse.ArgumentParser()
    argp.add_argument("input", nargs="?", type=argparse.FileType("r"), default=sys.stdin)
    argp.add_argument("--sgjp", default="../sgjp.tab")
    args = argp.parse_args()

    text = args.input.read()
    tokens = lexer.lex(text)
    db, preps = morph_anal.load(args.sgjp)
    morphs = morph_anal.analyze(tokens, db)
    ast = parser.parse(morphs, preps)
    ast_with_calls = phrase_resolver.resolve_module(ast)

    pretty.pretty(ast)

if __name__ == "__main__":
    main()
