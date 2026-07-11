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

Uwaga: `instagram.ć`, `analizator_morfologiczny.ć` i `wyrażenia.ć` mają
związane pola, ale pozostają w stanie legacy sprzed tej sesji (brak
aliasu `Tekst` po zdjęciu Tekstu z builtinów; ich własna `PustaLista`
nie zgadza się z desugarem literałów do `Nic`) — osobna migracja
przygrywkowa, poza zakresem napraw typów.

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

## Pozostałe rysy (świadomie poza zakresem tej sesji)

- surowe tracebacki Pythona z builtinów (`ord()`, `+`) przy błędach
  runtime zamiast `CRuntimeError` z Ć-owym stosem — do owinięcia,
- legacy manual_test (patrz uwaga w p. 2).
