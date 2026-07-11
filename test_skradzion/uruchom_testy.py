#!/usr/bin/env python3
"""Testy end-to-end skradzione z suit innych kompilatorów.

Scenariusze zachowań systemu typów zaczerpnięte z testów OCamla, Flow,
Crystala i TypeScriptu, przepisane na oryginalne programy w Ć.

Architektura jak w test/, z jednym rozszerzeniem: obok pozytywnych par
`NAZWA.ć` + `NAZWA.wynik` (exit 0, stdout 1:1) działają testy NEGATYWNE
`NAZWA.ć` + `NAZWA.błąd` — program MA odpaść (exit != 0), a stderr musi
zawierać każdą niepustą linię pliku .błąd jako podłańcuch.
"""
import os
import subprocess
import sys
from pathlib import Path

KATALOG = Path(__file__).resolve().parent
GCC = KATALOG.parent / "gćć-python" / "gćć.py"

ŚRODOWISKO = {**os.environ, "SDL_VIDEODRIVER": "dummy"}


def main():
    pliki = sorted(KATALOG.glob("*.ć"))
    if not pliki:
        print("brak plików .ć w katalogu testów")
        return 1
    porazki = 0
    for plik in pliki:
        wynik_path = plik.with_suffix(".wynik")
        błąd_path = plik.with_suffix(".błąd")
        proces = subprocess.run(
            [sys.executable, str(GCC), "--redis", str(plik)],
            capture_output=True, text=True, input="", env=ŚRODOWISKO,
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
                print(f"  stderr: {proces.stderr[:400]!r}")
                porazki += 1
            else:
                print(f"OK      {plik.name} (negatywny)")
            continue
        if not wynik_path.exists():
            print(f"PORAŻKA {plik.name}: brak pliku {wynik_path.name}")
            porazki += 1
            continue
        oczekiwane = wynik_path.read_text(encoding="utf-8")
        if proces.returncode != 0:
            print(f"PORAŻKA {plik.name}: exit {proces.returncode}")
            print(proces.stderr.rstrip()[:400])
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
