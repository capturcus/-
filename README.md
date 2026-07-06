# Język Ć

Ć to język programowania, w którym kod pisze się po polsku — z prawdziwą
polską odmianą. Identyfikatory są fleksyjne: `użytkownik`, `użytkownika`,
`użytkownikiem` i `użytkowników` to ten sam identyfikator, a o roli słowa
w zdaniu decydują przypadki gramatyczne i przyimki, nie pozycja czy
interpunkcja. Program w Ć czyta się jak (nieco techniczna) polszczyzna:

```
uwzględnij przygrywka.ć

definicja Użytkownika:
    imię (Tekst)
    wiek (Liczba)

aby przywitać użytkownika (Użytkownik) -> Tekst:
    zwróć sklej "cześć, " z imieniem użytkownika

aby działać:
    gość to Użytkownik o imieniu "Ada" o wieku trzydzieści
    powitanie to przywitaj gościa
```

Stan projektu: programy **parsują się i typują w całości** (pełna
inferencja typów, polskie komunikaty błędów), ale **runtime jeszcze nie
istnieje** — kod się sprawdza, lecz jeszcze nie wykonuje.

---

## Szybki start

Wymagania: Python 3 oraz plik słownika `sgjp.tab` (Słownik Gramatyczny
Języka Polskiego w formacie tab) w korzeniu repozytorium.

```
python3 gćć-python/gćć.py test/warianty.ć --sgjp sgjp.tab
```

Wynik to drzewo programu i wywnioskowane typy; błędny kod dostaje polski
komunikat z plikiem i numerem linii. Ładowanie słownika trwa ~8 s — przy
częstym iterowaniu użyj trybu redisowego:

```
pip3 install redis                      # raz
python3 gćć-python/sgjp_do_redisa.py    # raz (i po każdej wymianie sgjp.tab)
python3 gćć-python/gćć.py test/warianty.ć --redis   # start w ~0,1 s
```

Migracja jest idempotentna — wykrywa nową wersję `sgjp.tab` i wtedy
przeprowadza się ponownie, w przeciwnym razie nic nie robi.

Do VS Code jest wtyczka z kolorowaniem składni (katalog `vscode-ć/`,
motyw „Ć — biało-czerwony") — instalacja przez symlink do
`~/.vscode/extensions/` i restart edytora.

---

## Słowa i odmiana — fundament języka

Słowo dzieli się na **segmenty**: po podkreślniku (`zapisz_w_bazie`) i po
wielkich literach (`AdresKorespondencyjny`). Segmenty są analizowane
morfologicznie, a identyfikator znaczy to samo we wszystkich swoich
odmianach — deklarujesz `licznik`, a piszesz `licznika`, `licznikiem`,
`liczniki`, jak wymaga zdanie.

Identyfikator wielosegmentowy ma postać `[przymiotniki] rzeczownik
[reszta]` — np. `czerwona_inna_rzecz_z_warszawy`; przymiotniki zgadzają
się z rzeczownikiem w przypadku.

**Wielkość liter rozdziela przestrzenie nazw**: typy piszemy Wielką literą
(`Użytkownik`, `Lista`), zmienne, pola i funkcje — małą. Zmienna `lista`
i typ `Lista` współistnieją bez konfliktu.

Komentarze zaczynają się od `#`. Bloki wyznaczają wcięcia (tabulator lub
cztery spacje), jak w Pythonie.

---

## Zmienne i przypisanie

Przypisanie to słowo `to`:

```
licznik to zero
licznik to licznik plus jeden
```

Obowiązuje **zasięg blokowy**:

- pierwsze przypisanie deklaruje zmienną — widoczną **od tego miejsca do
  końca bloku**; użycie przed przypisaniem to błąd,
- zmienna zadeklarowana w gałęzi `jeśli`, ciele pętli albo gałęzi
  dopasowania jest **lokalna dla tego bloku**,
- przypisanie do zmiennej widocznej z zewnątrz to **reasignacja** tej
  samej zmiennej (typ musi się zgadzać) — zmienną potrzebną po bloku
  zadeklaruj przed nim:

```
wynik to zero
jeśli warunek:
    wynik to pięć      # reasignacja zewnętrznego `wynik`
suma to wynik          # OK
```

---

## Literały

**Liczby** zapisuje się słowami; sąsiadujące liczebniki sklejają się
w jedną wartość:

```
zero    jeden    dwadzieścia trzy    sto dwadzieścia pięć tysięcy czterysta
```

**Prawda i fałsz** (typ `Przełącznik`): `prawda` / `fałsz` — działają też
w odmianie (`przyjmij prawdę`).

**Teksty** w cudzysłowach, ze znakami ucieczki `\n \t \r \\ \" \' \0`:
`"pierwszy wiersz\ndrugi"`. Tekst nie jest typem wbudowanym — literał
tekstowy wymaga aliasu `Tekst` (dostajesz go przez `uwzględnij
przygrywka.ć`, gdzie `Tekst to Lista o elemencie Znak`); pusty tekst
`""` ≡ `Nic`.

**Znaki** (typ `Znak`) w pojedynczych cudzysłowach, z tymi samymi
znakami ucieczki: `'a'`, `'ż'`, `'\n'`. Literał musi zawierać dokładnie
jeden znak.

---

## Operatory

| operatory | znaczenie |
|---|---|
| `plus`, `minus`, `razy` | arytmetyka na `Liczbie` |
| `mniejsze od`, `większe od`, `mniejsze równe`, `większe równe`, `równe`, `nierówne` | porównania (dają `Przełącznik`) |
| `i`, `lub`, `nie` | logika na `Przełączniku` |

Priorytety od najsłabszego: `lub` < `i` < `nie` < porównania <
`plus`/`minus` < `razy` < unarny `minus`. Nawiasy grupują dowolne
wyrażenie:

```
suma to (dwa plus trzy) razy cztery
gotowe to nie zajęte i suma większe od dziesięć
```

---

## Sterowanie

```
jeśli koszt większe od budżet:
    ...
inaczej jeśli koszt równe budżet:
    ...
inaczej:
    ...

dopóki licznik mniejsze od dziesięć:
    licznik to licznik plus jeden

dla użytkownika w liście:
    jeśli użytkownik równe szukany:
        stop          # przerwij pętlę
    dalej             # następna iteracja

zwróć wyrażenie
zwróć                 # bez wartości — Nic
```

`dla` jest słowem strukturalnym tylko na początku instrukcji — w środku
wyrażenia pozostaje zwykłym przyimkiem (`weź dla użytkownika`).

---

## Funkcje — `aby`

```
aby wysłać coś do odbiorcy przez kanał:
    ...

aby liczyć listę (Lista) -> Liczba:
    ...
```

- Nazwa funkcji musi zawierać **czasownik** (`wysłać`, `zapisać_w_bazie`).
- Parametr to `[przyimek] nazwa [(Typ)]` — typ jest opcjonalny (wywnioskuje
  go inferencja), a przyimek i przypadek nazwy stają się „gramatyczną
  sygnaturą" parametru.
- `-> Typ` deklaruje typ zwracany (też opcjonalny).

**Wywołanie** to czasownik i argumenty. Argument dopasowuje się do
parametru po **(przyimku, przypadku)** — kolejność może być dowolna,
jeśli gramatyka rozstrzyga:

```
wyślij "raport" przez pocztę do szefa    # inna kolejność niż w sygnaturze
```

Argumentem jest pojedynczy „człon": literał, zmienna, łańcuch pól,
zagnieżdżone wywołanie. Większe wyrażenie ujmij w nawiasy:
`policz z (dwa plus trzy)`. **Nazwy parametru nie powtarza się** — rolę
niesie przyimek: `powiadom odbiorcę o "nowość"`.

Konwencja form: **definiuj bezokolicznikiem, wołaj rozkaźnikiem** —
`aby dodać...`, potem `dodaj x do y`. Obie formy muszą mieć wspólną lemmę,
więc uwaga na pary aspektowe: `dodaj` → `dodać` (nie `dodawać`),
`wybierz` → `wybrać`, `przyjmij` → `przyjąć`.

Funkcja bez żadnego `zwróć` — podobnie jak `zwróć` bez wartości
i `zwróć Nic` — ma typ zwracany `Nic`.

---

## Funkcje zewnętrzne — `można`

Granica świata: sieć, zegar, operacje na tekstach. Deklaracja bez ciała,
dlatego **wszystkie typy muszą być jawne**:

```
można wypisać tekst (Tekst) -> Nic
można skleić tekst (Tekst) z drugim (Tekst) -> Tekst
można pobrać_czas -> Liczba
```

Nieznana głowa typu (np. `Uchwyt`) działa jak parametr typu współdzielony
w obrębie sygnatury.

---

## Struktury — `definicja`

```
definicja Użytkownika:
    imię (Tekst)
    wiek (Liczba)

definicja Mapy z klucza na wartość:     # typ generyczny
    wpisy (Lista)
```

Nagłówek w dopełniaczu („definicja *czego*"), pola w mianowniku, typy pól
w nawiasach. Parametry typu (`z elementem`, `z klucza na wartość`) to małe
nazwy używane potem jako typy pól.

**Konstruktor** to po prostu nazwa typu — wielka litera wystarcza za słowo
kluczowe:

```
gość to Użytkownik o imieniu "Ada" o wieku trzydzieści
```

- `o polu WARTOŚĆ` — pole w **miejscowniku**, wartość to pełne wyrażenie,
- `z polem` — skrót: weź wartość z zadeklarowanej zmiennej o nazwie pola
  (pole w **narzędniku**):

```
imię to "Bob"
gość to Użytkownik z imieniem o wieku czterdzieści
```

Konstruktory się zagnieżdżają: `Komentarz o autorze Użytkownik o imieniu
"Ada" o treści "hej"` — pole nienależące do wewnętrznego typu wraca do
zewnętrznego.

---

## Dostęp do pól — łańcuchy dopełniaczowe

Odczyt pola to konstrukcja „pole *czego*" — obiekt w **dopełniaczu**,
łańcuchy dowolnej długości:

```
powitanie to imię użytkownika
miasto to nazwa adresu użytkownika sesji
```

Zapis — łańcuch po lewej stronie `to`:

```
wiek użytkownika to wiek użytkownika plus jeden
```

---

## Typy wariantowe — `albo` i dopasowanie `jest:` / `są:`

Unię deklaruje się przypisaniem na typach:

```
definicja Sukcesu z elementem:
    wartość (element)

definicja Błędu:
    opis (Tekst)

Rezultat to Sukces albo Błąd
```

Wariantem może być każda struktura zdefiniowana w programie oraz wbudowane
`Nic` — jedyny typ zero-argumentowy (`Opcja to Coś albo Nic`). Unie nie
zagnieżdżają się w uniach; przy deklaracji nie podaje się parametrów typu.

**Dopasowanie** to polski orzecznik — „X *jest* (czym?) *Błędem*".
Gałęzie w **narzędniku**, dekonstrukcja przez `z polem`:

```
rezultat jest:
    Sukcesem z wartością:
        wypisz wartość
    Błędem z opisem:
        wypisz opis
```

- **Orzecznik zgadza się liczbą z podmiotem**: `lista jest:`, ale
  `kwiatki są:` — pomyłka daje błąd z podpowiedzią właściwej formy.
  Podmiot dopasowania stoi w **mianowniku**.
- Gałęzie muszą pokryć **wszystkie** warianty unii; `Nic` obsługuje
  gałąź `Niczym:`. Alternatywnie OSTATNIĄ gałęzią może być **`inaczej:`** —
  pokrywa pozostałe warianty (bez wiązania pól):

  ```
  wartość jest:
      Symbolem z symbolem:
          zwróć symbol
      inaczej:
          zwróć ""
  ```

  Jawne gałęzie muszą być podzbiorem wariantów którejś unii; gdy pasuje
  ich kilka, o typie podmiotu rozstrzygają jego pozostałe wystąpienia
  (nierozstrzygnięty w `działać` → „dodaj adnotację typu").
- Wiązać można podzbiór pól (również żadne: `Sukcesem:`).
- Pola związane są lokalne dla gałęzi.
- Dopasowanie na nieotypowanym parametrze **wnioskuje** jego unię do
  sygnatury funkcji.

Jedyna relacja podtypowania: **struktura < jej unia**. Funkcja zwracająca
w różnych gałęziach różne warianty jednej unii dostaje typ unii; warianty
bez wspólnej unii to błąd. Typy parametryzowane są inwariantne
(`Lista z (Sukces)` to nie `Lista z (Rezultat)`).

---

## Wywołania z obsługą błędu — tryb przypuszczający + `?`

Odpowiednik operatora `?` z Rusta. Czasownik w **trybie przypuszczającym**
otwiera wywołanie, `?` po argumentach je domyka:

```
napis to wybrałbyś zero z części?
```

znaczy dokładnie:

```
tymczasowy to wybierz zero z części
tymczasowy jest:
    Sukcesem z wartością:
        napis to wartość
    Błędem z opisem:
        zwróć Błąd o opisie opis
```

Oba znaczniki są obowiązkowe — tryb bez `?` i `?` bez trybu to błędy.
Konstrukcja wymaga zadeklarowanej unii `Rezultat to Sukces albo Błąd`
(dokładnie tej postaci, jak wyżej). Wołana funkcja musi zwracać
`Rezultat`, a typ zwracany funkcji otaczającej rozszerza się o `Błąd`.
Ponieważ `?` domyka wywołanie, zagnieżdżenie nie potrzebuje nawiasów:

```
zapisz wydobyłbyś wartość z listy? do bazy
```

---

## Funkcje wyższego rzędu — gerundium i `zastosuj`

Funkcję przekazuje się przez jej **rzeczownik odczasownikowy**:
`dodawanie` to referencja do funkcji `dodawać`, `rozbieranie_koniunkcji` —
do `rozbierać_koniunkcję` (nominalizacja naturalnie przesuwa dopełnienie
do dopełniacza — tożsamość po lematach załatwia tę różnicę sama).
Referencje wskazują funkcje zdefiniowane w programie — jak wskaźniki
funkcji w C, bez domknięć.

Wartość funkcyjną wywołuje wbudowany czasownik `zastosuj` — argumenty
pozycyjnie, każdy przez `z` + narzędnik:

```
aby złożyć listę z operacją z akumulatorem:        # fold
    lista jest:
        Węzłem z głową z ogonem:
            reszta to złóż ogon z operacją z akumulatorem
            zwróć zastosuj operację z głową z resztą
        PustąListą:
            zwróć akumulator

suma to złóż liczby z dodawaniem z zero            # referencja gerundialna
```

Zasady:

- **Zmienna przesłania referencję** — parametr `operacja` w ciele to
  zmienna; gerundium działa jako referencja tylko, gdy nazwy nie ma
  w zasięgu.
- **`zastosować` jest zarezerwowane** — własnej funkcji o tym lemacie nie
  można zadeklarować (`zastosować_filtr` — można).
- **Tryb przypuszczający komponuje się**: `zastosowałbyś operację
  z wartością?` to zastosowanie z obsługą błędu (wymagania jak przy `?`).
- Typy strzałkowe są w pełni inferowane (`operacja : (Liczba, Liczba) →
  Liczba`); nie ma składni na strzałkę w `można` ani w polach struktur.
- Funkcja zwracająca jeden wariant unii (np. samego `Sukcesa`) pasuje
  tam, gdzie oczekiwany jest zwrot całej unii (`Rezultat`) — argumenty
  funkcji muszą się natomiast zgadzać dokładnie.
- Zagnieżdżony goły `zastosuj` zachłannie zjada kolejne `z …` — w wartości
  pola, w argumencie wywołania i w argumencie innego `zastosuj` używaj
  nawiasów: `bierz jeden z (zastosuj operację z dwa)`.

Typowe funkcje wyższego rzędu (fold, map, filter) zaimplementowane w Ć:
`test/fwr.ć`; realne użycie (gramatyka parsera jako jeden fold
sparametryzowany referencjami): `test/wyrażenia.ć`.

---

## Wiele plików — `uwzględnij`

Program można rozbić na pliki — dyrektywa `uwzględnij` wstawia zawartość
wskazanego pliku w miejscu dyrektywy (deklaracje w Ć są niezależne od
kolejności, więc to wystarcza):

```
uwzględnij pojemniki.ć
uwzględnij biblioteki/napisy.ć
```

- Ścieżka jest **względna wobec pliku, w którym stoi dyrektywa**.
- **Każdy plik wchodzi najwyżej raz** — gdy dwa pliki uwzględniają tę
  samą bibliotekę, jej deklaracje się nie powielają.
- Dyrektywa musi zaczynać się w kolumnie zerowej i jest rozpoznawana
  literalnie (bez odmiany).
- Błędy wskazują **plik źródłowy i oryginalny numer linii**, także przy
  konfliktach między plikami.

Przykład w repozytorium: `test/fwr.ć` uwzględnia `test/pojemniki.ć`.

---

## System typów w praktyce

Typów prawie nie trzeba pisać — inferencja wyprowadza sygnatury funkcji,
typy zmiennych, generyki i typy strzałkowe wartości funkcyjnych
z samego kodu, także przez referencje w przód i rekurencję wzajemną.
Adnotacje są dostępne tam, gdzie ich chcesz:

```
aby liczyć listę (Lista z elementem) -> Liczba:    # parametry i wynik
x (Liczba) to pięć                                 # zmienna
wynik to (weź od y) (Tekst)                        # sufiks na wyrażeniu
```

Mała, nieznana nazwa typu w sygnaturze (`element`, `rzecz`) działa jak
niejawny parametr typu — tak powstają funkcje generyczne.

Funkcja `działać` to punkt wejścia: wszystkie jej zmienne muszą mieć
w pełni konkretne typy (odpowiednik „type annotations needed").

Typy wbudowane: `Liczba`, `Przełącznik`, `Nic`, `Znak`. `Tekst` to alias
z przygrywki (`Tekst to Lista o elemencie Znak`) — nie jest wbudowany.

---

## Pułapki, o których warto wiedzieć

- **Wspólna lemma definicji i wywołania** — pary aspektowe mylą:
  `dodaj` → `dodać` (nie `dodawać`), `wziąłbyś` → `wziąć` (nie `brać`).
  Definiuj tym czasownikiem, którego formy faktycznie wołasz.
- **Nazwa parametru nie może być przyimkiem** (`a`, `u`, `w`, `z`, `o`…) —
  zostanie zjedzona jako przyimek.
- **Niejednoznaczność morfologiczna nazw pól** — np. `posty` czyta się
  i jako `post`, i jako `posta`; interpreter to zgłosi, wtedy wybierz
  inną nazwę (np. `wpisy`).
- **Formy eufoniczne przyimków działają** — `ze`, `we` są równoważne
  `z`, `w` wszędzie (`ze schodzeniem` ≡ `z ...`).
- **Rzeczowniki odczasownikowe są pełnoprawnymi rzeczownikami** —
  `polubienie` ma własną lemmę; pole `polubienia` nie koliduje z funkcją
  `polubić`.
- **Każde słowo musi istnieć w SGJP** — nazwa spoza słownika (np. `arność`)
  nie odmienia się i psuje program w zaskakujących miejscach. Sprawdź
  słowo przed użyciem (`redis-cli EXISTS sgjp:f:słowo`) i wybierz synonim
  (np. `krotność`).
- **Nazwa zmiennej nie może być liczebnikiem ani zaimkiem liczebnym** —
  `ile`, `dwa` itp. czytają się jako liczby.
- **Nie nazywaj kolekcji liczbą mnogą nazwy będącej już w zasięgu** —
  `ogniwa` to także dopełniacz lp od `ogniwo`, więc lista `ogniwa` obok
  parametru `ogniwo` skleja się z nim (objaw: błąd `occurs check`).
  Daj kolekcji inną głowę rzeczownikową (`zbiór`, `spis`).
- **W referencji gerundialnej do funkcji wielosegmentowej podkreślnik jest
  obowiązkowy** — `z polubieniem_wpisu` to referencja do `polubić_wpis`,
  ale `z polubieniem wpisu` (dwa słowa) może się sparsować jako odczyt
  pola `polubienia` zmiennej `wpis`, jeśli takie pole istnieje — błąd
  wyjdzie dopiero w typach, daleko od przyczyny.

---

## Przykłady

Katalog `test/` to żywa dokumentacja — te pliki parsują się i typują
obecnym interpreterem:

| plik | co pokazuje |
|---|---|
| `test.ć` | minimalny przykład: unia, dopasowanie z `inaczej:` |
| `warianty.ć` | unie, dopasowanie `jest:`, funkcje zewnętrzne |
| `nic.ć` | `Nic` w uniach i wnioskowanie typu `Nic` |
| `instagram.ć` | backend aplikacji: stan, operacje API, `?`, kontenery |
| `analizator_morfologiczny.ć` | duży program: listy, słowniki, `Rezultat`, `?` |
| `wyrażenia.ć` | parser wyrażeń: unie AST, try-calle, gramatyka jako jeden fold |
| `fwr.ć` + `pojemniki.ć` | funkcje wyższego rzędu (fold, map, filter) i `uwzględnij` |
| `parametryzowane.ć` | typy generyczne (mapy, drzewa AVL) |
| `lista.ć`, `stos.ć`, `para.ć`, `słownik.ć` | proste struktury danych |
| `łańcuchy_dopełniaczowe.ć` | dostęp do pól |
| `las.ć`, `test_typów.ć`, `definicje.ć`, `bank.ć` | drobne scenariusze |

---

## Struktura repozytorium

```
gćć-python/        interpreter referencyjny + testy pytest
test/              programy w Ć i podzbiór słownika do testów
vscode-ć/          wtyczka VS Code (składnia + motyw biało-czerwony)
sgjp.tab           pełny słownik SGJP (niewersjonowany)
make_subset.py     generator podzbioru słownika
```

Testy interpretera: `cd gćć-python && python3 -m pytest -q` (pierwszy raz
ładuje SGJP ~8 s; testy trybu redisowego pomijają się same, gdy Redis
nie działa).
