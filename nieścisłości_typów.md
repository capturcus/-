# Nieścisłości systemu typów — katalog ze stress-testu (2026-07-11)

Wynik rozległego stress-testu: zagnieżdżone typy, mieszanie wolnych
parametrów z konkretami, unie na wszystkich poziomach, strzałki jako
wartości. **Stan po sesji napraw: wszystkie pozycje rozwiązane** —
`bad/` znów pusty, reprodukcje żyją jako testy (e2e w `test/`,
negatywne w pytest).

## Dziury soundness — NAPRAWIONE

### 1. Wynik łańcucha o wielu kandydatach gubił argumenty typów ✔
Fold dodawania po liście ZNAKÓW przechodził typechecker (wynik łańcucha
generycznego pola był dysjunkcją po samych głowach, bez powiązania
argumentów z bazą) i wybuchał w runtime.

**Naprawa**: sprzężenia dysjunkcji (`Zmienna.zależne`) — kolaps
alternatyw bazy wiąże każdy zależny wynik łańcucha z typem pola
ZWYCIĘSKIEGO kandydata (kopiowane przy instancjacji). Testy:
`test_wynik_łańcucha_kontaminacja_odrzucona` (negatywny),
`test_wynik_łańcucha_sprzężony_z_kandydatem` + e2e
`test/kandydaci_łańcucha.ć` (pozytywne).

### 2. Pola luźne (granica dynamiczna) — ZAKAZANE ✔
Pole typu generycznego bez związania parametru (`zapas (Lista)`)
oznaczało nieśledzoną zawartość: błędne założenie czytelnika wybuchało
w runtime, dwa odczyty mogły przyjąć sprzeczne typy.

**Naprawa (decyzja projektowa)**: typ pola musi być W PEŁNI ZWIĄZANY —
parametrem struktury (wprost albo przechwytem po nazwie) albo konkretem
w aplikacji nazwanej. Walidacja `_check_pola_związane` z receptą obu
napraw w komunikacie. Zmigrowano: test/ (brainfuck ×2, unia_pola),
manual_test/ (wąż, instagram, analizator, wyrażenia — po ~5–15 pól).
README zaktualizowane (sekcja Struktury + Pułapki). Testy:
`test_pole_luźne_zakazane`, `test_pole_luźne_zakaz_częściowa_aplikacja`,
`test_pole_związane_wszystkie_formy_legalne`.

Uwaga: `instagram.ć`, `analizator_morfologiczny.ć` i `wyrażenia.ć` miały
związane pola, ale pozostawały w stanie legacy sprzed tej sesji (brak
aliasu `Tekst` po zdjęciu Tekstu z builtinów; ich własna `PustaLista`
nie zgadzała się z desugarem literałów do `Nic`). Migracja przygrywkowa
wykonana 2026-07-22 — oba programy typują się i uruchamiają (kontenery
z przygrywki, podział tekstu z operacje_tekstowe.ć, IO instagrama
zasymulowane wypisem, bo externy `można` nie miały implementacji).

## Crash typecheckera — NAPRAWIONY

### 3. Nieskończona rekursja diagnostyki ✔
Konflikt argumentów tej samej głowy + odczyt pola/adnotacja →
RecursionError (raise z poszlakownikiem → render typów → materializacja
→ raise…).

**Naprawa dwutorowa**: (a) flaga reentrancji `_w_diagnostyce` — podczas
budowy komunikatu materializacja nie rzuca (render „?"); (b) sam
wyzwalacz zniknął dzięki punktowi 7. Testy:
`test_join_z_odczytem_pola_czysty_błąd`,
`test_join_z_adnotacją_czysty_błąd`.

## Błędy semantyki — NAPRAWIONE

### 4. Łańcuch czytał pole po samej lemmie ✔
`formy papieru` zwracało wartość pola `forma` (pierwszy wariant
wygrywał); pole `formy` było nieosiągalne.

**Naprawa**: `_find_field_for_ident` zbiera trafienia po PEŁNYM kluczu
wszystkich wariantów; wiele różnych pól → głośna niejednoznaczność
z receptą („nazwij pola rozróżnialnie w każdej odmianie") — cichy
hazard zamieniony w błąd w duchu istniejących kolizji morfologicznych.
Test: `test_pola_tej_samej_lemmy_niejednoznaczny_odczyt`.

### 5. Gołe `zastosuj` jako instrukcja było no-opem ✔
**Naprawa**: gałąź `Apply`/`Bind`/`TryCall` w `execute_block` — bare
wywołanie wartości funkcyjnej wykonuje się dla efektów. Test e2e:
`test/zastosuj_jako_instrukcja.ć`.

## Nieścisłości — NAPRAWIONE

### 6. Fakty strzałkowe i konkretne współistniały cicho ✔
**Naprawa**: `_dodaj_dolną` odrzuca mieszankę ARROW/nie-ARROW
natychmiast („wartość funkcyjna i zwykła wartość nie łączą się w żadnej
unii"). Test: `test_strzałka_i_konkret_konflikt_natychmiast`.

### 7. Join faktów tej samej głowy nie unifikował argumentów ✔
`zbiór to Ogniwo[Liczba]; zbiór to Ogniwo[Znak]` przechodziło cicho
(konflikt dopiero przy odczycie — i to rekursją, p. 3).

**Naprawa (decyzja)**: `_dodaj_dolną` unifikuje argumenty joinów tej
samej głowy NATYCHMIAST (`_inwariantnie` — konflikt w linii
przypisania-sprawcy, z rodowodem parametru). Test:
`test_join_tej_samej_głowy_unifikuje_argumenty_natychmiast`.

### 8. Łańcuch wielopoziomowy przez pole generyczne pękał ✔
`głowa głowy macierzy` odpadało mimo znanych faktów (kandydaci chodzą
po deklaracjach; zejście trafiało w wolny parametr).

**Naprawa**: dzielenie łańcucha (`_resolve_chain` rekurencyjnie) — gdy
żaden kandydat nie domyka całości, ogniwo wewnętrzne rozwiązuje się
osobno, a reszta na jego wyniku; fakty płyną przez sprzężone instancje.
Bonus: błędy łańcuchów wskazują teraz konkretny typ podstawy („pole
'imię' nie występuje w typie ['Znak']"). Test e2e:
`test/łańcuch_przez_generyczne_pole.ć`.

### 9. Materializacja joinu gubiła argumenty unii ✔
Zmienna z faktami `Kubeł[Liczba]`+`Worek[Liczba]` renderowała się jako
`Pojemnik[?]`.

**Naprawa**: materializacja joinu buduje instancję unii, której świeże
sloty dostają wkłady członków jako granice dolne (bez mutacji
oryginałów) — render pokazuje `Pojemnik[Liczba]`. Test: zaostrzona
asercja w `test_unia_współdzielony_parametr_przepływa`.

## Sprawdzone i SOUND (stress test tego nie ruszył)

- kontrawariancja strzałek w obu kierunkach,
- jednorodność list przez granice funkcji i głębokości zagnieżdżenia,
- samozastosowanie (`zastosuj operację z operacją`) — typ rekurencyjny
  bez occurs-checka, działa i nie wiesza solvera,
- strzałki jako elementy list + `wskaż` + dopasowanie + `zastosuj`,
- zagnieżdżony `Rezultat` (odpakowanie dokładnie raz),
- przepływ elementu przez 3-poziomową hierarchię unii (sloty po nazwie),
- przecięcie kandydatów po dwóch polach („coś, co ma wagę i uszko"),
- pole o nazwie własnego parametru, element `Nic`, thunk builtina
  używany wielokrotnie, monomorficzność domknięć (świadomy rank-1).

### 10. Rekursja diagnostyki w `_nota_o_głowie` (znaleziona później) ✔
Cykliczny graf granic (zapis przez łańcuch sprzęga bazę z instancją
w obie strony) zapętlał wędrówkę po notach — RecursionError przy
budowie komunikatu o zawężeniu.

**Naprawa**: zbiór odwiedzonych w `_nota_o_głowie` (jak w pozostałych
wędrowcach). Test: `test_zapis_warunkowy_poszerza_element_czysty_błąd`
(przy okazji dokumentuje niewrażliwość na przepływ sterowania: zapis
pod `jeśli` poszerza element bezwarunkowo).

## Runda 2 — przegląd przedprodukcyjny (2026-07-11, wieczór)

Bateria 18 sond krzyżujących funkcjonalności wg klas błędów znanych
z produkcyjnych typecheckerów (value restriction z OCamla, ucieczka
skolemów z Haskella, kowariancja pól ze starej Scali, dywergencja
solvera na typach cyklicznych/occurs-check).

### 11. CRASH: typ cykliczny przez mutację slotu elementu ✔
`bad/p01_typ_cykliczny_przez_mutację.ć`:

    węzeł to Ogniwo o głowie pięć o ogonie Nic
    głowa węzła to węzeł          # element := Ogniwo[element] — cykl W TYPIE
    wypisz zmierz węzeł

→ dawniej surowy RecursionError w pętli `_render_typu ↔
_zmaterializuj`. Dwie przyczyny, dwie naprawy: (a) budowa komunikatu
joinu renderowała argumenty konkretów, a render materializował tę samą
zmienną — regres PRZED rzuceniem wyjątku; teraz treści diagnoz powstają
pod flagą `_w_diagnostyce` (`_zbuduj_diagnozę`), więc zagnieżdżona
materializacja zwraca None („?"); (b) ścieżka SUKCESU joinu tworzyła
świeże sloty przy każdej materializacji, więc render poprawnego typu
rekurencyjnego (μt.Ogniwo[t] przez `głowa węzła to węzeł` na liście
z Nic) nigdy nie domykał cyklu — teraz join jest memoizowany per
zmienna (wersjonowanie liczbą granic, bo granice tylko rosną).
Testy: `test_cykl_w_slocie_elementu_czysty_błąd` (konflikt → czysty
komunikat z poszlakami), `test_cykl_w_slocie_przez_unię_przechodzi`
(poprawny μ-typ + wymuszony render).

### 12. KOMUNIKAT: zagnieżdżone dopasowanie na zawężonym podmiocie ✔
`okaz jest: Kotem: okaz jest: Psem:` → „gałęzie — Pies — nie
odpowiadają członkom żadnego zadeklarowanego typu wariantowego" —
fałszywa diagnoza (Pies JEST członkiem Zwierzę). NAPRAWIONE: pętla
znanych głów rozpoznaje głowę-strukturę — „dopasowanie na wartości
o znanym typie 'Kot' — żadna z gałęzi (Pies) nie obejmuje 'Kot';
jeśli podmiot został już zawężony zewnętrznym `jest:`, wewnętrzne
dopasowanie widzi wyłącznie 'Kot'". Test:
`test_zagnieżdżony_match_na_zawężonym_podmiocie`.

### 13. KOMUNIKAT: odczyt pola na wartości funkcyjnej ✔
`waga rzeczy` gdy rzecz to domknięcie → dawniej „nie występuje
w typie ['→']". NAPRAWIONE: „pole 'waga' czytane z WARTOŚCI FUNKCYJNEJ
typu (Liczba) → Liczba — funkcje nie mają pól; wywołanie to
'zastosuj … z …'". Test:
`test_odczyt_pola_z_wartości_funkcyjnej_komunikat`.

### Potwierdzone SOUND w rundzie 2 (14 krzyżówek)
- samozastosowanie + arytmetyka na wyniku → czysty błąd (render typu
  cyklicznego strzałek bezpiecznie ucina „…"),
- `zwiąż` własnej funkcji we własnym ciele (self-closure w SCC) → działa,
- polimorficzna pustka z funkcji, dwa niezależne światy elementów →
  działa (brak problemu value restriction: świeża instancja typu
  + świeży obiekt per wywołanie); jedna zmienna z dwoma elementami →
  natychmiastowy konflikt,
- strzałki w polu WSPÓLNYM unii (przez parametr-slot) + `zastosuj`
  przez unię + `zwiąż` z pola wspólnego → działają,
- zapis pola wspólnego POD-unii w gałęzi zawężającej → działa,
- łańcuchowe generyki (kolaps kandydatów przez dwie kopie sygnatur),
- `zwiąż` wyniku aplikacji zwracającej strzałkę → działa (ponad
  dokumentowane ograniczenie),
- TryCall jako podmiot dopasowania; `jako` + reasignacja aliasu,
- rekurencyjna aplikacja parametru `Drzewo dla (Drzewo dla rzeczy)`,
- remis dwóch minimalnych unii przy polu wspólnym → czysty błąd remisu.

## Runda 3 — testy skradzione z suit innych kompilatorów (2026-07-12)

Nowy katalog **`test_skradzion/`**: 13 scenariuszy zachowań systemów
typów zaczerpniętych z suit OCamla (typing-poly/rectypes/misc), Flow
(refinements/recursive_defs), Crystala (semantic: if/union/recursive
struct) i TypeScriptu (narrowing/excess property), przepisanych na
oryginalne programy w Ć. Runner jak w `test/` + rozszerzenie: pary
`NAZWA.ć`+`NAZWA.błąd` to testy NEGATYWNE (program ma odpaść, stderr
musi zawierać wzorce). Stan: **13/13 przechodzi**.

Runda 4 (po naprawie #14): +15 scenariuszy → **28/28** (occur check,
monomorfizm parametru vs generalizacja po SCC, przecięcie strzałek
w martwym kodzie, currying, funkcja częściowa, havoc po wywołaniu —
w Ć zawężenie przeżywa, poszerzanie argumentów tej samej głowy, gałąź
spoza unii, hierarchia unii, generyk dwuparametrowy, migawka
domknięcia zwiąż, wariancja strzałek w OBU kierunkach, opcjonalność
przez Nic). **Zero nowych dziur** — wszystko albo przechodzi zgodnie
z semantyką, albo odpada z czystym, pouczającym komunikatem. Warte
odnotowania zachowania na granicy: samoaplikacja typuje się w ciele
jako μ-strzałka (jak OCaml z -rectypes), konflikt ujawnia wywołanie;
niewywoływana funkcja o parametrze użytym na dwóch niezgodnych typach
typuje się (przecięcie po stronie ujemnej, MLsub-zgodne) i jest
niewywoływalna; kontrawariancja parametru strzałki działa w kierunku
zdrowym, a niezdrowy odpada z receptą zawężenia.

### 14. DZIURA: zawężenie nieunieważniane przez przypisanie do podmiotu ✔
Scenariusz wprost z suity refinements Flow („refinement invalidation"):

    okaz (Zwierzę) to Kot o imieniu 'm'
    gdy okaz jest:
        Kotem:
            okaz to Pies o kości 'k'     # zapis idzie na ZEWNĄTRZ…
            wypisz imię okazu            # …ale cień gałęzi dalej mówił Kot

Typechecker PRZEPUSZCZAŁ odczyt `imię`, runtime czytał `imię` z Psa →
brak pola. Rozważona i ODRZUCONA naprawa: kasowanie cienia w miejscu
zapisu (porządek tekstowy). Kontrprzykład — pętla wewnątrz gałęzi
wykonuje odczyt sprzed zapisu również PO nim (krawędź powrotna):

    Kotem:
        dopóki prawda:
            wypisz imię okazu            # tekstowo PRZED zapisem…
            okaz to Pies o kości 'k'     # …dynamicznie także PO nim

**Naprawa (bez analizy przepływu, w duchu „ograniczenie z istnienia
kodu")**: cień zawężenia dostaje wyłącznie gałąź, która NIGDZIE nie
przepisuje podmiotu (`_cień_i_ciało` + rekurencyjny skan
`_linia_zapisu_do` przez zagnieżdżone jeśli/dopóki/jest:). Poprawność:
wiązania `z …` i alias `jako` to migawki wartości z wejścia do gałęzi,
funkcje nie mogą przepisać cudzej zmiennej lokalnej, więc bez zapisu
w gałęzi wartość podmiotu między strażnikiem wariantu a odczytem się
nie zmienia. Idiom kursora przechodzi bez zmian (czyta przez wiązania).
Gałąź bez cienia dokleja do swoich błędów wskazówkę z linią zapisu
i remediami (wiązania/alias, ponowne `jest:` po zapisie). Testy:
`test/zawężenie_unieważnione(.ć/_pętlą.ć)` (negatywne — runner test/
umie już pary `.ć`+`.błąd`), `test/zawężenie_po_zapisie.ć` (pozytyw),
7 pytestów w test_typechecker.py.

### 15. BUG diagnostyki runtime: `_brak_pola` wywala się na frozensecie ✔
Przy okazji #14: zamiast komunikatu o brakującym polu executor padał
z `TypeError: 'frozenset' object is not subscriptable`
(`nazwa = "_".join(keys[0][0])` zakładał inny kształt klucza; scope-keys
to frozenset krotek). Naprawione deterministycznym wyborem nazwy:
`min(("_".join(k[0]) for k in keys), default="?")`; test w
test_diagnostyka.py.

## Pozostałe rysy (świadomie poza zakresem tej sesji)

- surowe tracebacki Pythona z builtinów (`ord()`, `+`) przy błędach
  runtime zamiast `CRuntimeError` z Ć-owym stosem — do owinięcia.
