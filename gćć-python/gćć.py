#!/usr/bin/env python3
import argparse
import sys

import lexer
import morph_anal
import preprocess
import parser
import expression
import pretty


def main():
    argp = argparse.ArgumentParser()
    argp.add_argument("input", nargs="?", type=argparse.FileType("r"), default=sys.stdin)
    argp.add_argument("--sgjp", default="../sgjp.tab")
    args = argp.parse_args()

    text = args.input.read()
    tokens = lexer.lex(text)
    db, preps = morph_anal.load(args.sgjp)
    morphs = morph_anal.analyze(tokens, db)
    morphs = preprocess.preprocess(morphs)
    module = parser.parse(morphs, preps)
    expression.resolve_module(module, preps)

    pretty.pretty(module)


if __name__ == "__main__":
    main()
