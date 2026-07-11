# Slajd finałowy: mapa „polszczyzna → znaczenie programistyczne"

## Wersja pełna (materiał referencyjny / handout)

### Słowo — morfologia jako tożsamość

| mechanizm polszczyzny | znaczenie w Ć | przykład |
|---|---|---|
| lemat (forma słownikowa) | tożsamość identyfikatora — odmiana nie zmienia bytu | `licznik / licznika / licznikiem` — jedna zmienna |
| liczba gramatyczna | część klucza zakresu — lp i lm to różne byty | `forma` ≠ `formy` |
| rodzaj gramatyczny | część klucza zakresu | `kotek` (m) ≠ `kotka` (f) |
| mianownik | forma deklaracji — słownikowa postać wprowadza byt | `licznik to zero` |
| zgoda przymiotnik–rzeczownik | spójność segmentów nazwy wieloczłonowej | `duże_czerwone_drzewo`, ale nie `dużym_czerwone_drzewami` |
| słownik (SGJP, 5 mln form) | legalność nazw — co nie istnieje w polszczyźnie, nie istnieje w Ć | `arność` → odrzucone; `krotność` → OK |
| wielka litera | przestrzeń typów (ortografia niesie semantykę) | zmienna `lista` obok typu `Lista` |
| eufonia przyimków | `ze`/`we` ≡ `z`/`w` | `Krokiem ze znakiem:` |

### Przypadek i przyimek — rola zamiast pozycji

| mechanizm | znaczenie | przykład |
|---|---|---|
| przyimek + przypadek argumentu | dopasowanie do parametru po ROLI, nie kolejności | `wyślij "raport" przez pocztę do szefa` — dowolny szyk |
| dopełniacz | przynależność = odczyt pola, łańcuchowo | `imię autora komentarza` |
| miejscownik po `o` | pole w konstrukcji, wartość jawna | `Kot o imieniu "Mruczek"` |
| narzędnik po `z` | pole-skrót ze zmiennej / argument aplikacji | `z imieniem`; `zastosuj f z wynikiem` |
| narzędnik orzecznika | wariant w dopasowaniu — „X jest (czym?)" | `zwierzę jest: Kotem:` |
| celownik przy porównaniu | drugi operand równości | `przód równy owocowi`, `głowa nierówna dzielnikowi` |

### Czasownik — cztery formy, cztery znaczenia

| forma | znaczenie | przykład |
|---|---|---|
| bezokolicznik | definicja funkcji | `aby dodać liczbę do innej_liczby:` |
| rozkaźnik | wywołanie | `dodaj dwa do trzech` |
| rzeczownik odczasownikowy | funkcja jako wartość (referencja) | `złóż listę z dodawaniem z zero` |
| tryb przypuszczający + `?` | wywołanie z obsługą błędu | `wybrałbyś zero z części?` |

### Zdanie — składnia jako sterowanie

| mechanizm | znaczenie | przykład |
|---|---|---|
| `to` (orzeczenie imienne) | przypisanie | `gość to Użytkownik o…` |
| `jest:` / `są:` + zgoda liczby | dopasowanie wariantów; orzecznik zgadza się z podmiotem | `lista jest:` ale `wyniki są:` |
| `albo` | deklaracja unii = programowanie kraty podtypów | `Zwierzę to Kot albo Pies` |
| apozycja mianownikowa | argument typu w aplikacji nazwanej („o imieniu Jan") | `Lista o elemencie Znak` |
| stopień wyższy przymiotnika | operator porównania (w każdej odmianie) | `mniejszy od`, `większa równa` |
| liczebniki słowne (z odmianą) | literały liczbowe | `sto dwadzieścia trzy`, `od dziewiętnastu` |

### Znaczenie — pragmatyka jako wnioskowanie

| mechanizm | znaczenie | przykład |
|---|---|---|
| fraza nominalna | wnioskowanie typu z użycia — „rzecz jest czymś, co ma X" | `waga rzeczy` + `uszko rzeczy` ⇒ rzecz = Kubeł |
| wiedza o świecie | pola wspólne unii czytane bez zawężania | `owoc stanu` — czy pełza, czy poległ |
| rozbiór zdania wymaga arności | składnia i typy splecione — parser zna funkcje | pp-attachment w `testuj_funkcję domkowi samochodu z psem` |
| konflikt = sprzeczna narracja | błąd typów jako dowód: poszlaki z linii, werdykt u autora | „zdecyduj, która poszlaka jest błędna" |

## Wersja slajdowa (8 wierszy — reszta w handout)

| po polsku | w Ć |
|---|---|
| odmiana słowa | jedna tożsamość: `licznik = licznikiem` |
| przypadek + przyimek | rola argumentu zamiast pozycji |
| dopełniacz | odczyt pola: `imię autora komentarza` |
| 4 formy czasownika | definicja / wywołanie / wartość / obsługa błędu |
| „X jest Kotem" | dopasowanie i zawężanie typu |
| „albo" | unia = własnoręcznie zaprogramowana krata |
| fraza nominalna | wnioskowanie: `waga rzeczy` ⇒ rzecz ma wagę |
| sprzeczna opowieść | błąd typów = poszlaki + werdykt autora |

**Zdanie zamykające:** nie wymyśliliśmy tej składni — pożyczyliśmy ją
z języka, który znacie od urodzenia. Interpreter to tylko bardzo uważny
czytelnik: lekser zna odmianę, parser zna role w zdaniu, a system typów
czyta ze zrozumieniem.
