# Język Ć — wtyczka VS Code

Kolorowanie składni języka Ć w barwach biało-czerwonych. Dwa motywy:

- **`Ć — biało-czerwony`** (jasny) — białe tło, czerwony pasek stanu; słowa
  strukturalne i tryb przypuszczający czerwienią, typy ciemną czerwienią,
  przyimki bladą, reszta przygaszoną bielą.
- **`Ć — czerwono-biały`** (ciemny) — jebitnie czerwone tło, biały tekst,
  biały pasek stanu; te same barwy flagi, tylko odwrócone. Słowa strukturalne,
  tryb przypuszczający i typy bielą, reszta odcieniami różu.

Instalacja lokalna: katalog (albo symlink) w `~/.vscode/extensions/`,
potem restart VS Code. Motyw: `Cmd+K Cmd+T` → „Ć — biało-czerwony"
albo „Ć — czerwono-biały".

Rozszerzenie obsługuje pliki `.ć` w obu normalizacjach unicode (NFC i NFD —
macOS zapisuje nazwy plików w NFD).
