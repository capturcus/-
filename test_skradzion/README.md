# Testy skradzione z suit innych kompilatorów

Scenariusze zachowań systemu typów zaczerpnięte z testów OCamla
(`typing-poly`, `typing-rectypes`, `typing-misc`), Flow (`refinements`,
`recursive_defs`), Crystala (semantic: `if`, `union`, rekurencyjne
struktury) i TypeScriptu (narrowing, excess property check),
przepisane na **oryginalne programy w Ć** — kradzione są pomysły
na scenariusze, nie kod.

Uruchamianie i konwencje plików (`.wynik`, `.błąd`, …): wspólny runner
w katalogu głównym repozytorium — `python3 uruchom_testy.py
test_skradzion` (opis: `-h`).

Znaleziska tej suity (dziura #14 — gaszenie cienia zawężenia, #15 —
`_brak_pola`) są opisane i odhaczone w `nieścisłości_typów.md`.
