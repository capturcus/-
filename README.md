# Język Ć

Ć to język programowania, w którym kod pisze się po polsku — z prawdziwą
polską odmianą. Identyfikatory są fleksyjne: `użytkownik`, `użytkownika`,
`użytkownikiem` to ten sam identyfikator, a o roli słowa w zdaniu decydują
przypadki gramatyczne i przyimki, nie pozycja czy interpunkcja. Program
w Ć czyta się jak (nieco techniczna) polszczyzna:

```
uwzględnij przygrywka.ć

można wypisać coś (Cokolwiek) -> Nic

definicja Użytkownika:
    imię (Tekst)
    wiek (Liczba)

aby przywitać użytkownika:
    zwróć sklej "cześć, " z imieniem użytkownika

aby działać:
    gość to Użytkownik o imieniu "Ada" o wieku trzydzieści
    wypisz przywitaj gościa
    jeśli wiek gościa większy od osiemnastu:
        wypisz "pełnoletnia"
```

```
$ python3 gćć-python/gćć.py program.ć --sgjp sgjp.tab
cześć, Ada
pełnoletnia
```

Programy w Ć **parsują się, typują i wykonują**. Typów prawie nie trzeba
pisać — pełna inferencja z podtypowaniem wyprowadza je z kodu, a błędy
przychodzą po polsku, ze śladem wnioskowania. Punktem wejścia programu
jest funkcja `działać`.

Spis treści:

- [Szybki start](#szybki-start)
- [Rytuał startowy programu](#rytuał-startowy-programu)
- [Słowa i odmiana — fundament języka](#słowa-i-odmiana--fundament-języka)
- [Literały](#literały)
- [Zmienne i przypisanie](#zmienne-i-przypisanie)
- [Operatory](#operatory)
- [Sterowanie](#sterowanie)
- [Funkcje — `aby`](#funkcje--aby)
- [Funkcje wbudowane i zewnętrzne — `można`](#funkcje-wbudowane-i-zewnętrzne--można)
- [Struktury — `definicja`](#struktury--definicja)
- [Unie — `albo` i dopasowanie `gdy … jest:`](#unie--albo-i-dopasowanie-gdy--jest)
- [Typy parametryzowane i aliasy](#typy-parametryzowane-i-aliasy)
- [Funkcje wyższego rzędu](#funkcje-wyższego-rzędu)
- [Bejcowanie — częściowa aplikacja `zwiąż`](#bejcowanie--częściowa-aplikacja-zwiąż)
- [Obsługa błędów — `Rezultat` i tryb przypuszczający](#obsługa-błędów--rezultat-i-tryb-przypuszczający)
- [Przygrywka — biblioteka standardowa](#przygrywka--biblioteka-standardowa)
- [Grafika i gry — biblioteka `gra.ć`](#grafika-i-gry--biblioteka-grać)
- [Wiele plików — `uwzględnij`](#wiele-plików--uwzględnij)
- [System typów](#system-typów)
- [Pułapki, o których warto wiedzieć](#pułapki-o-których-warto-wiedzieć)
- [Przykłady](#przykłady)
- [Struktura repozytorium](#struktura-repozytorium)

---

## Szybki start

Wymagania: Python 3 oraz plik słownika `sgjp.tab` (Słownik Gramatyczny
Języka Polskiego w formacie tab, do pobrania z sgjp.pl) w korzeniu
repozytorium — interpreter analizuje morfologicznie każde słowo programu,
więc bez słownika nie ruszy.

```
python3 gćć-python/gćć.py test/dna.ć --sgjp sgjp.tab
```

Ładowanie słownika trwa kilka sekund — przy częstym iterowaniu użyj trybu
redisowego (lematyzacja przez lokalny Redis, start natychmiastowy):

```
pip3 install redis                      # raz
python3 gćć-python/sgjp_do_redisa.py    # raz (i po każdej wymianie sgjp.tab)
python3 gćć-python/gćć.py test/dna.ć --redis
```

Migracja jest idempotentna — wykrywa nową wersję `sgjp.tab` i wtedy
przeprowadza się ponownie, w przeciwnym razie nic nie robi.

Testy end-to-end języka — pozytywne (`*.ć` + `*.wynik`: stdout 1:1)
i negatywne (`*.ć` + `*.błąd`: program ma odpaść, stderr zawiera
wskazane fragmenty); szczegóły w `uruchom_testy.py -h`:

```
python3 uruchom_testy.py                # oba katalogi; wymaga redisa
python3 uruchom_testy.py test           # tylko test/
python3 uruchom_testy.py test_skradzion # scenariusze z suit OCamla,
                                        # Flow, Crystala i TypeScriptu
```

Testy interpretera: `cd gćć-python && python3 -m pytest -q`.

Do VS Code jest wtyczka z kolorowaniem składni (katalog `vscode-ć/`) —
instalacja przez symlink do `~/.vscode/extensions/` i restart edytora.

Błędy — składniowe, typów i wykonania — przychodzą jako
`plik:linia: KlasaBłędu: komunikat` z fragmentem źródła; błędy wykonania
dodatkowo z Ć-owym stosem wywołań.

---

## Rytuał startowy programu

Prawie każdy program zaczyna się tak:

```
uwzględnij przygrywka.ć

aby działać:
    wypisz "siemka"
```

- `uwzględnij przygrywka.ć` dołącza bibliotekę standardową
  ([przygrywkę](#przygrywka--biblioteka-standardowa)) — m.in. typ `Tekst`,
  bez którego literały tekstowe się nie typują; funkcja `wypisać`. Ścieżkę
  interpreter rozstrzyga dwuetapowo: najpierw względem pliku z dyrektywą,
  a gdy tam jej nie ma — w folderze `biblioteki/` (rozstrzyganym względem
  lokalizacji interpretera). Dlatego `uwzględnij przygrywka.ć` działa
  z dowolnego katalogu, a lokalny plik o tej samej nazwie ma pierwszeństwo.
- `aby działać:` to punkt wejścia — interpreter po sprawdzeniu typów
  wywołuje funkcję o lemacie `działać`.

Punkt wejścia ma — jako jedyna funkcja w języku — **dwie dozwolone
sygnatury**: bezargumentową albo z jednym parametrem, który dostaje
argumenty wywołania programu (typu `Lista o elemencie Tekst`; pusta
lista ≡ `Nic`). Argumenty podaje się w CLI po znaczniku `--`:

```
aby działać dla argumentów:
    wypisz (zmierz argumenty)
```

```
$ python3 gćć-python/gćć.py --redis program.ć -- raz dwa trzy
3
```

`wypisz` przyjmuje dowolną wartość: teksty drukuje wprost, liczby
dziesiętnie, `Nic` jako `Nic`, struktury jako `Nazwa(pole: wartość, …)`
(cykliczne struktury są bezpiecznie ucinane znacznikiem `…`).

---

## Słowa i odmiana — fundament języka

Każde słowo programu jest analizowane morfologicznie w SGJP. Identyfikator
znaczy to samo we wszystkich swoich odmianach — deklarujesz `licznik`,
a piszesz `licznika`, `licznikiem`, jak wymaga zdanie. To odmiana, a nie
kolejność, mówi interpreterowi, co jest czym.

- **Segmenty.** Słowo dzieli się po podkreślniku (`zapisz_w_bazie`) i po
  wielkich literach (`AdresKorespondencyjny`); każdy segment jest
  analizowany osobno.
- **Klucz zakresu.** Zmienną/pole identyfikuje trójka **(lemat, liczba,
  rodzaj)** — `forma` (lp) i `formy` (lm) to różne zmienne, `kotek` (m)
  i `kotka` (f) też. Funkcje i typy są identyfikowane po samych lematach.
- **Mianownik przy deklaracji.** Nazwę deklaruje się w mianowniku
  (zmienne, pola, aliasy, warianty unii); wyjątki wymuszone gramatyką:
  nagłówek `definicja Sesji:` stoi w dopełniaczu (definicja *czego*),
  a gałęzie dopasowania w narzędniku (`Kotem:`).
- **Identyfikatory wielosegmentowe** mają postać `[przymiotniki]
  rzeczownik [reszta]` — np. `wielki_kot`, `autor_komentarza`;
  przymiotniki zgadzają się z rzeczownikiem-głową w przypadku.
- **Wielkość liter rozdziela przestrzenie nazw**: typy piszemy Wielką
  literą (`Użytkownik`, `Lista`), zmienne, pola i funkcje — małą. Zmienna
  `lista` i typ `Lista` współistnieją bez konfliktu.
- **Każde deklarowane słowo musi istnieć w SGJP** — nazwa spoza słownika
  nie odmienia się i jest odrzucana. Formy eufoniczne przyimków (`ze`,
  `we`) działają wszędzie jak `z`, `w`.

Komentarze zaczynają się od `#` i zajmują **całą linię** (nie ma
komentarza za kodem). Bloki wyznaczają wcięcia — tabulator albo cztery
spacje, jak w Pythonie.

---

## Literały

**Liczby zapisuje się wyłącznie słowami** — cyfr nie ma. Sąsiadujące
liczebniki sklejają się w jedną wartość, skala jest długa (miliard = 10⁹):

```
zero    jeden    dwadzieścia trzy    sto dwadzieścia pięć tysięcy czterysta
```

Jedyny typ liczbowy to `Liczba` (całkowita). Liczby ujemne powstają przez
jednoargumentowy `minus`: `minus pięć`. Liczebniki odmieniają się jak
wszystko inne: `podziel siedem przez dwa`, ale `weź_resztę_z_dzielenia
siedmiu przez dwa`.

**Teksty** (typ `Tekst`) w cudzysłowach, ze znakami ucieczki
`\n \t \r \\ \" \' \0`: `"pierwszy wiersz\ndrugi"`. `Tekst` nie jest
typem wbudowanym — to alias z przygrywki (`Tekst to Lista o elemencie
Znak`), a literał tekstowy to w istocie lista znaków; **pusty tekst `""`
≡ `Nic`**. Bez dołączonej przygrywki (albo własnego aliasu `Tekst`)
literał tekstowy jest błędem typów.

**Znaki** (typ `Znak`) w apostrofach, z tymi samymi znakami ucieczki:
`'a'`, `'ż'`, `'\n'`. Literał musi zawierać dokładnie jeden znak.

**Prawda i fałsz** (typ `Przełącznik`): `prawda` / `fałsz` — działają też
w odmianie (`przyjmij prawdę`).

**`Nic`** to jednocześnie typ i jego jedyna wartość — pusty wynik, koniec
listy, brakująca wartość w unii (`Opcja to Coś albo Nic`).

---

## Zmienne i przypisanie

Przypisanie to słowo `to`:

```
licznik to zero
licznik to licznik plus jeden
```

Obowiązuje **zasięg blokowy**:

- pierwsze przypisanie deklaruje zmienną — widoczną od tego miejsca do
  końca bloku; użycie przed przypisaniem to błąd,
- zmienna zadeklarowana w gałęzi `jeśli`, ciele pętli albo gałęzi
  dopasowania jest lokalna dla tego bloku,
- przypisanie do zmiennej widocznej z zewnątrz to **przepisanie** tej
  samej zmiennej — zmienną potrzebną po bloku zadeklaruj przed nim:

```
wynik to zero
jeśli warunek:
    wynik to pięć      # przepisanie zewnętrznego `wynik`
suma to wynik          # OK
```

Deklarację można adnotować typem — `zwierzę (Zwierzę) to Nic` — co
[przybija typ zmiennej dokładnie](#adnotacje). Celem przypisania może też
być pole struktury: `wiek użytkownika to wiek użytkownika plus jeden`.

---

## Operatory

| operatory | znaczenie |
|---|---|
| `plus`, `minus`, `razy` | arytmetyka na `Liczbie` |
| `mniejsze od`, `większe od`, `mniejsze równe`, `większe równe` — w dowolnej odmianie (`większy od`, `mniejsza równa`) | porównania liczb (dają `Przełącznik`) |
| `równe`, `nierówne` — w dowolnej odmianie (`równy`, `nierówna`) | równość **strukturalna** — rekurencyjnie po polach, bezpieczna dla cykli |
| `tożsame` | równość **referencyjna** — ten sam obiekt (wartości proste po wartości) |
| `i`, `lub`, `nie` | logika na `Przełączniku` |

Priorytety od najsłabszego: `lub` < `i` < `nie` < porównania <
`plus`/`minus` < `razy` < unarny `minus`. Nawiasy grupują dowolne
wyrażenie:

```
suma to (dwa plus trzy) razy cztery
gotowe to nie zajęte i suma większe od dziesięć
```

**Wszystkie porównania odmieniają się** przez rodzaj i przypadek zgodnie
ze zdaniem: `głowa równa zasadzie`, `znak równy '+'`, `limit większy od
zera`, `wartość mniejsza równa dziewięciu`, `głowa nierówna dzielnikowi`.
Liczebniki po prawej stronie też mogą stać w dowolnym przypadku (`od
zera`, `od dziewiętnastu`). Równość wymaga porównywalnych typów (wspólna
głowa albo wspólna unia) — porównanie `Liczby` ze `Znakiem` to błąd typów.

**Dzielenia nie ma wśród operatorów** — to funkcje wbudowane deklarowane
w przygrywce, obie podłogowe (reszta nieujemna dla dodatniego dzielnika,
dzielenie przez zero to błąd wykonania):

```
podziel siedem przez dwa                  # → 3
weź_resztę_z_dzielenia siedmiu przez dwa  # → 1
podziel (minus siedem) przez dwa          # → -4
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
    jeśli licznik równe trzy:
        dalej          # następna iteracja
    jeśli licznik większe od pięć:
        dość           # przerwij pętlę

zwróć wyrażenie
zwróć                  # bez wartości — Nic
```

Warunek `jeśli`/`dopóki` musi być `Przełącznikiem`. Pętli `dla … w …`
nie ma — `dla` to zwykły przyimek (nagłówki funkcji, argumenty wywołań);
po kolekcjach chodzi się rekurencją albo `dopóki` z
[idiomem kursora](#zawężanie-przez-dopasowanie).

---

## Funkcje — `aby`

```
aby wysłać coś do odbiorcy przez kanał:
    ...

aby zmierzyć listę (Lista) -> Liczba:
    ...
```

- Nazwa funkcji musi zawierać **czasownik** (`wysłać`, `zapisać_w_bazie`).
- Parametr to `[przyimek] nazwa [(Typ)]` — typ jest opcjonalny
  (wywnioskuje go inferencja), a przyimek i przypadek nazwy stają się
  „gramatyczną sygnaturą" parametru.
- `-> Typ` deklaruje typ zwracany (też opcjonalny).

**Wywołanie** to czasownik i argumenty. Argument dopasowuje się do
parametru po **(przyimku, przypadku)** — argumenty z jednoznacznym
dopasowaniem trafiają na swoje miejsca niezależnie od kolejności,
pozostałe (np. wyrażenia w nawiasach, które nie mają przypadka)
pozycyjnie:

```
wyślij "raport" przez pocztę do szefa    # inna kolejność niż w sygnaturze
```

Argumentem jest pojedynczy „człon": literał, zmienna, łańcuch pól,
zagnieżdżone wywołanie. Większe wyrażenie ujmij w nawiasy:
`policz z (dwa plus trzy)`. Operatory wiążą na zewnątrz wywołania:
`zmierz listę plus jeden` znaczy `(zmierz listę) plus jeden`. **Nazwy
parametru nie powtarza się** przy wywołaniu — rolę niesie przyimek:
`powiadom odbiorcę o "nowość"`.

Konwencja form: **definiuj bezokolicznikiem, wołaj rozkaźnikiem** —
`aby dodać...`, potem `dodaj x do y`. Obie formy muszą mieć wspólny
lemat, więc uwaga na pary aspektowe: `dodaj` → `dodać` (nie `dodawać`),
`wybierz` → `wybrać`, `przyjmij` → `przyjąć`.

W ciele funkcji parametr występuje w mianowniku niezależnie od formy
w sygnaturze: `aby dodać rzecz do drugiej_rzeczy:` a w środku
`zwróć rzecz plus druga_rzecz`.

Funkcja bez żadnego `zwróć` — podobnie jak `zwróć` bez wartości — ma typ
zwracany `Nic`. Funkcja zwracająca tylko na niektórych ścieżkach dostaje
do typu zwracanego dounifikowane `Nic` (szczegóły w [systemie
typów](#funkcje-i-polimorfizm)).

---

## Funkcje wbudowane i zewnętrzne — `można`

Granica świata: deklaracja sygnatury bez ciała, dlatego **wszystkie typy
muszą być jawne**:

```
można wypisać tekst (Tekst) -> Nic
można czytać_plik ze ścieżki (Tekst) -> Rezultat o elemencie Tekst
```

Interpreter ma wbudowane implementacje dziewięciu funkcji, zadeklarowane
w przygrywce (osobny zestaw graficzny deklaruje [`gra.ć`](#grafika-i-gry--biblioteka-grać)):

| funkcja | znaczenie |
|---|---|
| `wypisać coś (Cokolwiek) -> Nic` | wypis na standardowe wyjście |
| `podzielić … przez … -> Liczba` | dzielenie podłogowe |
| `wziąć_resztę_z_dzielenia … przez … -> Liczba` | reszta z dzielenia |
| `zapisać_znakiem liczbę (Liczba) -> Znak` | punkt kodowy → znak (`chr`) |
| `zapisać_liczbą znak (Znak) -> Liczba` | znak → punkt kodowy (`ord`) |
| `czytać_plik ze ścieżki (Tekst) -> Rezultat o elemencie Tekst` | odczyt pliku |
| `zapisać_plik dla zawartości (Tekst) do ścieżki (Tekst) -> Rezultat o elemencie Liczba` | zapis pliku (Sukces = liczba bajtów) |
| `wczytać_wejście -> Tekst` | jedna linia ze standardowego wejścia, bez końcowego znaku nowej linii (jak `input` w Pythonie); EOF daje pusty tekst (≡ `Nic`) |
| `wylosować_liczbę od minimum (Liczba) do maksimum (Liczba) -> Liczba` | losowa liczba z domkniętego przedziału; pusty przedział to błąd wykonania |

Nieznana głowa typu w sygnaturze `można` (np. `Cokolwiek`, `Uchwyt`)
działa jak **niejawny parametr typu** współdzielony w obrębie sygnatury —
stąd idiom `można wypisać coś (Cokolwiek) -> Nic` dla funkcji
przyjmującej dowolną wartość.

Most `zapisać_znakiem`/`zapisać_liczbą` to jedyna droga między `Znakiem`
a `Liczbą` — Ć nie ma tablicy ASCII, a porównania porządkowe
i arytmetyka działają wyłącznie na `Liczbie`:

```
wypisz (zapisz_liczbą 'A')            # 65
wypisz (zapisz_znakiem sześćdziesiąt pięć)   # A
```

---

## Struktury — `definicja`

```
definicja Użytkownika:
    imię (Tekst)
    wiek (Liczba)
```

Nagłówek w dopełniaczu („definicja *czego*"), pola w mianowniku, typy pól
w nawiasach (obowiązkowe). **Typ pola musi być w pełni związany** — pole
to mutowalny magazyn, więc typechecker musi znać jego zawartość. Typ
generyczny w polu wiąże się na trzy sposoby:

```
definicja Kubła z elementem:
    zapas (Lista)                       # przechwyt po nazwie: element Kubła
    metka (Tekst)                       # alias — w pełni związany
definicja Worka:
    zapas (Lista o elemencie Liczba)    # konkret aplikacją nazwaną
```

Pole „luźne" (`zapas (Lista)` w strukturze bez parametru `element`) jest
**zakazane** — komunikat podpowiada obie naprawy. Dawniej takie pole było
granicą dynamiczną: typu zawartości nikt nie śledził, a błędne założenie
czytelnika wybuchało dopiero w runtime.

**Konstruktor** to po prostu nazwa typu — wielka litera wystarcza za
słowo kluczowe. Pola podaje się na dwa sposoby:

- `o polu WARTOŚĆ` — pole w **miejscowniku**, wartość to pełne wyrażenie,
- `z polem` — skrót: weź wartość z zadeklarowanej zmiennej o nazwie pola
  (pole w **narzędniku**):

```
gość to Użytkownik o imieniu "Ada" o wieku trzydzieści

imię to "Bob"
gość to Użytkownik z imieniem o wieku czterdzieści
```

Konstrukcja musi wypełnić wszystkie pola; ich kolejność jest dowolna.
Konstruktory się zagnieżdżają: `Komentarz o autorze Użytkownik o imieniu
"Ada" o treści "hej"` — pole nienależące do wewnętrznego typu wraca do
zewnętrznego.

**Dostęp do pól** to konstrukcja dopełniaczowa „pole *czego*" — obiekt
w dopełniaczu, łańcuchy dowolnej długości, także po lewej stronie `to`:

```
powitanie to imię użytkownika
miasto to nazwa adresu użytkownika sesji
wiek użytkownika to wiek użytkownika plus jeden
```

**Struktury są referencyjne.** Przypisanie i przekazanie do funkcji nie
kopiuje — mutacja pola jest widoczna wszędzie tam, gdzie obiekt jest
osiągalny. Można budować struktury cykliczne:

```
węzeł to Węzeł o głowie jeden o ogonie Nic
ogon węzła to węzeł            # cykl — legalny
```

Rozróżnienie `równe` (struktura) / `tożsame` (referencja) istnieje
właśnie dlatego.

---

## Unie — `albo` i dopasowanie `gdy … jest:`

Unię (typ wariantowy) deklaruje się przypisaniem na typach, na poziomie
modułu:

```
definicja Kota:
    imię (Tekst)

definicja Psa:
    kość (Tekst)

Zwierzę to Kot albo Pies
```

Wariantem może być struktura zdefiniowana w programie, wbudowane `Nic`
— jedyny typ zeroargumentowy (`Opcja to Coś albo Nic`) — oraz **inna
unia**. Unie tworzą więc hierarchię, a podtypowanie jest przechodnie:

```
Pies to Jamnik albo Pudel
Zwierzę to Kot albo Pies          # Jamnik ≤ Pies ≤ Zwierzę
```

Cykl w hierarchii (`A to B …`, `B to A …`) to błąd. Unie nie przyjmują
własnych parametrów typu (dziedziczą [parametry swoich
członków](#typy-parametryzowane-i-aliasy) — przez wszystkie poziomy).

**Dopasowanie** otwiera `gdy` i polski orzecznik — „*gdy* X *jest*
(czym?) *Kotem*". Gałęzie w **narzędniku**, dekonstrukcja pól przez
`z polem`:

```
gdy zwierzę jest:
    Kotem z imieniem:
        wypisz imię
    Psem z kością:
        wypisz kość
```

Zasady:

- **Orzecznik zgadza się liczbą z podmiotem**: `gdy lista jest:`, ale
  `gdy wyniki są:` — pomyłka daje błąd z podpowiedzią właściwej formy.
  Podmiot stoi w mianowniku.
- Podmiotem może być **dowolne wyrażenie**, nie tylko zmienna:
  `gdy szukaj po pięciu jest:` dopasowuje wynik wywołania,
  `gdy zawartość pudełka jest:` — wartość pola.
- Gałęzie muszą **rozłącznie pokryć wszystkie** warianty unii; `Nic`
  obsługuje gałąź `Niczym:`. Alternatywnie ostatnią gałęzią może być
  `inaczej:` — pokrywa pozostałe warianty (bez wiązania pól).
- Gałęzią może być też **pod-unia** — `Psem:` łapie i Jamnika, i Pudla
  (także w runtime); wolno mieszać poziomy (`Kotem`/`Jamnikiem`/`Pudlem`
  na `Zwierzęciu`), ale gałęzie nakładające się (`Psem:` obok
  `Jamnikiem:`) to błąd. Pod-unia nie wiąże pól — całość bierze się
  przez `jako`.
- Wiązać można podzbiór pól (również żadne: `Kotem:`); pola związane są
  lokalne dla gałęzi. Przed słowem zaczynającym się od „z" przyimek
  przybiera formę `ze`: `Krokiem ze znakiem:`.
- `jako nazwa` wiąże **całą** dopasowaną wartość pod świeżą nazwą
  (w mianowniku), już z zawężonym typem — można łączyć z wiązaniem pól:

```
gdy rezultat jest:
    Sukcesem jako paczka z wartością:
        wypisz wartość
        wypisz paczka
    Błędem jako kłopot:
        wypisz (opis kłopotu)
```

Wewnątrz gałęzi podmiot jest **zawężony** do wariantu — `imię zwierzęcia`
działa w gałęzi `Kotem:` bez dodatkowych ceregieli. Zapis do podmiotu
w gałęzi trafia do zmiennej **zewnętrznej** i jest widoczny po bloku —
to podstawa idiomu kursora przy chodzeniu po listach:

```
dopóki prawda:
    gdy reszta jest:
        Niczym:
            dość
        Węzłem z głową z ogonem:
            wypisz głowa
            reszta to ogon        # przesuwa kursor — zapis na zewnątrz
```

Uwaga: gałąź, która **przepisuje podmiot** (jak wyżej `reszta to ogon`),
nie widzi go już wąsko — po zapisie nazwa może wskazywać dowolny wariant,
a pętla wykonuje nawet wcześniejsze odczyty PO zapisie, więc o utracie
zawężenia decyduje samo istnienie zapisu w gałęzi, nie jego miejsce.
Wiązania `z głową z ogonem` i alias `jako` to **migawki wartości**
z wejścia do gałęzi — zapis ich nie psuje (dlatego kursor czyta przez
nie). Kto potrzebuje wąskiego odczytu po zapisie, zawęża ponownie
dopasowaniem `jest:`.

Semantyka typowa dopasowania (wnioskowanie unii podmiotu, zawężanie,
niejednoznaczność) — w [systemie typów](#zawężanie-przez-dopasowanie).

---

## Typy parametryzowane i aliasy

Struktura może mieć parametry typu — deklarowane jak parametry funkcji
(`[przyimek] nazwa`), używane potem jako typy pól:

```
definicja Ogniwa z elementem:
    głowa (element)
    ogon (Lista)

definicja Mapy z klucza na wartość:
    wpisy (Lista)

definicja Drzewa dla rzeczy:
    wartość (rzecz)
    lewy_syn (Drzewo dla rzeczy)
```

Parametrów zwykle **nie podaje się przy użyciu** — konkretyzują się przez
inferencję (`Ogniwo o głowie pięć o ogonie Nic` to `Ogniwo[Liczba]`).
Unia, której członkiem jest struktura parametryzowana, dziedziczy jej
parametry po nazwach (`Lista to Ogniwo albo Nic` ma niejawny parametr
`element`).

Gdy parametry chcesz podać jawnie (w adnotacji albo aliasie), są dwie
formy:

- **nazwana** — `o NAZWIE Typ`, nazwa parametru w miejscowniku; działa
  na strukturach i uniach: `Lista o elemencie Znak`,
  `-> Rezultat o elemencie Tekst`,
- **przyimkowa, jak w definicji** — tylko na strukturach:
  `(Stos z elementem)`, `(Mapa z klucza na wartość)`, z zagnieżdżeniem
  w nawiasach `(Lista z (Mapa z klucza na wartość))`. Na unii forma
  przyimkowa/pozycyjna jest niedozwolona — unia przyjmuje wyłącznie
  aplikację nazwaną.

**Alias typu** to przypisanie na typach bez `albo`; po prawej stronie
aliasu aplikacja może być wyłącznie nazwana:

```
Tekst to Lista o elemencie Znak
Numer to Liczba
Ciąg to Łańcuszek o wartości Tekst o elemencie Liczba
```

Aliasy są przezroczyste (w pełni zamienne z rozwinięciem) i mogą się
łańcuchować; cykl aliasów to błąd.

Adnotacje typów pojawiają się w czterech miejscach: polach struktur
`nazwa (Typ)`, parametrach `nazwa (Typ)`, typie zwracanym `-> Typ`
i sufiksie wyrażenia `wyrażenie (Typ)`. Sufiks wiąże się z pojedynczym
członem tuż przed nim — szersze otypowanie wymaga nawiasów:
`(weź od y) (Tekst)`.

---

## Funkcje wyższego rzędu

Funkcję przekazuje się przez jej **rzeczownik odczasownikowy**:
`dodawanie` to referencja do funkcji `dodawać`, `przekraczanie_progu` —
do `przekraczać_próg`. Referencje wskazują funkcje zdefiniowane
w programie (także wbudowane, np. `z wypisaniem`); domknięcia powstają
wyłącznie przez [bejcowanie `zwiąż`](#bejcowanie--częściowa-aplikacja-zwiąż)
— nie ma przechwytywania zmiennych z otoczenia. Zmienna o tym samym
lemacie przesłania referencję.

Wartość funkcyjną wywołuje wbudowany czasownik `zastosuj` — argumenty
pozycyjnie, każdy przez `z` + narzędnik:

```
aby złożyć listę (Lista) z operacją z akumulatorem:      # fold
    gdy lista jest:
        Ogniwem z głową z ogonem:
            reszta to złóż ogon z operacją z akumulatorem
            zwróć zastosuj operację z głową z resztą
        Niczym:
            zwróć akumulator

suma to złóż liczby z dodawaniem z zero                  # referencja gerundialna
```

Zasady:

- **`zastosować` jest zarezerwowane** — własnej funkcji o tym lemacie
  nie można zadeklarować (`zastosować_filtr` — można).
- Typy strzałkowe są w pełni inferowane (`operacja : (Liczba, Liczba) →
  Liczba`); nie ma składni na strzałkę w `można` ani w polach struktur.
- **Tryb przypuszczający komponuje się**: `zastosowałbyś operację
  z wartością?` to zastosowanie z obsługą błędu.
- W referencji do funkcji wielosegmentowej podkreślnik jest obowiązkowy:
  `z polubieniem_wpisu`, nie `z polubieniem wpisu` (dwa słowa mogą się
  sparsować jako odczyt pola).
- Zagnieżdżony goły `zastosuj` zachłannie zjada kolejne `z …` — w wartości
  pola i w argumentach używaj nawiasów: `bierz jeden z (zastosuj operację
  z dwa)`.

Gotowe fold/mapa/filtr/indeksowanie są w przygrywce (`złożyć`,
`przekształcać`, `przesiewać`, `wskazać`); użycie: `test/kolekcje.ć`.

---

## Bejcowanie — częściowa aplikacja `zwiąż`

Wbudowany czasownik `zwiąż` zamraża **pierwszych k argumentów** funkcji
(pozycyjnie) i zwraca wartość funkcyjną oczekującą pozostałych:

```
aby dodać liczbę do innej_liczby:
    zwróć liczba plus inna_liczba

aby działać:
    dodanie_dwóch to zwiąż dodanie z dwa
    wypisz (zastosuj dodanie_dwóch z trzy)      # 5
```

Domknięcie jest zwykłą wartością funkcyjną — można je przekazać do
funkcji, zastosować przez `zastosuj`, dowiązać kolejnym `zwiąż` (argumenty
się doklejają) i wypisać. Typowy duet z przygrywkowym filtrem:

```
warunek to zwiąż stwierdzenie_podzielności z dzielnikiem
lista to przesiewaj listę przez warunek
```

Zasady:

- Odbiorca i argumenty jak w `zastosuj`: odbiorca to primary (referencja
  gerundialna, zmienna, nawiasy), każdy argument przez `z` + narzędnik.
- **Typ odbiorcy musi być znaną strzałką** — referencja gerundialna albo
  zmienna o już ustalonym typie funkcyjnym. Wiązanie na nieustalonej
  wartości (np. generycznym parametrze) to błąd typów — Ć konsekwentnie
  wymaga znanej arności.
- Związanie **wszystkich** argumentów daje bezargumentowy odkładany
  obliczeniowo „thunk" (`zastosuj F` bez argumentów); związanie **zbyt
  wielu** to błąd typów.
- Wiązać można też funkcje wbudowane: `zwiąż podzielenie z sto`.
- `związać` jest zarezerwowane jak `zastosować` (`związać_snopek` — można).
- Bejcowanie nie zawodzi — tryb przypuszczający (`związałbyś …?`) jest
  błędem.

---

## Obsługa błędów — `Rezultat` i tryb przypuszczający

Odpowiednik operatora `?` z Rusta. Konstrukcja wymaga unii dokładnie tej
postaci (przygrywka deklaruje ją gotową):

```
definicja Sukcesu z elementem:
    wartość (element)

definicja Błędu:
    opis (Tekst)

Rezultat to Sukces albo Błąd
```

Czasownik w **trybie przypuszczającym** otwiera wywołanie, `?` po
argumentach je domyka:

```
napis to wybrałbyś zero z części?
```

znaczy dokładnie:

```
tymczasowy to wybierz zero z części
gdy tymczasowy jest:
    Sukcesem z wartością:
        napis to wartość
    Błędem z opisem:
        zwróć Błąd o opisie opis
```

Sukces jest **odpakowywany** do swojej wartości, Błąd **propagowany
zwrotem** z funkcji otaczającej — jej typ zwracany rozszerza się o `Błąd`.
Oba znaczniki są obowiązkowe: tryb przypuszczający bez `?` i `?` bez
trybu to błędy. Wołana funkcja musi zwracać `Rezultat`. Konstrukcja
działa tylko w ciele funkcji. Ponieważ `?` domyka wywołanie,
zagnieżdżenie nie potrzebuje nawiasów:

```
zapisz wydobyłbyś wartość z listy? do bazy
```

Uwaga na pary aspektowe także tutaj: `wybrałbyś` → lemat `wybrać`,
`zawiódłbyś` → `zawieść`.

---

## Przygrywka — biblioteka standardowa

`biblioteki/przygrywka.ć` to standardowa biblioteka dołączana przez
`uwzględnij`. Najważniejszy skutek: **`Tekst` przestaje być czymkolwiek
wbudowanym i staje się listą znaków** — literały tekstowe to łańcuchy
ogniw, każda funkcja listowa działa na tekstach, a pusty tekst ≡ `Nic`.

Typy:

```
definicja Ogniwa z elementem:
    głowa (element)
    ogon (Lista)

Lista to Ogniwo albo Nic
Tekst to Lista o elemencie Znak
Rezultat to Sukces albo Błąd          # Sukces z elementem `wartość`, Błąd z `opis`
```

Funkcje (wszystkie generyczne po elemencie, działają na `Tekście` jak na
każdej innej liście):

| funkcja | znaczenie |
|---|---|
| `zmierzyć listę -> Liczba` | długość |
| `skleić listę z resztą -> Lista` | konkatenacja |
| `odwrócić listę -> Lista` | odwrócenie |
| `wyłuskać tekst -> Znak` | pierwszy znak (dla pustego: `'?'`) |
| `złożyć listę z operacją z akumulatorem` | fold prawostronny |
| `przekształcać listę z operacją` | mapa |
| `przesiewać listę przez warunek` | filtr |
| `wskazać pozycję na liście` | indeksowanie od **jedynki**, zwraca `Rezultat` |
| `pokazać liczbę -> Tekst` | liczba jako tekst dziesiętny (z minusem) |
| `przedstawić cyfrę -> Znak`, `rozwijać liczbę -> Tekst` | cegiełki `pokazać` |
| `odczytać_liczbę z napisu -> Rezultat o elemencie Liczba` | tekst dziesiętny → liczba (odwrotność `pokazać`, z minusem); zły znak / pusty napis / sam minus dają `Błąd` z opisem |
| `odcyfrować znak -> Rezultat o elemencie Liczba` | wartość cyfry `'0'`–`'9'` (odwrotność `przedstawić`) |

Plus deklaracje wbudowanych: `podzielić`, `wziąć_resztę_z_dzielenia`,
`zapisać_znakiem`, `zapisać_liczbą`, `czytać_plik`, `zapisać_plik`,
`wczytać_wejście`, `wylosować_liczbę`
(tabela w sekcji [`można`](#funkcje-wbudowane-i-zewnętrzne--można)).

Typowy program interaktywny: `wczytaj_wejście` + `odczytaj_liczbę`
z dopasowaniem `Rezultatu` — zobacz `test/sito_z_wejścia.ć`.

---

## Grafika i gry — biblioteka `gra.ć`

`uwzględnij gra.ć` (dołącza też przygrywkę) daje builtiny graficzne
oparte na pygame, w trybie natychmiastowym: program otwiera okno, rysuje
w pętli i odpytuje wejście. Wymagana instalacja `pip3 install pygame-ce`
(właśnie **pygame-ce**, nie klasyczny pygame — ten nie ma wheeli dla
świeżych Pythonów); pygame jest importowany leniwie, więc bez niego
interpreter i wszystkie programy niegraficzne działają normalnie.

Szkielet każdej gry:

```
uwzględnij gra.ć

aby działać:
    otwórz_okno o sześciuset o (czterysta pięćdziesiąt) z "Tytuł"
    dopóki pokaż_klatkę:
        <logika i rysowanie>
```

`pokaż_klatkę` robi całą obsługę klatki naraz: wyświetla narysowane,
ogranicza tempo do **30 klatek na sekundę**, zbiera wydarzenia i czyści
ekran pod następną klatkę; po zamknięciu okna krzyżykiem zwraca `fałsz`
i pętla naturalnie się kończy. Współrzędne w pikselach: `od lewej`
rośnie w prawo, `od góry` w dół.

| funkcja | znaczenie |
|---|---|
| `otworzyć_okno o szerokości o wysokości z tytułem (Tekst) -> Nic` | otwiera okno gry |
| `pokazać_klatkę -> Przełącznik` | klatka: flip + 30 fps + wydarzenia + czyszczenie; `fałsz` po zamknięciu |
| `narysować_koło od lewej od góry o promieniu w barwie -> Nic` | koło (od środka) |
| `narysować_prostokąt od lewej od góry o szerokości o wysokości w barwie -> Nic` | prostokąt (od lewego górnego rogu) |
| `narysować_napis treść (Tekst) od lewej od góry o rozmiarze w barwie -> Nic` | tekst na ekranie |
| `narysować_duszka ze ścieżki (Tekst) od lewej od góry -> Nic` | sprite z pliku (PNG z przezroczystością; buforowany) |
| `dobrać_barwę nazwę (Tekst) -> Barwa` | barwa po polskiej nazwie albo `"#RRGGBB"` |
| `zbadać_klawisz nazwę (Tekst) -> Przełącznik` | czy klawisz jest wciśnięty teraz (ruch ciągły) |
| `pobrać_wydarzenia -> Lista o elemencie Wydarzenie` | wydarzenia od ostatniej klatki (akcje jednorazowe) |

Typy z `gra.ć`: struktura `Barwa` (`czerwień`/`zieleń`/`błękit`, 0–255;
gotowe barwy przez `dobierz_barwę "zieleń"` — czerń, biel, szarość,
czerwień, zieleń, błękit, żółć, pomarańcz, fiolet, róż, brąz) oraz unia
`Wydarzenie to Naciśnięcie albo Kliknięcie albo Ruch` — obsługiwana
zwykłym dopasowaniem `jest:`. Nazwy klawiszy: `"lewo"`, `"prawo"`,
`"góra"`, `"dół"`, `"spacja"`, `"enter"`, `"wyjście"`, litery i cyfry.

Kompletna gra przykładowa: **`manual_test/wąż.ć`** (snake — siatka,
sterowanie strzałkami, wynik, koniec gry). Interpreter jest wolny —
budżet na klatkę starcza na proste gry (wąż, pong), nie na systemy
cząsteczkowe. Testy graficzne działają bezokienkowo przez
`SDL_VIDEODRIVER=dummy` (runner ustawia to sam).

---

## Wiele plików — `uwzględnij`

Program można rozbić na pliki — dyrektywa `uwzględnij` wstawia zawartość
wskazanego pliku w miejscu dyrektywy (deklaracje w Ć są niezależne od
kolejności, więc to wystarcza):

```
uwzględnij przygrywka.ć
uwzględnij pod/napisy.ć
```

- Ścieżkę interpreter rozstrzyga **dwuetapowo**: najpierw **względem
  pliku, w którym stoi dyrektywa**, a gdy tam jej nie ma — w folderze
  `biblioteki/` (rozstrzyganym względem lokalizacji interpretera). Dzięki
  temu biblioteki standardowe (`przygrywka.ć`, `operacje_tekstowe.ć`) są
  widoczne z dowolnego katalogu, a lokalny plik o tej samej nazwie ma
  pierwszeństwo.
- **Każdy plik wchodzi najwyżej raz** — gdy dwa pliki uwzględniają tę
  samą bibliotekę, jej deklaracje się nie powielają; cykle są bezpieczne.
- Dyrektywa musi zaczynać się w kolumnie zerowej i jest rozpoznawana
  literalnie (bez odmiany).
- Błędy wskazują **plik źródłowy i oryginalny numer linii**, także przy
  konfliktach między plikami.

---

## System typów

Ć jest typowane statycznie, z **pełną inferencją z podtypowaniem**
(rodzina MLsub/simple-sub) na **nominalnej** siatce typów. W praktyce:
typów prawie nie piszesz, a mimo to każdy program jest w całości
sprawdzony przed wykonaniem. Cena: kilka reguł, które trzeba rozumieć,
bo komunikaty o błędach odwołują się wprost do nich.

### Świat typów

- wbudowane: `Liczba`, `Znak`, `Przełącznik`, `Nic`,
- struktury użytkownika (`definicja`), także parametryzowane,
- unie zadeklarowane `albo` (członkami struktury i `Nic`),
- aliasy — przezroczyste skróty, nie nowe typy,
- typy funkcyjne (strzałki) — tylko inferowane, bez składni,
- niejawne parametry typu — małe/nieznane nazwy w sygnaturach
  (`element`, `rzecz`, `Cokolwiek`).

### Relacja podtypowania — kompletna definicja

Podtypowanie jest **wyłącznie nominalne** i wyczerpuje się w dwóch
regułach:

1. każdy typ jest podtypem samego siebie,
2. typ (struktura albo unia) jest podtypem unii, której jest
   **zadeklarowanym** członkiem — przechodnio przez poziomy hierarchii:
   przy `Pies to Jamnik albo Pudel` i `Zwierzę to Kot albo Pies` mamy
   `Jamnik ≤ Pies ≤ Zwierzę`, więc też `Jamnik ≤ Zwierzę`.

Nic więcej. Nie ma podtypowania strukturalnego (dwie struktury o tych
samych polach to obce typy), nie ma relacji między uniami spoza
zadeklarowanej hierarchii (nawet gdy jedna wylicza warianty drugiej),
unia nigdy nie jest podtypem swojego członka, nie ma typu „wszystko"
ani „nic-nie-ma" (`Nic` to zwykła wartość, nie dno kraty), nie ma
niejawnych konwersji.

Dwie konsekwencje wariancji:

- **Pola struktur są inwariantne** — bo są mutowalne. Listy są
  jednorodne: `Ogniwo o głowie pięć o ogonie (Ogniwo o głowie 'a'
  o ogonie Nic)` to błąd („niejawny argument 'element' nie zgadza się
  między wystąpieniami"). Upcast kontenera nie jest przy tym zakazany —
  przepływ wartości **skleja sloty elementów**: gdy kocie stado dostanie
  zwierzęcy alias (albo trafi do funkcji od `Listy o elemencie
  Zwierzę`), element poszerza się we WSZYSTKICH widokach naraz, więc
  dopisanie Psa przez alias uczciwie zmusza także „koci" uchwyt do
  gałęzi na Psa. Nie ma dwóch prawd o jednej liście.
- **Wartości funkcyjne**: argumenty kontrawariantnie, wynik
  kowariantnie. Tam, gdzie oczekiwana jest funkcja z `Kota`, pasuje
  funkcja ze `Zwierzęcia` (przyjmuje więcej); tam, gdzie oczekiwany
  wynik `Zwierzę`, pasuje funkcja zwracająca `Kota`.

### Jak działa wnioskowanie

Dla każdej zmiennej, parametru, pola i wyniku typechecker zbiera dwa
rodzaje informacji:

- **fakty** — co do niej rzeczywiście wpływa („w linii 2 przypisano
  Kota"),
- **wymagania** — czego żądają jej użycia („w linii 7 przekazano ją
  funkcji oczekującej Zwierzęcia").

Typ to **podsumowanie faktów**: pojedyncza głowa, a gdy faktów jest
więcej — najmniejsza zadeklarowana unia, która pokrywa je wszystkie
(mierzona liczbą liści hierarchii, więc wybiera najciaśniejszy poziom:
`Jamnik ⊔ Pudel = Pies`, ale `Jamnik ⊔ Kot = Zwierzę`).
Wymagania niczego nie „ustalają" — tylko filtrują i sprawdzają. Stąd
cztery zachowania, które warto znać:

**Zmienna może zmieniać wariant, jeśli łączy je unia.** Typ zmiennej to
suma wszystkich przypisań:

```
pupil to Kot o imieniu "Mruczek"
pupil to Pies o kości "szynka"      # OK: pupil ma typ Zwierzę
rzecz to jeden
rzecz to 'z'                        # BŁĄD: Liczby i Znaku nie łączy unia
```

Konflikt jest zgłaszany **natychmiast**, w linii przypisania-sprawcy,
z wypisem poszlak (wszystkich faktów z liniami) — i z gotowym szablonem:
„jeśli to zamierzone, zadeklaruj unię: `Rzecz to … albo …`". Gdy fakty
pokrywa **więcej niż jedna** minimalna unia, to też błąd (remis) —
rozstrzyga adnotacja.

**Wymagania nie poszerzają.** Wartość znana jako `Kot` przekazana
funkcji od `Zwierząt` **pozostaje Kotem** — dalej można czytać jej
`imię` bez zawężania. Poszerza tylko rzeczywisty fakt (przypisanie
innego wariantu).

**Wymagania się przecinają.** Parametr użyty w dwóch funkcjach —
jednej od `Domownika` (`Kot albo Pies`), drugiej od `Futrzaka`
(`Kot albo Chomik`) — może być wyłącznie `Kotem`; wywołanie z Kotem
przechodzi, z Psem nie (test `test/przecięcie.ć`).

**Wynik nie zależy od kolejności.** Przestawianie linijek, pól
konstrukcji ani kolejności deklaracji nie zmienia wywnioskowanych typów
— fakty i wymagania tylko się akumulują.

W drugą stronę działa dokładność: unia **nie mieści się** w miejscu
oczekującym konkretnego wariantu. `Zwierzę` przekazane tam, gdzie
oczekiwany jest dokładnie `Kot`, to błąd z podpowiedzią: „w runtime może
być: Pies; zawęź dopasowaniem `jest:` przed przekazaniem".

### Adnotacje

Trzy narzędzia o różnej semantyce:

- **Adnotowana deklaracja** `pupil (Zwierzę) to Kot o imieniu "M"` —
  **przybija typ zmiennej dokładnie do adnotacji**. Wartość musi się
  w niej mieścić, ale odczyty widzą `Zwierzę`, nie `Kota` — to sposób na
  świadome poszerzenie od pierwszej linii (np. `zwierzę (Zwierzę) to
  Nic`, zanim cokolwiek tam trafi).
- **Sufiks na wyrażeniu** `wyrażenie (Typ)` — czysty **upcast**:
  wyrażenie musi się mieścić w typie, wynik ma typ z adnotacji.
  Rzutować można tylko w górę (do nadtypu).
- **Rzutowania w dół nie ma.** Jedyna droga od unii do wariantu to
  dopasowanie `jest:` — bezpieczne, bo sprawdzane na wyczerpanie.

### Zawężanie przez dopasowanie

`gdy X jest:` to jednocześnie kontrola wariantów i zawężanie typów:

- Gałęzie muszą **rozłącznie pokrywać liście jednej zadeklarowanej
  unii** — wprost, pod-uniami albo mieszanką poziomów (brak gałęzi,
  gałąź spoza unii, powtórka i nakładające się gałęzie to osobne,
  precyzyjne błędy). Z `inaczej:` wystarczy podzbiór wariantów.
- W gałęzi `Kotem:` podmiot **jest Kotem** — pola wariantu dostępne
  wprost, przez wiązania `z polem` i przez łańcuchy na podmiocie.
  Gałąź `inaczej:` **nie zawęża** (nie ma „negatywnego" wnioskowania).
- Zapis do podmiotu w gałęzi idzie do zmiennej **zewnętrznej** — jej typ
  uczciwie poszerza się o zapisany wariant, a odczyty w gałęzi dalej
  widzą typ zawężony. Dzięki temu działa idiom kursora.
- Pole wspólne wszystkim wariantom unii (przechodnio, przez całą
  hierarchię) można czytać **i pisać bez zawężania** — `owoc stanu`
  działa, czy stan jest Pełzaniem, czy Porażką; „coś, co ma segmenty"
  wnioskuje się z samego odczytu, jak w polszczyźnie. Warunek: typ pola
  musi być **identyczny** we wszystkich wariantach (parametry typowe
  łączą się w jeden slot unii po nazwie — pole `(Lista o elemencie
  element)` u obu wariantów jest wspólne, u jednego `element`
  a u drugiego `sztuka` już nie). Pole obecne tylko w niektórych
  wariantach wymaga `jest:`.
- Dopasowanie na wartości o nieznanym typie (np. nieadnotowanym
  parametrze) **wnioskuje** jego unię do sygnatury funkcji. Gdy gałęzie
  pasują do kilku unii, decyzja jest **odraczana**: kandydaci trzymani są
  jako alternatywy, a kolejne fakty i użycia je zawężają. Jeśli do końca
  zostaje więcej niż jeden — błąd „typ pasuje do wielu możliwości …
  dodaj adnotację typu" (z podpowiedzią, który wariant-dyskryminator
  rozstrzygnie).

### Funkcje i polimorfizm

- Sygnatura bez adnotacji jest tak ogólna, jak pozwala ciało — wolne
  typy parametrów i wyniku działają jak **niejawne parametry typu**.
  Tak samo małe nieznane nazwy w adnotacjach (`element`, `rzecz`).
- Funkcje są **polimorficzne między wywołaniami**: każde wywołanie
  dostaje świeży egzemplarz sygnatury, więc `przetwarzaj dla jeden` może
  dać `Liczbę`, a `przetwarzaj dla 'z'` — `Znak`, bez konfliktu.
- **Rekursja jest monomorficzna**: wywołania rekurencyjne (także we
  wzajemnie rekurencyjnej grupie funkcji) współdzielą jedną sygnaturę.
  Polimorfizm obowiązuje dopiero „z zewnątrz" grupy. Referencje w przód
  i wzajemna rekursja działają bez żadnych deklaracji wyprzedzających.
- Typ zwracany to suma zwrotów ze wszystkich gałęzi (znów: najmniejsza
  pokrywająca unia). Funkcja, w której jakaś ścieżka nie kończy się
  `zwróć`, dostaje dounifikowane `Nic` — jeśli reszta zwrotów się z tym
  nie łączy, błąd podpowiada: „dopisz `zwróć` … albo zadeklaruj unię
  z Nic".

### Punkt wejścia i konkretność

Wymóg pełnej konkretności typów obowiązuje **tylko w `działać`** —
odpowiednik „type annotations needed" pojawia się, gdy jakiejś zmiennej
punktu wejścia nie da się ugruntować (np. wynik externa, którego nikt
nie użył strukturalnie). Funkcje pomocnicze mogą pozostać dowolnie
polimorficzne. Wyjątek praktyczny: wolny parametr unii uchodzi —
`pusta (Lista) to Nic` typuje się, mimo że elementu pustej listy nikt
nie zna (skonkretyzuje się przez użycie).

### Błędy typów

Komunikaty niosą pełny ślad wnioskowania:

- **poszlaki** — każda granica pamięta linię i kontekst powstania
  („linia 2: przypisanie do 'rzecz'", „argument 2 wywołania 'dodaj'");
  przy konflikcie wypisywane są poszlaki obu stron: „zdecyduj, która
  poszlaka jest błędna",
- **droga wartości** — łańcuch, którym wartość dopłynęła do pękającego
  miejsca,
- **podpowiedzi** — szablon brakującej unii, „czy chodziło o …?" przy
  literówkach w polach i typach, forma poprawnego orzecznika przy
  `jest`/`są`, wskazanie wariantów-dyskryminatorów przy
  niejednoznaczności,
- kontekst „(podczas typowania linii N, w funkcji 'f')" i tłumaczenie
  numerów linii na oryginalne pliki przy `uwzględnij`.

---

## Pułapki, o których warto wiedzieć

- **Wspólny lemat definicji i wywołania** — pary aspektowe mylą:
  `dodaj` → `dodać` (nie `dodawać`), `wziąłbyś` → `wziąć` (nie `brać`).
  Definiuj tym czasownikiem, którego formy faktycznie wołasz.
- **Nazwa parametru nie może być przyimkiem** (`a`, `u`, `w`, `z`, `o`…)
  — zostanie zjedzona jako przyimek.
- **Niejednoznaczność morfologiczna nazw pól** — np. `posty` czyta się
  i jako `post`, i jako `posta`; interpreter to zgłosi, wtedy wybierz
  inną nazwę (np. `wpisy`).
- **Każde słowo musi istnieć w SGJP** — nazwa spoza słownika
  (np. `arność`) nie odmienia się i psuje program w zaskakujących
  miejscach. Sprawdź słowo przed użyciem (`redis-cli EXISTS
  sgjp:f:słowo`) i wybierz synonim (np. `krotność`).
- **Nazwa zmiennej nie może być liczebnikiem ani zaimkiem liczebnym** —
  `ile`, `dwa`, `szereg` itp. czytają się jako liczby; interpreter
  podpowie synonim (`spis`, `wykaz`).
- **Nie nazywaj kolekcji liczbą mnogą nazwy będącej już w zasięgu** —
  `ogniwa` to także dopełniacz lp od `ogniwo`, więc lista `ogniwa` obok
  parametru `ogniwo` skleja się z nim przez odczyt dopełniaczowy. Daj
  kolekcji inną głowę rzeczownikową (`zbiór`, `spis`).
- **Rzeczowniki odczasownikowe są pełnoprawnymi rzeczownikami** —
  `polubienie` ma własny lemat; pole `polubienia` nie koliduje z funkcją
  `polubić`. Za to w referencji gerundialnej do funkcji wielosegmentowej
  podkreślnik jest obowiązkowy (`z polubieniem_wpisu`).
- **Typ pola musi być w pełni związany** — `zapas (Lista)` przechodzi
  tylko, gdy struktura ma parametr `element` (wiązanie po nazwie);
  inaczej podaj konkret: `zapas (Lista o elemencie Liczba)`.
- **Pusty tekst to `Nic`** — dopasowanie tekstu gałęzią `Niczym:` łapie
  `""`; `"" równe Nic` daje `prawdę`.
- **Indeksowanie list zaczyna się od jedynki** (`wskaż jeden na liście`).

---

## Przykłady

Katalog `test/` to żywa dokumentacja — każdy plik `*.ć` uruchamia się
obecnym interpreterem, a `*.wynik` pokazuje jego wyjście:

| plik | co pokazuje |
|---|---|
| `wypisanie.ć`, `arytmetyka.ć`, `porównania.ć`, `logika.ć`, `dzielenie.ć` | podstawy: wypis, operatory |
| `funkcje.ć`, `złączenie_parametrów.ć` | funkcje, argumenty przyimkowe |
| `warunki.ć`, `pętla.ć`, `stop_dalej.ć`, `przypisania.ć` | sterowanie, przypisania |
| `struktury.ć`, `unie.ć`, `dopasowanie.ć`, `jako.ć` | struktury, unie, dopasowanie |
| `podmiot.ć`, `podmiot_wyrażenie.ć`, `przepisanie_podmiotu.ć`, `kursor.ć` | dopasowanie na wyrażeniu, zapis do podmiotu, idiom kursora |
| `zawężenie.ć`, `przecięcie.ć`, `pierwszeństwo_unii.ć`, `dysjunkcja.ć`, `ujednoznacznienie.ć` | system typów w akcji |
| `hierarchia.ć` | zagnieżdżone unie: podtypowanie przechodnie, gałąź-unia w dopasowaniu |
| `adnotowana_deklaracja.ć`, `adnotowane_przepisanie.ć`, `aliasy.ć` | adnotacje i aliasy |
| `tożsamość.ć`, `cykl.ć` | `równe` vs `tożsame`, struktury cykliczne |
| `tekst_lista.ć`, `znak.ć`, `znak_liczba.ć`, `łańcuchy.ć`, `dna.ć` | teksty, znaki, most Znak↔Liczba |
| `formy_gramatyczne.ć` | odmiany liczebników i porównań (`zera`, `większa od`, `nierówny`) |
| `kolekcje.ć`, `mapowanie.ć`, `aplikacja.ć` | funkcje wyższego rzędu |
| `bejcowanie.ć`, `domknięcia.ć`, `sito_bejcowane.ć` | częściowa aplikacja `zwiąż`, thunki, domknięcia w filtrze |
| `rezultat.ć`, `pliki.ć` | `Rezultat`, `?`, operacje na plikach |
| `wczytanie_wejścia.ć`, `odczytanie_liczby.ć`, `sito_z_wejścia.ć` | standardowe wejście, parsowanie liczb z tekstu |
| `wylosowanie.ć` | losowość |
| `grafika.ć` | builtiny graficzne (bezokienkowo) |
| `argumenty.ć`, `argumenty_puste.ć` | argumenty wywołania programu (`działać dla argumentów`) |
| `http.ć`, `brainfuck.ć`, `brainfuck_mutowalny.ć` | większe programy (parser HTTP, interpreter brainfucka) |

Większe programy przykładowe leżą w `manual_test/` (nie są uruchamiane
automatycznie): gra wąż na pygame (`wąż.ć`), backend aplikacji
instagramopodobnej (`instagram.ć`), parser JSON-a (`json.ć`), parser
wyrażeń samego Ć (`wyrażenia.ć`), drzewa AVL (`parametryzowane.ć` +
`użyj_drzewa.ć`), analizator morfologiczny
(`analizator_morfologiczny.ć`), sito Eratostenesa w dwóch stylach
(`sito_eratostenesa.ć`, `sito_eratostenesa_bejcowane.ć`).

---

## Struktura repozytorium

```
gćć-python/        interpreter (lexer → morfologia → parser → typechecker → executor) + testy pytest
biblioteki/        biblioteki standardowe (przygrywka.ć, gra.ć, operacje_tekstowe.ć) — fallback dla `uwzględnij`
test/              testy end-to-end języka (pary *.ć / *.wynik)
manual_test/       większe programy przykładowe
vscode-ć/          wtyczka VS Code (kolorowanie składni)
sgjp.tab           słownik SGJP (niewersjonowany, do pobrania z sgjp.pl)
make_subset.py     generator podzbioru słownika do testów
```
