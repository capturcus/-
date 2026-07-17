"""Spolszczenie argparse. Każdy komunikat argparse (usage, pomoc, błędy
złych flag) przechodzi przez `argparse._` (gettext) — `spolszcz()`
podmienia ją na słownikową. String spoza słownika (egzotyczny albo
z przyszłej wersji Pythona) przechodzi bez zmian."""
import argparse

PO_POLSKU = {
    "usage: ": "użycie: ",
    "%(prog)s: error: %(message)s\n": "%(prog)s: błąd: %(message)s\n",
    "%(prog)s: warning: %(message)s\n":
        "%(prog)s: ostrzeżenie: %(message)s\n",
    "positional arguments": "argumenty pozycyjne",
    "options": "opcje",
    "subcommands": "podpolecenia",
    "show this help message and exit": "pokaż tę pomoc i zakończ",
    "show program's version number and exit":
        "pokaż wersję programu i zakończ",
    " (default: %(default)s)": " (domyślnie: %(default)s)",
    "unrecognized arguments: %s": "nierozpoznane argumenty: %s",
    "expected one argument": "oczekiwano jednej wartości",
    "expected at most one argument": "oczekiwano co najwyżej jednej wartości",
    "expected at least one argument":
        "oczekiwano co najmniej jednej wartości",
    "expected %s argument": "oczekiwano %s wartości",
    "expected %s arguments": "oczekiwano %s wartości",
    "invalid choice: %(value)r (choose from %(choices)s)":
        "niepoprawny wybór: %(value)r (do wyboru: %(choices)s)",
    "invalid %(type)s value: %(value)r":
        "niepoprawna wartość typu %(type)s: %(value)r",
    "ambiguous option: %(option)s could match %(matches)s":
        "niejednoznaczna opcja: %(option)s może oznaczać %(matches)s",
    "the following arguments are required: %s": "wymagane argumenty: %s",
    "one of the arguments %s is required":
        "wymagany jest jeden z argumentów: %s",
    "not allowed with argument %s": "niedozwolone razem z argumentem %s",
    "ignored explicit argument %r": "zignorowano jawny argument %r",
    "unexpected option string: %s": "nieoczekiwana opcja: %s",
    "can't open '%(filename)s': %(error)s":
        "nie można otworzyć '%(filename)s': %(error)s",
    "option '%(option)s' is deprecated":
        "opcja '%(option)s' jest przestarzała",
    "argument '%(argument_name)s' is deprecated":
        "argument '%(argument_name)s' jest przestarzały",
}


def _tłumacz(msg):
    return PO_POLSKU.get(msg, msg)


def spolszcz():
    argparse._ = _tłumacz
    argparse.ngettext = lambda sg, pl, n: _tłumacz(sg if n == 1 else pl)
