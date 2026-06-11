# Język Ć

Ć to język programowania w którym kod pisze się po polsku — z polską odmianą,
polskimi przyimkami, polskimi liczebnikami słownymi i polską składnią zdań.
Słowa kluczowe i nazwy są fleksyjne: `użytkownik`, `użytkownika`, `użytkownikiem`
i `użytkowników` to ten sam identyfikator, a parser dobiera odpowiednią formę
do kontekstu.

Repozytorium zawiera implementację referencyjną w Pythonie (`gćć-python/`).
Obecnie zaimplementowane są: lekser, analiza morfologiczna (oparta o słownik
SGJP), preprocesor tokenów, parser strukturalny i parser fraz. Programy
parsują się w pełni do gotowego AST — runtime jeszcze nie istnieje, ale
gramatyka jest ostateczna.

---

## Spis treści

1. [Uruchamianie](#uruchamianie)
2. [Struktura pliku źródłowego](#struktura-pliku-źródłowego)
3. [Lekser](#lekser)
4. [Liczebniki słowne](#liczebniki-słowne)
5. [Operatory leksykalne (preprocesor)](#operatory-leksykalne-preprocesor)
6. [Identyfikatory](#identyfikatory)
7. [Definicje funkcji (`aby`)](#definicje-funkcji-aby)
8. [Funkcje zewnętrzne (`można`)](#funkcje-zewnętrzne-można)
9. [Definicje typów (`definicja`)](#definicje-typów-definicja)
10. [Typy wariantowe (`albo`, `czym jest`)](#typy-wariantowe-albo-czym-jest)
11. [Struktury sterujące](#struktury-sterujące)
12. [Przypisanie (`to`)](#przypisanie-to)
13. [Wyrażenia](#wyrażenia)
14. [Wywołania funkcji](#wywołania-funkcji)
15. [Łańcuchy dostępu do pól (getter chain)](#łańcuchy-dostępu-do-pól-getter-chain)
16. [Tworzenie struktur (konstruktor)](#tworzenie-struktur-konstruktor)
17. [Subscript (`pod`)](#subscript-pod)
18. [Zasięg i rozróżnianie wariantów](#zasięg-i-rozróżnianie-wariantów)
19. [Konflikty nazw](#konflikty-nazw)
20. [Komunikaty błędów](#komunikaty-błędów)

---

## Uruchamianie

Interpreter jest skryptem CLI:

```
./gćć-python/gćć.py PLIK.ć [--sgjp ŚCIEŻKA_DO_sgjp.tab]
```

- Wejście można też podać na `stdin`.
- `--sgjp` domyślnie wskazuje `../sgjp.tab` (czyli plik SGJP w katalogu nadrzędnym względem skryptu).
- Wynik to drzewo AST wypisane przez `pretty.pretty(module)` — drzewo
  z gałęziami `├──`/`└──`, z polami `params`, `body`, `cond`, `then`/`else`,
  `var`/`collection`/`body`, `fields`, `args`.

W trakcie uruchomienia źródło przechodzi przez:

1. `lexer.lex` — surowe tokeny.
2. `morph_anal.load` + `morph_anal.analyze` — dopina do tokenów słownikowe analizy z SGJP.
3. `preprocess.preprocess` — scalanie operatorów porównania, oznaczanie operatorów arytmetycznych, scalanie liczebników w jeden token literalny.
4. `parser.parse` — Pass 1: definicje, sterowanie, surowe `Phrase` jako reszta.
5. `expression.resolve_module` — Pass 2: każde `Phrase` jest rozkładane na faktyczne wyrażenie.
6. `pretty.pretty` — wypisuje AST.

---

## Struktura pliku źródłowego

Program to ciąg deklaracji top-level: definicji funkcji (`aby`), deklaracji
zewnętrznych (`można`), definicji typów (`definicja`), przypisań (`X to Y`)
oraz wyrażeń-statementów.

Plik powinien być w UTF-8. Wewnątrz funkcji obowiązują reguły
wcięciowe — jak w Pythonie.

```
# Komentarz na wierszu.
definicja Użytkownika:
    imię (Tekst)
    wiek (Liczba)

aby zacznij_dzień:
    licznik to zero
```

---

## Lekser

### Wcięcia

- Wcięcie liczy się w jednostkach: jedna tabulacja **lub** cztery spacje.
- Mieszane wcięcia: pierwsza nie-tabowa/nie-4-spacjowa pozycja kończy liczenie poziomu.
- Lekser emituje `INDENT`/`DEDENT` na zmianach poziomu i `DEDENT`y na końcu pliku, żeby zamknąć wszystkie otwarte bloki.

### Komentarze i puste linie

- Komentarz to linia, której pierwszy nie-biały znak to `#`. Komentarze
  i puste linie są w całości pomijane — nie produkują nawet `NEWLINE`.

### Token `NEWLINE`

- Lekser produkuje `NEWLINE` po każdej **treściwej** linii (linia, która coś wniosła do strumienia tokenów).

### Słowa (`WORD`)

Słowo to dowolny ciąg znaków, w którym nie ma spacji, dwukropka,
nawiasów, znaku `"`. Każde słowo jest dzielone na **segmenty**:

1. Najpierw rozcięcie po `_`. Puste segmenty są pomijane (`__x` to to samo co `_x`).
2. Każda część jest dalej rozcinana po dużych literach (CamelCase): wielka litera rozpoczyna nowy segment.
3. Wszystkie segmenty są zamieniane na małe litery.

Przykłady:

| Źródło | Segmenty |
|---|---|
| `użytkownik` | `("użytkownik",)` |
| `zapisz_w_bazie` | `("zapisz","w","bazie")` |
| `AdresKorespondencyjny` | `("adres","korespondencyjny")` |
| `UżytkownikAdministrujący` | `("użytkownik","administrujący")` |
| `to_zrobic` | `("to","zrobic")` — `to` wewnątrz słowa pozostaje segmentem, nie operatorem |

Token `WORD` niesie ze sobą krotkę segmentów, **nie** oryginalną pisownię.

### Literały tekstowe (`TEXT`)

- W cudzysłowach `"…"`. Wewnątrz cudzysłowów dozwolone wszystko poza `"`.
- Lekser nie interpretuje znaków ucieczki — wartość tekstu to dokładnie to,
  co jest między cudzysłowami. Np. `"\n"` to dwuznakowy ciąg `\` + `n`.

### Pozostałe tokeny

| Tok | Składnia |
|---|---|
| `COLON` | `:` |
| `LPAREN` / `RPAREN` | `(` / `)` |
| `ARROW` | `->` |
| `ASSIGN` | słowo `to` (specjalnie wyróżnione przez lekser — gdy w treści linii pojawi się samo słowo `to`, staje się `ASSIGN`). Wewnątrz większego słowa `to` nadal jest zwykłym segmentem (`to_zrobic`). |

### Granice tokenów

- `:`, `(`, `)`, `"` zawsze rozcinają od sąsiednich słów; `klienta:` to `WORD("klient", …) COLON`.
- Spacje, taby — zwykłe separatory.

---

## Liczebniki słowne

Liczby zapisuje się słowami. Preprocesor scala maksymalną sekwencję
liczebników w jeden token literału całkowitego (`INT_LIT`).

Słowo jest liczebnikiem, jeżeli SGJP daje mu analizę z `pos == "num"` **lub**
jego kanoniczna lemma to wielokrotność (`tysiąc`, `milion`, `miliard`,
`bilion`, `trylion`) — bo gen. pl. typu `tysięcy`/`milionów` w SGJP są
tagowane wyłącznie jako `subst`, a muszą być uznane za część liczby.

### Słowniki

- **Jednostki 0–19:** `zero`, `jeden`, `dwa`, `trzy`, `cztery`, `pięć`, `sześć`, `siedem`, `osiem`, `dziewięć`, `dziesięć`, `jedenaście`, `dwanaście`, `trzynaście`, `czternaście`, `piętnaście`, `szesnaście`, `siedemnaście`, `osiemnaście`, `dziewiętnaście`.
- **Dziesiątki:** `dwadzieścia`–`dziewięćdziesiąt`.
- **Setki:** `sto`, `dwieście`, …, `dziewięćset`.
- **Wielokrotności (skala polska/długa):** `tysiąc` = 10³, `milion` = 10⁶, `miliard` = 10⁹, `bilion` = 10¹², `trylion` = 10¹⁸.

### Algorytm

Iteruje po tokenach, kumulując bieżącą grupę:

- jednostki/dziesiątki/setki: dodawane do `current`,
- wielokrotność: `total += max(current, 1) * mag`, a `current` zerowane.

Końcowy wynik: `total + current`.

Przykłady:

| Zapis | Wartość |
|---|---|
| `zero` | 0 |
| `jeden` | 1 |
| `dziewiętnaście` | 19 |
| `dwadzieścia trzy` | 23 |
| `sto dwadzieścia trzy` | 123 |
| `czterysta dwadzieścia pięć tysięcy czterysta trzydzieści pięć` | 425 435 |
| `tysiąc` | 1000 |
| `dwa tysiące` | 2000 |
| `pięć tysięcy` | 5000 |
| `dwa miliony trzysta tysięcy` | 2 300 000 |
| `miliard` | 1 000 000 000 |

Liczebniki muszą iść jedno po drugim, bez operatorów między — operator
arytmetyczny rozcina sekwencję na dwie liczby: `sto plus dwieście` →
`INT_LIT 100 + INT_LIT 200`.

---

## Operatory leksykalne (preprocesor)

Preprocesor wykonuje cztery przebiegi na strumieniu tokenów (w tej
kolejności):

### 1. Operatory porównania (`CMP_OP`)

Rozpoznawane **po formie powierzchniowej** (bo w SGJP `mniejsze` ma lemmę
`mały` — odróżnienie operatora od zwykłego przymiotnika wymaga form
neutrum singularis).

| Słowa | Operator |
|---|---|
| `mniejsze od` | `<` |
| `większe od` | `>` |
| `mniejsze równe` | `<=` |
| `większe równe` | `>=` |
| `równe` | `=` |
| `nierówne` | `!=` |

`równe` i `nierówne` rozpoznawane po **lemmie** (`równy`/`nierówny`).
Pojedynczy segment — wewnątrz `mały_kot` (multi-seg) `mniejsze` nie
zostanie wykryte.

### 2. Operatory arytmetyczne (`ARITH_OP`, `TERM_OP`)

Rozpoznawane po formie powierzchniowej (po lemmie też by zadziałało — lemmy
są kanoniczne):

| Słowo | Operator |
|---|---|
| `plus` | `+` |
| `minus` | `-` |
| `razy` | `*` |

Tylko jako pojedynczy segment (`("plus",)`). Dzielenie i modulo nie
istnieją.

### 3. Operator subscript (`POD`)

Słowo `pod` (kanoniczna lemma `("pod",)`) staje się tokenem `POD`, ale
**tylko** jako pojedynczy segment. `pod_warunkiem` (multi-seg) pozostaje
zwykłym `WORD`.

### 4. Scalanie liczebników w `INT_LIT`

Maksymalna sąsiadująca sekwencja słów-liczebników (zob. wyżej) jest scalana
w jeden token `INT_LIT` z wartością `int`.

Kolejność (cmp → arith → pod → numbers) jest istotna: gdyby liczby były
najpierw, `mniejsze od pięć` zgubiłoby `pięć` w scalaniu — `od` nie jest
liczebnikiem, ale wpadałoby między `cmp` i resztę.

---

## Identyfikatory

Identyfikator multi-segmentowy ma postać:

```
[przymiotnik]* [rzeczownik] [reszta]
```

- **Przymiotniki** (segmenty z analizą `adj`, `pact`, `ppas`) tworzą prefiks
  i muszą zgadzać się w przypadku z głową rzeczownikową oraz między sobą.
- **Rzeczownik** (`subst`) zamyka prefiks jako głowa identyfikatora.
- **Reszta** (segmenty po głowie) jest passthrough — nie wpływa na przypadek,
  lemma kanonikalizowana standardowo.

Single-seg identyfikatory bez analiz (np. `x`, `n`) lub atomy single-letter
są traktowane jako nieprzezroczyste — przepuszczane bez analizy morfologicznej.

### Warianty

Każdy identyfikator niesie **wszystkie spójne interpretacje** — kartezjański
produkt po segmentach z możliwością czytania `adj`-czytania (kontynuuje
prefiks) lub `subst`-czytania (zamyka prefiks jako głowa). Po refaktoringu
parser nie wybiera jednego „kanonicznego" wariantu — każdy `Identifier` ma
pole `variants: tuple[(lemmas_tuple, case_frozenset), ...]` z wszystkimi
możliwościami. Dispatcher kontekstowy (np. w `struct_creation`, w
argumencie wywołania) wybiera ten wariant, który domyka kontekst.

Przykład: `części_mowy`

- Subst-prefix: `("część", "mowa")` z casem `{gen, dat, loc}`.
- Adj-prefix: `("częsty", "mowa")` z casem `{nom, voc}` (m1 pl).

Atrybut `lemmas_set` daje sumę wszystkich kandydujących krotek lemm,
`case` to suma przypadków po wariantach.

### Identyfikatory funkcji

Identyfikator funkcji musi zawierać **co najmniej jeden segment
czasownikowy** (analiza `fin`, `impt`, `inf`, `imps`, `praet`, `pcon`,
`winien`, `bedzie`, `fut`, `cond`). Pierwszy taki segment jest „głową
czasownikową" — fundzia funkcji powstaje z permutacji lemm wszystkich
segmentów.

- Wybór czasownikowej lemmy: spośród analiz czasownikowych — preferuje tę,
  której lemma jest równa formie powierzchniowej, w przeciwnym razie
  pierwszą.
- Funkcja nie ma `case` (verb-only). Wewnątrz `Identifier.variants` zwraca pustą krotkę.
- Single-seg verb-only identyfikatory są tolerowane jako nazwy funkcji (np. `działać`, `zwrócić`).

### Błędy identyfikatorów

Wielosegmentowy identyfikator, którego pierwszy segment nie jest ani
przymiotnikiem, ani rzeczownikiem, ani czasownikiem (np. `czy_zielony` —
`czy` to `qub`), rzuca `IdentifierError`:

```
Niepoprawny identyfikator 'czy_zielony': pierwszy segment 'czy' nie jest
ani przymiotnikiem, ani rzeczownikiem, ani identyfikatorem funkcji.
Oczekiwana forma: [przymiotnik...] [rzeczownik] [reszta], gdzie
przymiotniki i rzeczownik zgadzają się w przypadku.
```

### Kanonikalizacja segmentów

Funkcja `canonical` zwraca jedną kanoniczną krotkę lemm:

- Single-letter / brak analiz → segment niezmieniony.
- Multi-pos segment — preferuje analizy `adj`/`pact`/`ppas`. Wśród nich
  wybiera tę, której lemma równa się segmentowi, w przeciwnym razie pierwszą.
- Imiesłowy aktywne i bierne (`pact`, `ppas`) są w SGJP lematyzowane do
  bezokolicznika — przy ładowaniu bazy ich lemma zastępowana jest
  cytowaną formą mianownika sg. m1 (`administrujący` zamiast `administrować`).

Przykłady kanonikalizacji:

| Forma | Lemma kanoniczna |
|---|---|
| `rzecz` | `("rzecz",)` |
| `klienta` | `("klient",)` |
| `fibonacci` | `("fibonacci",)` (nieznane — passthrough) |
| `n`, `a` | `("n",)`, `("a",)` |
| `administrującego` | `("administrujący",)` |
| `obserwowanego` | `("obserwowany",)` |
| `zielonego` | `("zielony",)` (preferencja adj nad substantywizowanym `zielone`) |
| `zapisz_w_bazie` | `("zapisać", "w", "baza")` |
| `inna_rzecz` | `("inny", "rzecz")` |

---

## Definicje funkcji (`aby`)

```
aby NAZWA [PARAM…] [-> TYP]:
    STMT
    STMT
    …
```

- `NAZWA` to identyfikator funkcji (musi zawierać czasownik).
- Każdy `PARAM` ma postać `[PRZYIMEK] NAZWA_PARAM [( TYP )]`.
- Opcjonalne `-> TYP` deklaruje typ zwracany.
- Ciało rozpoczyna się od `:`, jednej linii (czasem pustych) i poziomu wcięcia.

### Parametry

Parametr to:

```
[PRZYIMEK] IDENTYFIKATOR [( TYP )]
```

- **Przyimek** — pojedynczy segment, którego kanoniczna lemma znajduje się
  w słowniku przyimków (zbudowanym przy ładowaniu SGJP — wszystkie formy
  `pos == "prep"`, mapowane na zbiór dopuszczalnych przypadków).
- **Identyfikator** — może być w dowolnej fleksji; jego `case` jest
  zapamiętany w polu parametru (do późniejszego dopasowania argumentów).
- **Typ** — w nawiasach, jedno słowo. Pobierana jest kanoniczna lemma typu.

Przykłady:

```
aby pisać x:                                          # 1 param bez przyimka
aby pisać_coś_do_klienta coś do klienta:              # 2 params, drugi z 'do'
aby zapisywać_w_bazie x w bazie:                      # parametr w locativie
aby wysłać coś do odbiorcy przez kanał od nadawcy:    # 4 params, 3 z przyimkami
aby pisać x (Tekst):                                  # parametr z typem
aby działać -> wynik:                                 # tylko typ zwracany
aby usuwać_z_listy element (Tekst) z listy (Tekst) -> wynik:
```

### Przyimki w słowniku

Słownik przyimków powstaje przy ładowaniu SGJP — zawiera wszystkie formy
z `pos == "prep"`, indeksowane po lemmie, z sumą dopuszczalnych przypadków.

- `na`: `{acc, loc}`
- `w`: `{acc, loc}`
- `dla`: `{gen}`
- itd.

**Uwaga:** alternacje samogłoskowe (`ze`, `we`, `nade`, `przede`, …) są w
SGJP traktowane jako oddzielne lematy — formy podstawowe (`z`, `w`, `nad`,
`przed`) są kanoniczne i tylko one trafiają do dispatcherów. W tej chwili
warianty samogłoskowe **nie** są aliasowane — w kodzie zawsze należy używać
formy podstawowej.

### Konwencja: nazwa parametru określa też jego rolę gramatyczną

Funkcja przyjmuje argumenty „przez przyimek + przypadek". Wywołanie
dopasowuje argumenty do parametrów po (przyimku, przypadku) — patrz
[Wywołania funkcji](#wywołania-funkcji).

---

## Funkcje zewnętrzne (`można`)

```
można NAZWA [PARAM (TYP)…] -> TYP
```

Deklaracja sygnatury funkcji bez ciała — analogia `extern` z C. Składnia
nagłówka jak przy `aby`, ale **bez** dwukropka i bez bloku ciała. Cała
deklaracja mieści się w jednej linii.

Ponieważ extern nie ma ciała, z którego dałoby się wnioskować typy,
**każdy parametr musi mieć jawny typ `(Typ)`, a typ zwracany `-> Typ`
jest obowiązkowy** — brak któregokolwiek to błąd parsowania. Typechecker
buduje sygnaturę wprost z adnotacji i traktuje wywołania externów tak
samo jak wywołania funkcji z `aby`. Głowa niebędąca znanym typem (np.
`Miejsce` bez `definicja`) działa jak parametr typu współdzielony
w obrębie sygnatury.

Próba dodania `:` lub ciała rzuca `SyntaxError`.

Przykłady:

```
można działać -> Nic
można wypisać tekst (Tekst) -> Nic
można zapisać do bazy (Baza) dane (Tekst) -> Nic
można leżeć na polanie (Miejsce) w lesie (Miejsce) przy jeziorze (Liczba) -> Liczba
można policzyć x (Tekst) -> liczba

# błąd — parametry bez typów i brak typu zwracanego:
można leżeć na polanie w lesie przy jeziorze
```

**Uwaga implementacyjna:** parser dopasowuje `można` po **formie powierzchniowej** segmentu, ponieważ kanonikalizacja w trybie adj-priority woli `możny` (przym.) niż predykatyw `można`. Inne formy `możny` nie wyzwolą extern-def.

`można` można mieszać z `aby` w jednym module.

---

## Definicje typów (`definicja`)

```
definicja NAZWA_TYPU:
    POLE
    POLE
    …
```

- `NAZWA_TYPU` — identyfikator (multi-seg po CamelCase i `_`); jego
  **kanoniczna lemma** stanowi nazwę typu (np. `Sesji` → `("sesja",)`,
  `AdresKorespondencyjny` → `("adres", "korespondencyjny")`).
- `POLE` ma postać `NAZWA_POLA ( TYP )`. Każde pole w osobnej linii.

```
definicja Sesji:
    token (Tekst)
    użytkownik (Użytkownik)
    data_utworzenia (Data)
    adres_ip (AdresIP)
```

### Konwencja: pola deklaruje się w mianowniku

Identyfikator pola jest przepuszczany przez normalny resolver wariantów.
Z każdej krotki wariantów do `field_names` trafiają **tylko te lemma-krotki,
które mają w przypadku `nom`** (`_field_lemmas`). Jeżeli żaden wariant nie
zawiera `nom`, jest błąd `ResolveError("pole struct-a 'X' nie ma formy
mianownika; pola deklaruj w nom")`.

- Atom (single-letter / bez wariantów) jest przepuszczany jako jedyna lemma.
- Multi-wariantowe pola (np. `liście`) dostają tylko warianty mianownika.

---

## Typy wariantowe (`albo`, `czym jest`)

### Deklaracja unii

```
NAZWA to WARIANT albo WARIANT [albo WARIANT…]
```

Deklaracja na poziomie modułu, rozpoznawana po samodzielnym słowie `albo`
po prawej stronie `to` (`albo` nie jest operatorem wyrażeń, więc nie
koliduje z przypisaniami). Wszystkie nazwy w mianowniku.

```
definicja Błędu:
    opis (Tekst)

definicja Wyniku z elementem:
    wynik (element)

Rezultat to Wynik albo Błąd
```

Zasady:

- Każdy wariant musi być **strukturą zdefiniowaną w module** (nie builtinem,
  nie inną unią — zagnieżdżanie unii jest niedozwolone). Kolejność deklaracji
  w module jest dowolna.
- Warianty wymienia się **bez parametrów typu** — parametryzacja to sprawa
  konkretnych struktur; unia tylko grupuje głowy. W konsekwencji unia
  „wymazuje" argumenty typów wariantów (`Wynik z Liczbą` → `Rezultat`).
- Nazwa unii działa wszędzie tam, gdzie nazwa typu: adnotacje parametrów,
  typ zwracany, typy pól, sufiks `(Rezultat)`.
- Nie można utworzyć wartości unii przez `Rezultat o ...` — tworzy się
  konkretną strukturę.

### Podtypowanie

Jedyna dopuszczana relacja to **struktura < typ wariantowy**, stosowana na
pozycjach top-level unifikacji: przypisanie, `zwrócić`, argument wywołania,
wartość pola, adnotacja. Gdy dwie strony to różne warianty jednej unii (albo
wariant i jego unia), typ rozszerza się do unii — przy wielu pasujących
uniach wygrywa najmniejsza, remis to błąd. Funkcja zwracająca w gałęziach
różne warianty jednej unii jest typowana tą unią; gałęzie zwracające typy
bez wspólnej unii to błąd (nie ma nienazwanych unii). Typy parametryzowane
są **inwariantne**: `Lista z (Wynik)` nie unifikuje się z `Lista z (Rezultat)`.

### Dopasowanie: `czym jest X?`

```
czym jest WYRAŻENIE?
    jeśli WARIANT [z POLE]*:
        BLOK
    jeśli WARIANT [z POLE]*:
        BLOK
```

- `czym jest` rozpoznawane po formach powierzchniowych na początku
  statementu; nagłówek kończy `?` (nowy token leksera, poza stringami).
- Unia subjectu jest wyznaczana inferencją: zbiór gałęzi musi **dokładnie**
  odpowiadać zbiorowi wariantów jednej zadeklarowanej unii (brak gałęzi
  dla wariantu → błąd z listą brakujących; gałąź spoza unii → błąd;
  duplikat gałęzi → błąd). Typ subjectu unifikuje się z tą unią — więc
  `czym jest` na nieotypowanym parametrze typuje go unią w sygnaturze.
- `z POLE` dekonstruuje wariant: pole (w narzędniku, jak shorthand
  konstruktora)
  staje się zmienną w scope gałęzi, o typie z deklaracji struktury.
  Można związać **podzbiór** pól (też żadne: `jeśli Wynik:`). Pola
  o typie-parametrze struktury zaczynają jako wolne zmienne i konkretyzują
  się przez użycie.
- Gałąź to osobny blok (jak ciało `jeśli`): związane pola i zmienne
  zadeklarowane w gałęzi są dla niej lokalne; zmienną używaną po matchu
  zadeklaruj przed nim i reasygnuj w gałęziach.

```
aby opisywać rezultat -> Tekst:
    czym jest rezultat?
        jeśli Wynik:
            zwróć "powodzenie"
        jeśli Błąd z opisem:
            zwróć opis
```

Pełny przykład: `test/warianty.ć`.

---

## Struktury sterujące

### `jeśli` / `inaczej jeśli` / `inaczej`

```
jeśli WARUNEK:
    BLOK
[ inaczej jeśli WARUNEK:
    BLOK ]*
[ inaczej:
    BLOK ]
```

Łańcuch `inaczej jeśli` jest rekursywnie zagnieżdżonym `If` w `else_body`.

```
jeśli x mniejsze od jeden:
    a to jeden
inaczej jeśli x mniejsze od dwa:
    a to dwa
inaczej:
    a to trzy
```

### `dopóki` (while)

```
dopóki WARUNEK:
    BLOK
```

### `dla X w Y:` (for / foreach)

```
dla ZMIENNA w KOLEKCJA:
    BLOK
```

- `ZMIENNA` to identyfikator (zwykła walidacja jak inne identyfikatory).
- `w` — wymagane słowo łącznikowe, sprawdzane po kanonikalnej lemmie
  `("w",)`. Brak `w` rzuca `SyntaxError`.
- `KOLEKCJA` to dowolne wyrażenie (Phrase): zmienna, subscript, getter
  chain, wywołanie funkcji, struct creation, logika.

```
dla użytkownika w liście:
    nazwa to imię użytkownika
```

**Uwaga:** `dla` jest słowem kluczowym strukturalnym **tylko na pierwszej
pozycji statementu**. Wewnątrz `phrase` (np. argument wywołania funkcji:
`weź dla użytkownika`) `dla` jest zwykłym przyimkiem dopuszczalnym przez
parser wyrażeń.

### `stop` (break) i `dalej` (continue)

- `stop` — break z najbliższej pętli. Brak argumentu.
- `dalej` — continue. Brak argumentu. Cokolwiek po `dalej` to `SyntaxError`.

**Uwaga:** `dalej` jest słowem kluczowym **tylko na pozycji
statementu**. Wewnątrz phrase'a `dalej` jest zwykłym tokenem
(`a to dalej` zostaje przypisaniem do zmiennej `dalej`).

### `zwrócić` (return)

```
zwrócić [WYRAŻENIE]
```

- `zwrócić` bez wartości — `Return(value=None)`.
- `zwrócić WYRAŻENIE` — wartość zwrotu to dowolne wyrażenie.

```
zwrócić
zwrócić pięć
zwrócić dwa plus trzy
zwrócić użytkownik sesji
```

---

## Przypisanie (`to`)

```
LEWA_STRONA to PRAWA_STRONA
```

- `LEWA_STRONA` to wyrażenie:
  - prosta zmienna (`liczba to pięć`),
  - chain LHS / field write (`liczba_polubień postu to ...`),
  - subscript (`lista pod indeksem to ...`).
- `PRAWA_STRONA` — dowolne wyrażenie.

`to` jest słowem kluczowym leksykalnym — pojawienie się słowa `to` (poza
literałem tekstowym i poza większym wyrazem) tworzy token `ASSIGN`,
który rozcina statement na lewą i prawą stronę.

`równe` to porównanie, nie przypisanie:

```
x to a równe b
# → Assignment(target=Phrase[x], value=BinOp(=, a, b))
```

### Reguła scope dla `to` (block scoping)

Jeżeli lewa strona to **prosta zmienna** (pojedyncze WORD, niebędące
chain'em po polu ani subscriptem), to przypisanie **deklaruje** zmienną
w bieżącym bloku — jest widoczna **od miejsca przypisania do końca
bloku**. Prawa strona jest rozwiązywana PRZED deklaracją lewej, więc
`x to x` bez wcześniejszego `x` to błąd (użycie przed przypisaniem).

Jeżeli LHS to chain rozpoczynający się od pola struct-a (`autor postu to ...`),
to przypisanie jest **zapisem do pola** — `autor` **nie** staje się
zmienną. Subscript-LHS (`lista pod indeksem to ...`) to zapis do elementu —
`lista` musi już być zadeklarowana.

Ciała `jeśli`/`inaczej`, `dopóki`, `dla` i gałęzi `czym jest` to **osobne
bloki**: zmienna zadeklarowana w gałęzi NIE jest widoczna po bloku ani
w sąsiedniej gałęzi. Przypisanie do zmiennej widocznej z bloku
nadrzędnego to **reasignacja** tej zmiennej (nie nowa, lokalna kopia) —
typechecker unifikuje typy na jednej zmiennej:

```
licznik to zero          # deklaracja przed blokiem
jeśli flaga:
    licznik to pięć      # reasignacja zewnętrznego licznika
wynik to licznik         # OK — licznik widoczny, typ Liczba
```

Bez deklaracji przed blokiem `wynik to licznik` byłby błędem rezolucji.

---

## Wyrażenia

Wszystko, co nie jest słowem kluczowym strukturalnym (`aby`, `można`,
`definicja`, `jeśli`, `inaczej`, `dopóki`, `dla`, `stop`, `dalej`,
`zwrócić`) na pozycji statementu, jest **frazą**. Granica frazy
(`Phrase`) to: `NEWLINE`, `COLON`, `ARROW`, `INDENT`, `DEDENT`, `ASSIGN`
albo niezbalansowany `)`. Nawiasy chwilowo wyłączają tę regułę
(`paren_depth > 0`).

Drugi przebieg (`expression.resolve_module`) bierze każdą frazę i parsuje
ją w pełnej gramatyce wyrażeń (od najniższego do najwyższego
priorytetu):

```
phrase     := or_expr
or_expr    := and_expr ("lub" and_expr)*
and_expr   := not_expr ("i"  not_expr)*
not_expr   := "nie" not_expr | cmp_expr
cmp_expr   := arith [CMP_OP arith]
arith      := term (ARITH_OP term)*        # +, -
term       := factor (TERM_OP factor)*     # *
factor     := [ARITH_OP] subscript         # unary +/-
subscript  := primary ("pod" primary)*     # left-assoc, postfix
primary    := INT_LIT | TEXT | "(" phrase ")"
            | function_call | getter_chain | struct_creation
            | identifier_ref
```

### Priorytety i asocjatywność

- `lub` < `i` < `nie` < porównanie < `+ -` < `*` < unarny `+` `-` < `pod`.
- Lewa asocjatywność w `+`, `-`, `*` i `pod` (`10 - 3 - 2 = (10-3)-2 = 5`).
- Porównanie nie jest asocjatywne (`a < b < c` jest błędne — tylko jeden CMP_OP).
- `nie` jest prawo-asocjatywne (`nie nie x` to `Not(Not(x))`).

### Operatory logiczne

- `nie` (Not) — prefiks. Niższe od `i`/`lub`, **wyższe** od porównań. Czyli
  `nie dwa większe od trzy` to `Not(BinOp(>, 2, 3))`.
- `i` (And) — binarny.
- `lub` (Or) — binarny.
- `a i b lub c` to `Or(And(a, b), c)`.

### Porównania

Patrz [Operatory leksykalne](#operatory-leksykalne-preprocesor).
Dwa argumenty arytmetyczne po obu stronach operatora:

```
jeden plus dwa mniejsze od trzy plus cztery
# → BinOp(<, BinOp(+,1,2), BinOp(+,3,4))
```

### Arytmetyka

- `plus` (+), `minus` (-), `razy` (*).
- Brak dzielenia, modulo, potęgowania (na razie).
- Unarny `+`/`-` w pozycji `factor`. Można składać: `minus minus pięć` to `UnaryOp(-, UnaryOp(-, 5))`.

```
dwa plus trzy razy pięć        # → 2 + (3*5)
(dwa plus trzy) razy cztery    # → (2+3) * 4
minus pięć                     # → -5
```

### Literały

- `INT_LIT` — patrz [Liczebniki słowne](#liczebniki-słowne).
- `TEXT` — np. `"siemka"`. Wartość — dokładnie to, co w cudzysłowach.

### Nawiasy

`(` i `)` grupują dowolne wyrażenie. Nawiasy mogą zawierać operatory
logiczne (`(a i b)`), porównania (`(x mniejsze od y)`), arytmetykę,
chainy, subscripty, fcalls — wszystko.

---

## Wywołania funkcji

Wywołanie funkcji ma postać `NAZWA ARG1 ARG2 ARG3 …` — nazwa, potem
argumenty rozdzielone spacjami. Każdy argument:

```
[PRZYIMEK] PRIMARY
```

- Argument zawsze jest poziomu `primary` — operatory binarne wiążą się na
  **zewnątrz** wywołania (lewostronne wiązanie).
- Liczba argumentów musi odpowiadać liczbie parametrów w sygnaturze
  zdefiniowanej w module (lub w `aby` zdefiniowanym dalej — sygnatury są
  zbierane w pierwszym przebiegu, więc forward reference działa).

### Dopasowanie argumentów do parametrów

Parametry w `aby`/`można` mają trójkę (przyimek, przypadek z identyfikatora,
typ). Argumenty mają (przyimek, przypadek wyrażenia jeśli to `Identifier`).

Algorytm dopasowania (`_match_args_to_slots`):

1. Dla każdego argumentu zbierz zbiór kandydujących slotów (parametrów):
   - przyimek argumentu = przyimek parametru,
   - jeżeli oba przypadki znane, ich przecięcie musi być niepuste.
2. Wielokrotnie: jeśli któryś argument ma dokładnie **jeden** wolny kandydujący slot — przypisz go i usuń ze zbiorów; powtarzaj aż brak postępu.
3. Pozostałe argumenty przypisywane są **pozycyjnie** do pozostałych wolnych slotów (po kolei wystąpienia).
4. Jeśli pozycyjne dopasowanie nie pasuje do kandydatów (przyimek się nie zgadza), to `ResolveError`.

```
aby wysłać coś do odbiorcy przez kanał od nadawcy:
    …
# wywołanie:
wyślij "treść" do anny przez https od marka
# parametry (z prep): None, do, przez, od
# arg "treść" → None slot (coś)
# arg do anny → do slot (odbiorca)
# arg przez https → przez slot (kanał)
# arg od marka → od slot (nadawca)
```

### Forward references

Sygnatury funkcji są kolekcjonowane w pierwszym przebiegu, więc wywołanie
może wystąpić **przed** definicją:

```
aby działać:
    pisz "hej"        # ← wywołanie

aby pisać x:          # ← definicja
    zwrócić
```

### Sub-wywołania jako argumenty

```
aby weź_użytkownika_z_bazy o identyfikatorze: …
aby zapisz_w_bazie x: …

# Sub-fcall jako argument (primary):
zapisz_w_bazie weź_użytkownika_z_bazy o identyfikatorze
# → FunctionCall(zapisz_w_bazie, [
#       Word(None, FunctionCall(weź_użytkownika_z_bazy, [Word(o, identyfikator)]))
#   ])
```

### Operatory na zewnątrz wywołania

Bo argumenty są tylko `primary`, operatory wiążą wynik wywołania:

```
weź_wiek_z_bazy dla identyfikatora plus siedem
# → BinOp(+, FCall(weź_wiek_z_bazy, [identyfikator]), 7)

wywołaj_funkcję z dwa plus trzy
# → BinOp(+, FCall(wywołaj_funkcję, [Word(z, 2)]), 3)

wywołaj_funkcję z (dwa plus trzy)
# → FCall(wywołaj_funkcję, [Word(z, BinOp(+, 2, 3))])
```

### Nazwa wywołania → identyfikator funkcji

`head_ident` musi mieć **co najmniej jedną** lemma-krotkę w
`function_defs` (zarejestrowanych przez `aby`/`można`).

- Jeżeli `FunctionIdentifier.from_head` nie wybuchnie i któraś lemma istnieje w `function_defs` → wywołanie funkcji.
- W przeciwnym razie → traktujemy jak referencję zmiennej (`identifier_ref`), z opcjonalnym narrowingiem do zmiennych w scope.

### Kanonikalizacja vs deklaracja

`canonical()` w analizatorze morfologicznym preferuje analizy `adj`-like
nad innymi. Czasem powoduje to, że forma użycia kanonikalizuje się inaczej
niż definicja:

- `znajdź` (impt sg) → `("znaleźć",)` w definicji `aby znajdź_użytkownika`,
  ale w wywołaniu też `znajdź_użytkownika` → tę samą lemmę.
- `dąb` ma w SGJP analizę `impt` od czasownika `dąć` — resolver traktuje go
  jak nazwę funkcji.
- `złóż_komunikat` w wywołaniu kanonikalizuje się do `('złoże', 'komunikat')`
  (subst > verb). Definicja musi mieć identyczną formę powierzchniową.

W praktyce: **definiuj funkcje w tej samej formie powierzchniowej co
wywołania**. Jeżeli nie pasuje, można definiować używając form takich
samych jak w call site, bo cała `lemmas_set` (kartezjański produkt) i tak
ląduje w mapie `function_defs`.

---

## Łańcuchy dostępu do pól (getter chain)

```
POLE OBIEKT [POLE_GŁĘBSZE] [POLE_JESZCZE_GŁĘBSZE] …
```

Łańcuch dopisuje kolejne segmenty — pierwszy jest **polem zarejestrowanego
struct-a**, kolejny jest **dopełniaczem** (`gen`) identyfikatora bazy.

Detekcja chain-startu (`_can_start_chain`):

1. `head_ident.lemmas_set` ma niepuste przecięcie z `ctx.field_names`.
2. Następny token to WORD niebędący przyimkiem, w którego wariantach jest `gen`.

Po starcie chain jest rozszerzany dopóki:

- ostatni element chain'a jest polem (`_ident_is_field`),
- następny token jest słowem w `gen` (i nie jest przyimkiem).

Każdy element chain to `Identifier` (z wariantami). Wybór ostatecznej
lemmy pola zostawia się dispatcherowi pól (na razie tylko symboliczne —
przy rozróżnianiu nazw pól w struct_creation).

Przykłady:

```
# Definicja:
definicja Postu:
    autor (Tekst)
    treść (Tekst)

# Łańcuch 2-elementowy:
wynik to autor postu                 # GetterChain(autor, post)

# Z arytmetyką wokół:
licznik to liczba_polubień postu plus dwadzieścia osiem
#         → BinOp(+, GetterChain(liczba_polubień, post), 28)
```

Wewnątrz typu zagnieżdżonego:

```
imię użytkownika sesji
# → GetterChain(imię, użytkownik, sesja)
```

### Chain w pozycji LHS przypisania

```
liczba_polubień postu to liczba_polubień postu plus jeden
```

LHS to chain → **field write** (nie deklaracja zmiennej). `liczba_polubień`
nie staje się zmienną.

### Chain w pozycji indeksu / argumentu fcall / wartości pola

Wszędzie tam, gdzie pojawia się `primary`, chain rozpoznawany jest tak samo.

```
lista pod numerem autora
# → Subscript(lista, GetterChain(numer, autor))
```

---

## Tworzenie struktur (konstruktor)

```
TYP [O POLE WARTOŚĆ]* [Z POLE]*
```

Nazwa typu w pozycji wyrażenia rozpoczyna konstrukcję struct — typy mają
skapitalizowane lemmy, a zmienne/pola/funkcje małą literę, więc wielka
litera jednoznacznie wskazuje konstruktor (nie ma słowa kluczowego;
`nowy` jest zwykłym słowem i może być np. nazwą zmiennej). Nazwa typu
może być w dowolnym przypadku (dopasowanie po lemmie). Reszta tokenów
to argumenty:

- `o POLE WARTOŚĆ` — explicit value. `POLE` musi być w `loc` w jakimś
  wariancie (`o jakim/o czym`). `WARTOŚĆ` to **pełne wyrażenie** (Phrase) —
  obejmuje arytmetykę, fcalls, chainy, zagnieżdżone struct creation.
  Granica `WARTOŚĆ` ustalana jest dynamicznie: kończy się gdy kolejny
  token to `o` lub `z` matchujące niezajęte pole aktywnego struct-a
  (`StructCtx` — stos w parserze).
- `z POLE` — shorthand. `POLE` musi być w `inst` w jakimś wariancie
  (`z jakim/z czym`). Wartość pola = `None` (semantycznie: weź wartość
  z istniejącej zmiennej / z aktualnego scope'u o tej samej nazwie —
  zmienna musi być zadeklarowana, inaczej `ResolveError`).

### Dispatcher pól w struct args

Każdy kolejny `o/z` + WORD jest oceniany w kontekście aktywnego `StructCtx`:

- Wybierany jest wariant identyfikatora pola, w którym lemma trafia w
  `fields_by_type[ctx.type_name] - already_assigned` z wymaganym `case`
  (`loc` dla `o`, `inst` dla `z`).
- Jeśli żaden wariant nie pasuje, dispatcher kończy parsowanie argumentów
  i wraca; reszta tokenów (jeśli zostały) jest parsowana w gramatyce
  wyrażeń — co zwykle rzuca `ResolveError`.
- Jeśli wiele wariantów pasuje, parser rzuca `ResolveError("…
  niejednoznaczny w tym kontekście…")`.

### Zagnieżdżone struct creation

Stos `struct_stack` w parserze pozwala na zagnieżdżone konstrukcje. Granica
wartości pola w zewnętrznym struct jest wyznaczana po tym, czy kolejny
token to `o/z` matchujące **niezajęte pole zewnętrznego** struct-a
(innermost wins — `_next_struct_arg_kind` patrzy na bieżący `ctx` na
szczycie stosu).

### Przykłady

```
definicja Użytkownika:
    nazwa (Tekst)
    wiek (Liczba)

# Explicit value:
u to Użytkownik o nazwie "Anna"

# Wartość = pełne wyrażenie:
u to Użytkownik o wieku weź_wiek_z_bazy dla identyfikatora plus siedem o nazwie "Anna"

# Shorthand (z nazwą + z wiekiem):
u to Użytkownik z nazwą z wiekiem

# Mieszane:
u to Użytkownik z nazwą o wieku trzydzieści

# Zagnieżdżone:
nowy_komentarz to Komentarz o autorze Użytkownik o imieniu "Anna" o nazwisku "Nowak" o poście Post o treści "Pierwszy" o liczbie_polubień zero

# Duplikat pola — innermost wins:
test to Komentarz o autorze Użytkownik o identyfikatorze jeden o identyfikatorze dwa
# `o identyfikatorze jeden` → Użytkownik.identyfikator = 1
# `o identyfikatorze dwa`   → Komentarz.identyfikator = 2 (innermost ma już zajęte → wrac na enclosing)
```

---

## Subscript (`pod`)

```
PRIMARY pod PRIMARY [pod PRIMARY]…
```

- Lewostronna asocjatywność (`a pod b pod c = (a pod b) pod c`).
- Operator postfiksowy: po `primary`, kolejne `pod primary` rozszerzają lewy operand.
- Prawy operand to `primary` (np. liczba, identyfikator, chain, nawiasy
  z wyrażeniem). Brak prawego operandu → `ResolveError`.

Priorytet — niższy od arytmetyki:

```
lista pod indeksem plus jeden
# → BinOp(+, Subscript(lista, indeks), 1)
```

Żeby wepchnąć arytmetykę do indeksu — nawiasy:

```
lista pod (indeksem plus jeden)
# → Subscript(lista, BinOp(+, indeks, 1))
```

Niższy od `nie`:

```
nie lista pod indeksem
# → Not(Subscript(lista, indeks))
```

Wyższy od fcall-arg primary:

```
weź dla numeru pod indeksem
# → Subscript(FCall(weź, [numer]), indeks)
# (subscript na WYNIKU fcall, bo arg to tylko primary)

weź dla (numeru pod indeksem)
# → FCall(weź, [Subscript(numer, indeks)])
```

Subscript jako LHS przypisania:

```
lista pod indeksem to jeden
```

W wartości pola struct:

```
p to Pudełko o wartości lista pod jeden
# → StructCreation(Pudełko, [StructArg(wartość, Subscript(lista, 1))])
```

---

## Zasięg i rozróżnianie wariantów

### Scope

`Scope` to symbol table dla zmiennych. Łańcuch `parent` daje hierarchię
**bloków**: moduł → funkcja → ciało `jeśli`/`dopóki`/`dla`/gałęzi `czym
jest`. `variables` to `set` pełnych kluczy (lemmas, liczba, rodzaj)
zadeklarowanych zmiennych.

Deklaracje (sekwencyjnie, w miejscu wystąpienia):

- Top-level: `Assignment` na poziomie modułu (LHS, jeśli to prosta zmienna).
- W funkcji: każdy `Param` dodawany do function-scope.
- W bloku: `Assignment` deklaruje zmienną w bloku, w którym stoi —
  chyba że zmienna jest już widoczna (także z bloku nadrzędnego); wtedy
  to reasignacja. Deklaracje z bloku-dziecka NIE są widoczne po bloku.
- Zmienna pętli `dla` oraz pola związane w gałęzi `czym jest` żyją
  w scope swojego bloku.

**Każde użycie zmiennej wymaga wcześniejszej deklaracji** — dotyczy to
referencji (`identifier_ref`), podstawy getter chaina (`autor postu` czyta
zmienną `post`) i skrótu `z polem` w konstruktorze (czyta zmienną o nazwie pola).
Referencja do niezadeklarowanej zmiennej to `ResolveError` już w Pass 2.

### Narrowing wariantów do scope

Gdy identyfikator nie jest funkcją, nie startuje chain'a, nie startuje
struct creation — staje się referencją (`identifier_ref`). Wtedy parser
sprawdza, które warianty (`segments` z `variants`) odpowiadają
zadeklarowanym zmiennym w scope, i odfiltrowuje resztę:

- Jeżeli **ŻADEN** wariant nie pasuje → `ResolveError`
  („nie jest zadeklarowaną zmienną w tym miejscu").
- Jeżeli **wszystkie** warianty pasują → no-op (nie ma czego zawężać).
- W przeciwnym razie → zostaje tylko te w scope.

Narrowing **nie wybiera „najlepszego" wariantu** — dispatcher
kontekstowy (fcall slot, type checker) ma to zrobić później.

Przykład: identyfikator `liście` ma 4 warianty (lista, list, liść,
liście-neutrum). Jeżeli w scope jest `listy` (gen sg `lista`, nom pl
`list`) — narrowing zostawi 2 warianty: `("lista",)` i `("list",)`.

### For-var widoczna w body

```
dla x w listy:
    dla y w x:           # x to outer for-var, widoczna
        wypisz y
```

---

## Konflikty nazw

Wszystkie sprawdzane w `_build_ctx` (przed Pass 2):

### Duplikat funkcji

Jeżeli dwie różne `FunctionDef` mają wspólną lemma-krotkę w `lemmas_set`
(różne formy powierzchniowe ale ta sama lemma kanoniczna) → `ResolveError`:

```
konflikt nazw funkcji: 'pisać' pasuje do wielu definicji
('pisać_coś' i 'pisać_innego')
```

### Pole == funkcja

Pole struct-a o lemma identycznej z którąś nazwą funkcji → `ResolveError`:

```
konflikt nazw: identyfikator nie może być jednocześnie polem i funkcją: X
```

---

## Komunikaty błędów

- `IdentifierError` — niepoprawny multi-seg identyfikator (zob. wyżej).
- `FunctionIdentifierError` — nazwa funkcji bez segmentu czasownikowego.
- `SyntaxError` — z lekkim opisem („Expected …, got …", brak `w` w `dla`,
  `:` po `można`, śmieci po `dalej`, etc.).
- `ResolveError` — wszelkie problemy semantyczne w Pass 2 (ambiguity w
  identyfikatorze, brak prawego operandu `pod`, niedopasowanie argumentu
  do parametru, nieparsowalne pozostałe tokeny).
- `NumberParseError` — wewnętrzny błąd parsera liczebników (gdy ktoś wepchnie
  nie-liczebnik do `parse_number_words`).

Wszystkie błędy są pisane po polsku.

---

## Mini-przykład: pełny program

```
definicja Użytkownika:
    identyfikator (Tekst)
    nazwa (Tekst)
    email (Tekst)
    hasło (Tekst)
    liczba_obserwujących (Liczba)


aby stworzyć_użytkownika z nazwą (Tekst) z emailem (Tekst) z hasłem (Tekst):
    zwrócić


aby zapisać_w_bazie x:
    zwrócić


aby istnieje_użytkownik z emailem (Tekst) -> Przełącznik:
    zwrócić


aby wygenerować_id:
    zwrócić


aby zarejestrować z nazwą (Tekst) z emailem (Tekst) z hasłem (Tekst) -> Użytkownik:
    jeśli istnieje_użytkownik z emailem:
        zwróć "email zajęty"
    nowy to stwórz_użytkownika z nazwą z emailem z hasłem
    identyfikator nowego to wygeneruj_id
    liczba_obserwujących nowego to zero
    zapisz_w_bazie nowego
    zwróć nowego
```

Co ten program robi:

1. Definiuje typ `Użytkownik` z 5 polami.
2. Deklaruje 4 funkcje pomocnicze (puste — przyszły runtime je wypełni).
3. Definiuje `zarejestrować` — funkcję z 3 parametrami przyimkowymi
   (`z nazwą`, `z emailem`, `z hasłem`) i typem zwrotnym `Użytkownik`.
4. W ciele:
   - sprawdza `istnieje_użytkownik z emailem` — przyimek `z` dopasowuje
     się do parametru `z emailem` w sygnaturze sprawdzanej funkcji,
   - jeżeli istnieje — wczesny `zwróć "email zajęty"`,
   - tworzy `nowy` przez shorthand `z nazwą z emailem z hasłem`,
   - przypisuje wartości do pól `identyfikator` i `liczba_obserwujących`
     (chain LHS),
   - wywołuje `wygeneruj_id` (no-arg fcall) i `zero` (liczbę słowną),
   - zapisuje do bazy i zwraca.

---

## Rzeczy które jeszcze nie istnieją

(stan z `notes`, do informacji)

- Runtime (uruchamianie programów).
- System typów (Hindley–Milner, planowane).
- Gramatyczne rozwiązywanie argumentów (głębszy dispatch).
- Stdlib: listy, `Przełącznik`, konkatenacja stringów.
- Tryb przypuszczający w nazwach funkcji (`usunąłbyś_komentarz dla usera`).
- Pętle przez `które`/`kiedy`.
- Filtrowanie argumentów fcall po prep-mandated case.
- Rozróżnianie niejednoznaczności lematu typu.

---

## Struktura repozytorium

```
.
├── gćć-python/             # Implementacja referencyjna
│   ├── gćć.py              # CLI
│   ├── lexer.py            # tokenizacja
│   ├── morph_anal.py       # SGJP loader + analyze + canonical
│   ├── preprocess.py       # operatory leksykalne (CMP/ARITH/POD/INT_LIT)
│   ├── number_parser.py    # liczby słowne
│   ├── identifier.py       # walidacja [adj] [subst] [reszta] + warianty
│   ├── ast_nodes.py        # dataclassy AST
│   ├── parser.py           # Pass 1 (definicje + sterowanie + raw Phrase)
│   ├── expression.py       # Pass 2 (gramatyka wyrażeń + dispatcher)
│   ├── pretty.py           # tree pretty-printer
│   ├── test_*.py           # pytest
│   └── …
├── test/                   # Programy testowe w Ć
│   ├── lexer_test.ć
│   ├── parser_test.ć
│   ├── parser_test2.ć
│   ├── instagram.ć
│   ├── stress_test.ć
│   ├── analizator_morfologiczny.ć  (przekład morph_anal.py na Ć)
│   ├── las.ć
│   ├── sgjp_subset.tab     # mały podzbiór SGJP do testów
│   └── subset_lemmas.txt
├── sgjp.tab                # pełna baza SGJP (niewersjonowana — gitignore)
├── make_subset.py          # generator sgjp_subset.tab
└── notes
```
