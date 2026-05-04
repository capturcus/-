#!/usr/bin/env python3
import argparse
import sys

import lexer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?", type=argparse.FileType("r"), default=sys.stdin)
    args = parser.parse_args()

    text = args.input.read()
    tokens = lexer.lex(text)
    print(tokens)


if __name__ == "__main__":
    main()
