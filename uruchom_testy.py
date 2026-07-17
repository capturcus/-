#!/usr/bin/env python3
"""Testy end-to-end interpretera Ć.

Uruchamia każdy plik `*.ć` ze wskazanych katalogów testowych przez
`gćć.py --redis` i ocenia go według plików towarzyszących o tej samej
nazwie:

  NAZWA.wynik      test POZYTYWNY — program ma przejść (exit 0),
                   a stdout równać się 1:1 treści pliku
  NAZWA.błąd       test NEGATYWNY — program ma odpaść (exit != 0),
                   a każda niepusta linia pliku musi wystąpić
                   w stderr jako podłańcuch
  NAZWA.argumenty  (opcjonalnie) argumenty programu, przekazywane
                   po znaczniku `--` (trafiają do `działać`)
  NAZWA.wejście    (opcjonalnie) standardowe wejście programu;
                   bez pliku program dostaje EOF, żeby test nigdy
                   nie zawisł na terminalu

Plik .ć bez .wynik i bez .błąd to porażka (zapomniane oczekiwanie) —
chyba że jest biblioteką dołączaną przez `uwzględnij` (BIBLIOTEKI).

Bez argumentów uruchamia wszystkie katalogi domyślne.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

KATALOG = Path(__file__).resolve().parent
GCC = KATALOG / "gćć-python" / "gćć.py"
DOMYŚLNE = ("test", "test_skradzion")

sys.path.insert(0, str(KATALOG / "gćć-python"))
import argparse_po_polsku  # noqa: E402 — ścieżka znana dopiero po KATALOG

argparse_po_polsku.spolszcz()

# Pliki biblioteczne (dołączane przez `uwzględnij`) — nie są testami,
# nie mają `aby działać` ani pliku .wynik. Standardowe biblioteki
# (przygrywka.ć, operacje_tekstowe.ć) mieszkają w biblioteki/ i tak
# nie trafiają do globu; tu zostają tylko biblioteki lokalne testów.
BIBLIOTEKI = {"słownik.ć"}

# Builtiny graficzne (gra.ć) rysują na sucho — bez otwierania prawdziwych
# okien; dla testów bez grafiki ta zmienna jest obojętna.
ŚRODOWISKO = {**os.environ, "SDL_VIDEODRIVER": "dummy"}


def uruchom_katalog(katalog):
    """Uruchamia wszystkie testy katalogu; zwraca (przeszło, wszystkich)."""
    pliki = sorted(p for p in katalog.glob("*.ć")
                   if p.name not in BIBLIOTEKI)
    porazki = 0
    for plik in pliki:
        wynik_path = plik.with_suffix(".wynik")
        błąd_path = plik.with_suffix(".błąd")
        if not wynik_path.exists() and not błąd_path.exists():
            print(f"PORAŻKA {plik.name}: brak pliku {wynik_path.name} "
                  f"ani {błąd_path.name}")
            porazki += 1
            continue
        argumenty = []
        arg_path = plik.with_suffix(".argumenty")
        if arg_path.exists():
            argumenty = ["--"] + arg_path.read_text(
                encoding="utf-8").split()
        wejście_path = plik.with_suffix(".wejście")
        wejście = (wejście_path.read_text(encoding="utf-8")
                   if wejście_path.exists() else "")
        proces = subprocess.run(
            [sys.executable, str(GCC), "--redis", str(plik), *argumenty],
            capture_output=True, text=True, input=wejście, env=ŚRODOWISKO,
        )
        if błąd_path.exists():
            wzorce = [w for w in błąd_path.read_text(
                encoding="utf-8").splitlines() if w.strip()]
            if proces.returncode == 0:
                print(f"PORAŻKA {plik.name}: miał odpaść, przeszedł")
                porazki += 1
            elif not all(w in proces.stderr for w in wzorce):
                print(f"PORAŻKA {plik.name}: stderr bez oczekiwanego "
                      f"wzorca")
                print(f"  oczekiwane fragmenty: {wzorce!r}")
                print(f"  stderr: {proces.stderr.rstrip()}")
                porazki += 1
            else:
                print(f"OK      {plik.name} (negatywny)")
            continue
        oczekiwane = wynik_path.read_text(encoding="utf-8")
        if proces.returncode != 0:
            print(f"PORAŻKA {plik.name}: exit {proces.returncode}")
            print(proces.stderr.rstrip())
            porazki += 1
        elif proces.stdout != oczekiwane:
            print(f"PORAŻKA {plik.name}")
            print(f"  oczekiwane: {oczekiwane!r}")
            print(f"  otrzymane:  {proces.stdout!r}")
            porazki += 1
        else:
            print(f"OK      {plik.name}")
    print(f"\n{katalog.name}: {len(pliki) - porazki}/{len(pliki)} "
          f"testów przeszło")
    return len(pliki) - porazki, len(pliki)


def main():
    argp = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    argp.add_argument(
        "katalogi", nargs="*", metavar="KATALOG",
        default=list(DOMYŚLNE),
        help="katalogi testów do uruchomienia, względem katalogu "
             f"repozytorium (domyślnie: {', '.join(DOMYŚLNE)})")
    args = argp.parse_args()
    przeszło = wszystkich = 0
    for nazwa in args.katalogi:
        katalog = Path(nazwa)
        if not katalog.is_absolute():
            katalog = KATALOG / katalog
        if not katalog.is_dir():
            print(f"PORAŻKA: '{nazwa}' nie jest katalogiem")
            return 1
        print(f"=== {katalog.name} ===")
        ok, ile = uruchom_katalog(katalog)
        przeszło += ok
        wszystkich += ile
        print()
    if len(args.katalogi) > 1:
        print(f"RAZEM: {przeszło}/{wszystkich} testów przeszło")
    return 0 if przeszło == wszystkich and wszystkich > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
