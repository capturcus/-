"""Pass 0: scalanie plików — dyrektywa `uwzględnij <ścieżka>`.

Działa na czystym tekście, ZANIM ruszy jakakolwiek inna maszyneria
interpretera (lexer, morfologia, parser): dyrektywa jest zastępowana
zawartością wskazanego pliku (rekurencyjnie), a wynik to jeden scalony
program. Deklaracje w Ć są niezależne od kolejności, więc konkatenacja
wystarcza.

Jedyna logika ponad konkatenację to DEDUPLIKACJA: każdy plik wchodzi do
scalonego programu najwyżej raz (klucz: znormalizowana ścieżka realpath —
NFC, bo macOS zapisuje nazwy plików w NFD). Diament (a→c, b→c) nie
powiela deklaracji `c`, a cykl (a→b→a) kończy się naturalnie, bo plik
w trakcie scalania jest już odnotowany jako widziany.

Składnia dyrektywy: wiersz zaczynający się (od kolumny zerowej) słowem
`uwzględnij`, po którym następuje ścieżka. To dyrektywa tekstowa, nie
identyfikator — rozpoznawana literalnie, bez odmiany.

ROZSTRZYGANIE ŚCIEŻKI dwuetapowe: najpierw RELATYWNIE względem pliku,
w którym stoi dyrektywa; gdy tam pliku nie ma — w folderze `biblioteki`
(rozstrzyganym względem lokalizacji interpretera, nie katalogu roboczego).
Dzięki temu `uwzględnij przygrywka.ć` znajduje bibliotekę standardową
z dowolnego katalogu, a lokalny plik o tej samej nazwie ma pierwszeństwo.

NUMERY LINII: każda linia scalonego tekstu pochodzi verbatim z dokładnie
jednego pliku źródłowego, więc scalanie buduje mapę pochodzenia
(linia scalona → (plik, linia oryginalna)). Reszta interpretera dalej
operuje na scalonym tekście i scalonych numerach; tłumaczenie na
oryginalne pliki/linie odbywa się wyłącznie przy PREZENTACJI błędów
(`Scalony.origin` dla głównego numeru, `Scalony.translate` dla odwołań
„linia N" wbudowanych w treść komunikatów).
"""

import os
import re
import unicodedata
from dataclasses import dataclass

from ast_nodes import InterpreterError

DIRECTIVE = "uwzględnij"

# Folder z bibliotekami standardowymi (przygrywka.ć, operacje_tekstowe.ć…).
# Rozstrzygany względem lokalizacji interpretera — katalog tego modułu leży
# w `gćć-python/`, a `biblioteki/` jest jego sąsiadem w korzeniu repo.
BIBLIOTEKI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          os.pardir, "biblioteki")

# Odwołania do linii wbudowane w treść komunikatów ("(linia 42)",
# "w linii 42") — tłumaczone przez Scalony.translate.
_LINE_REF = re.compile(r"\b(lini[ai])\s+(\d+)\b")


@dataclass
class Scalony:
    """Wynik passu 0: scalony tekst + mapa pochodzenia linii.

    `origins[i]` to (plik, linia oryginalna) dla 1-based linii scalonej
    i+1. Treść linii jest identyczna z oryginałem, więc snippety błędów
    mogą dalej pochodzić ze scalonego tekstu."""
    text: str
    origins: list

    def origin(self, line):
        """(plik, linia oryginalna) dla 1-based linii scalonej; None poza
        zakresem (np. line=None albo błąd syntetyczny bez linii)."""
        if line is None or not (1 <= line <= len(self.origins)):
            return None
        return self.origins[line - 1]

    def translate(self, message, main_file):
        """Tłumaczy odwołania „lini[ai] N" wbudowane w komunikat na
        oryginalne numery; gdy linia pochodzi z innego pliku niż główny
        plik raportowany w nagłówku błędu, dopisuje plik:
        `linia 108` → `linia 12 w pojemniki.ć`."""
        def repl(m):
            org = self.origin(int(m.group(2)))
            if org is None:
                return m.group(0)
            file, line = org
            suffix = f" w {file}" if file != main_file else ""
            return f"{m.group(1)} {line}{suffix}"
        return _LINE_REF.sub(repl, message)


def parse_directive(line):
    """Ścieżka z dyrektywy `uwzględnij <ścieżka>` albo None, gdy wiersz
    nie jest dyrektywą. Dyrektywa musi zaczynać się w kolumnie zerowej,
    a po słowie kluczowym musi stać biały znak (`uwzględnijmy` to nie
    dyrektywa). Treść normalizowana do NFC — edytory bywają niezgodne."""
    stripped = unicodedata.normalize("NFC", line.rstrip())
    if not stripped.startswith(DIRECTIVE):
        return None
    rest = stripped[len(DIRECTIVE):]
    if not rest or not rest[0].isspace():
        return None
    path = rest.strip()
    return path or None


def _resolve(base, target):
    """Ścieżka do pliku z dyrektywy `uwzględnij <target>`: najpierw
    relatywnie do katalogu `base` (pliku z dyrektywą), a gdy tam pliku
    nie ma — w folderze `biblioteki`. Gdy nigdzie go nie ma, zwraca
    ścieżkę relatywną, żeby komunikat błędu wskazał to, co napisał autor."""
    relative = os.path.join(base, target)
    if os.path.exists(relative):
        return relative
    library = os.path.join(BIBLIOTEKI, target)
    if os.path.exists(library):
        return library
    return relative


def _key(path):
    """Klucz deduplikacji: realpath (symlinki, `..`) + normalizacja NFC
    (ta sama nazwa w NFC i NFD to ten sam plik na macOS)."""
    return unicodedata.normalize("NFC", os.path.realpath(path))


def _merge_text(text, base, source_name, seen, out):
    """Scala tekst programu pochodzący z `source_name` do akumulatora
    `out` (pary: treść linii, (plik, linia oryginalna)); dyrektywy
    rozwiązywane względem katalogu `base`."""
    for lineno, line in enumerate(text.splitlines(), start=1):
        target = parse_directive(line)
        if target is None:
            out.append((line, (source_name, lineno)))
            continue
        _merge_file(_resolve(base, target), seen, out,
                    from_file=source_name, from_line=lineno)


def _merge_file(path, seen, out, *, from_file=None, from_line=None):
    key = _key(path)
    if key in seen:
        return
    seen.add(key)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        where = (f" (dyrektywa w {from_file}, linia {from_line})"
                 if from_file is not None else "")
        raise InterpreterError(
            f"nie można odczytać pliku '{path}': "
            f"{e.strerror or e}{where}",
            line=from_line,
        )
    _merge_text(text, os.path.dirname(path), path, seen, out)


def _scalony(out):
    return Scalony(
        text="\n".join(line for line, _ in out) + "\n",
        origins=[org for _, org in out],
    )


def resolve(path):
    """Punkt wejścia: plik → Scalony (tekst z końcowym '\\n' + mapa)."""
    out = []
    _merge_file(path, set(), out)
    return _scalony(out)


def resolve_stdin(text):
    """Wariant dla stdin: dyrektywy względem bieżącego katalogu."""
    out = []
    _merge_text(text, "", "<stdin>", set(), out)
    return _scalony(out)
