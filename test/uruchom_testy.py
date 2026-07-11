#!/usr/bin/env python3
"""Testy end-to-end interpretera Ć.

Każdy plik `*.ć` w tym katalogu jest uruchamiany przez `gćć.py --redis`,
a jego stdout porównywany 1:1 z plikiem `*.wynik` o tej samej nazwie.

Test NEGATYWNY to para `NAZWA.ć` + `NAZWA.błąd` (zamiast `.wynik`):
program ma się NIE powieść (exit ≠ 0), a każda niepusta linia pliku
`.błąd` musi wystąpić w stderr jako podłańcuch.
"""
import os
import subprocess
import sys
from pathlib import Path

KATALOG = Path(__file__).resolve().parent
GCC = KATALOG.parent / "gćć-python" / "gćć.py"

# Builtiny graficzne (gra.ć) rysują na sucho — bez otwierania prawdziwych
# okien; dla testów bez grafiki ta zmienna jest obojętna.
ŚRODOWISKO = {**os.environ, "SDL_VIDEODRIVER": "dummy"}

# Pliki biblioteczne (dołączane przez `uwzględnij`) — nie są testami,
# nie mają `aby działać` ani pliku .wynik. Standardowe biblioteki
# (przygrywka.ć, operacje_tekstowe.ć) mieszkają w ../biblioteki i tak
# nie trafiają do globu; tu zostają tylko biblioteki lokalne dla testów.
BIBLIOTEKI = {"słownik.ć"}


def main():
    pliki = sorted(p for p in KATALOG.glob("*.ć") if p.name not in BIBLIOTEKI)
    if not pliki:
        print("brak plików .ć w katalogu testów")
        return 1
    porazki = 0
    for plik in pliki:
        wynik_path = plik.with_suffix(".wynik")
        błąd_path = plik.with_suffix(".błąd")
        if not wynik_path.exists() and not błąd_path.exists():
            print(f"PORAŻKA {plik.name}: brak pliku {wynik_path.name} "
                  f"ani {błąd_path.name}")
            porazki += 1
            continue
        # Opcjonalny plik NAZWA.argumenty: linie przekazywane programowi
        # po znaczniku `--` (argumenty `działać`).
        argumenty = []
        arg_path = plik.with_suffix(".argumenty")
        if arg_path.exists():
            argumenty = ["--"] + arg_path.read_text(
                encoding="utf-8").split()
        # Opcjonalny plik NAZWA.wejście: standardowe wejście programu
        # (dla `wczytaj_wejście`). Bez pliku program dostaje puste
        # wejście (EOF), żeby test nigdy nie zawisł na terminalu.
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
                print(f"OK      {plik.name}")
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
    print(f"\n{len(pliki) - porazki}/{len(pliki)} testów przeszło")
    return 1 if porazki else 0


if __name__ == "__main__":
    sys.exit(main())
