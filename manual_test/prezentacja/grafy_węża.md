# Dwa grafy węża — materiał na slajd „Maszyna"

Oba grafy dotyczą `manual_test/wąż.ć` (z włączonym `gra.ć` i przygrywką).

Gotowe rendery obok: `krata.svg`/`krata.png` i `granice.svg`/`granice.png` (wygenerowane mermaid-cli — do wstawienia w slajdy
bez żadnych wtyczek). Podgląd Mermaida w VS Code wymaga rozszerzenia
„Markdown Preview Mermaid Support" (Matt Bierner); identyfikatory
węzłów poniżej są ASCII-owe (etykiety w cudzysłowach niosą polskie
znaki), bo znaki diakrytyczne w ID i kropki w nienazwanych
podgrafach wywracają część rendererów.

## Graf 1: krata nominalna (graf członków unii) — „mapa świata"

Statyczna, zbudowana raz z deklaracji `albo`; strzałka = „jest
zadeklarowanym członkiem". Cykle zakazane. `⟨element⟩` oznacza parametr
typu (unie dziedziczą go po nazwach członków).

```mermaid
flowchart BT
    subgraph B["builtiny"]
        Liczba["Liczba"]
        Znak["Znak"]
        Przelacznik["Przełącznik"]
        Nic["Nic"]
    end

    subgraph P["przygrywka.ć"]
        Ogniwo["Ogniwo⟨element⟩"]
        Lista["Lista⟨element⟩"]
        Tekst["Tekst (alias)"]
        Sukces["Sukces⟨element⟩"]
        Blad["Błąd"]
        Rezultat["Rezultat⟨element⟩"]
        Ogniwo --> Lista
        Sukces --> Rezultat
        Blad --> Rezultat
        Tekst -. "alias: Lista o elemencie Znak" .-> Lista
    end

    subgraph G["gra.ć"]
        Barwa["Barwa"]
        Nacisniecie["Naciśnięcie"]
        Klikniecie["Kliknięcie"]
        Ruch["Ruch"]
        Wydarzenie["Wydarzenie"]
        Nacisniecie --> Wydarzenie
        Klikniecie --> Wydarzenie
        Ruch --> Wydarzenie
    end

    subgraph W["wąż.ć"]
        Pole["Pole"]
        Pelzanie["Pełzanie"]
        Porazka["Porażka"]
        Rozgrywka["Rozgrywka"]
        Pelzanie --> Rozgrywka
        Porazka --> Rozgrywka
    end

    Nic --> Lista

    classDef unia fill:#ffe8e8,stroke:#c00,stroke-width:2px
    classDef alias fill:#f4f4f4,stroke:#999,stroke-dasharray:4
    class Lista,Rezultat,Wydarzenie,Rozgrywka unia
    class Tekst alias
```

Węzły bez strzałek wychodzących (Pole, Barwa, Liczba, Znak, Przełącznik)
to typy poza wszelkimi uniami — ich join z czymkolwiek innym nie
istnieje. Jedyny węzeł w dwóch rodzinach: `Nic` (builtin ORAZ członek
Listy).

## Graf 2: graf granic — „sieć dróg tego programu" (wycinek: pętla stanu)

Dynamiczny, budowany z każdej linijki; `α` = zmienna typowa (węzeł),
krawędź = granica z poszlaką (linia + kontekst). Prostokąty = konkrety
(fakty-liście), podwójne kółka = zmienne typowe, romb = zapytanie do
KRATY (join), sześciokąt = wymaganie.

```mermaid
flowchart LR
    K3["Porażka o powodzie 'ściana' (l.93)"]
    K4["Porażka o powodzie 'własny ogon' (l.95)"]
    K5["Pełzanie — zjedzenie owocu (l.98)"]
    K6["Pełzanie — zwykły ruch (l.99)"]
    RetPelznij(("α wynik pełznąć"))
    K3 -- "zwrot" --> RetPelznij
    K4 -- "zwrot" --> RetPelznij
    K5 -- "zwrot" --> RetPelznij
    K6 -- "zwrot" --> RetPelznij

    JOIN{"KRATA: Pełzanie ⊔ Porażka = Rozgrywka"}
    RetPelznij -.-> JOIN

    Rozgrywka(("α rozgrywka — parametr przestawić"))
    RetPrzestaw(("α wynik przestawić"))
    K2["Pełzanie — klatka bez kroku (l.109)"]
    RetPelznij -- "zwróć pełznij (l.108)" --> RetPrzestaw
    K2 -- "zwrot" --> RetPrzestaw
    Rozgrywka -- "zwróć rozgrywkę (l.111)" --> RetPrzestaw

    K1["Pełzanie — konstrukcja startowa (l.130)"]
    Stan(("α stan"))
    K1 -- "przypisanie (l.130)" --> Stan
    RetPrzestaw -- "stan to przestaw (l.134)" --> Stan
    Stan -- "argument 1 wywołania przestaw (l.134)" --> Rozgrywka

    Kandydat{"łańcuch owoc stanu: fakty = Rozgrywka, kandydat-unia"}
    WynikPole(("α wynik łańcucha = Pole"))
    W1{{"wymaganie: kolumna to Liczba (narysuj_koło, l.136)"}}
    Stan -.-> Kandydat
    Kandydat --> WynikPole
    WynikPole --> W1

    classDef fakt fill:#e8f4e8,stroke:#2a7
    classDef zmienna fill:#fff,stroke:#333,stroke-width:2px
    classDef krata fill:#ffe8e8,stroke:#c00
    classDef wymaganie fill:#e8ecff,stroke:#36c
    class K1,K2,K3,K4,K5,K6 fakt
    class Stan,Rozgrywka,RetPelznij,RetPrzestaw,WynikPole zmienna
    class JOIN,Kandydat krata
    class W1 wymaganie
```

Dwie rzeczy do pokazania palcem:

1. **CYKL**: `α stan → α rozgrywka → α wynik przestawić → α stan`
   (argument wywołania + `zwróć rozgrywkę` + przypisanie wyniku).
   To nie patologia, tylko typowa pętla stanu gry — i powód, dla
   którego każdy wędrowiec grafu granic nosi zbiór odwiedzonych.
2. **Współpraca grafów**: różowe węzły to miejsca, gdzie solver pyta
   kratę — join czterech zwrotów pełznąć (Pełzanie ⊔ Porażka) oraz
   rozstrzygnięcie kandydata łańcucha `owoc stanu` (fakt-unia →
   odczyt pola wspólnego).

## Graf 3: graf wywołań — „w jakiej kolejności"

Krawędzie WYMIERZONE z solvera (`_wywoływane` na ciałach funkcji),
nie narysowane z pamięci. Ciągła strzałka = wywołanie wprost;
przerywana = referencja gerundialna (funkcja przekazana jako
wartość — `zwiąż namalowanie…`, fold `z obróceniem`). Żółte węzły
mają pętlę własną (samorekursja). Rendery: `wywolania.svg`/`.png`.

Tarjan na tym grafie daje dla węża **29 SCC — same singletony**
(każda żółta pętla to własny, jednofunkcyjny fixpoint). Kontrast
z repo: brainfuck.ć ma trzyfunkcyjną SCC `wykonać ↔ zapętlić ↔
obsłużyć` — tam sygnatury stabilizują się razem. Osiągalne od
`działać`: 19 z 29 funkcji (10 przygrywkowych nieużywanych
pominięto na rysunku).

```mermaid
flowchart TB
    subgraph W["wąż.ć"]
        dzialac["działać (punkt wejścia)"]
        przestawic["przestawić"]
        pelznac["pełznąć"]
        obrocic["obrócić"]
        wskazacleb["wskazać_łeb"]
        skrocic["skrócić"]
        sprawdzic["sprawdzić_obecność"]
        wylowoc["wylosować_owoc"]
        wylpole["wylosować_pole"]
        namalowac["namalować"]
        oglosic["ogłosić"]
    end

    subgraph P["przygrywka.ć (10 nieużywanych pominięto)"]
        przeksztalcac["przekształcać (mapa)"]
        zlozyc["złożyć (fold)"]
        zmierzyc["zmierzyć"]
        sklec["skleić"]
        przelozyc["przełożyć"]
        pokazac["pokazać"]
        rozwijac["rozwijać"]
        przedstawic["przedstawić"]
    end

    dzialac --> przestawic
    dzialac --> oglosic
    dzialac --> wylowoc
    dzialac --> przeksztalcac
    dzialac --> zmierzyc
    dzialac --> pokazac
    dzialac --> sklec
    dzialac -. "zwiąż (referencja)" .-> namalowac

    przestawic --> pelznac
    przestawic --> zlozyc
    przestawic -. "fold (referencja)" .-> obrocic

    pelznac --> wskazacleb
    pelznac --> skrocic
    pelznac --> sprawdzic
    pelznac --> wylowoc

    wylowoc --> wylpole
    wylowoc --> sprawdzic
    wylowoc --> wylowoc

    oglosic --> sklec
    pokazac --> rozwijac
    pokazac --> sklec
    rozwijac --> przedstawic
    rozwijac --> sklec
    rozwijac --> rozwijac
    sklec --> przelozyc
    przelozyc --> przelozyc
    skrocic --> skrocic
    sprawdzic --> sprawdzic
    zmierzyc --> zmierzyc
    zlozyc --> zlozyc
    przeksztalcac --> przeksztalcac

    classDef wejscie fill:#ffe8e8,stroke:#c00,stroke-width:2px
    classDef samorekursja stroke-dasharray:0,fill:#fffbe6,stroke:#b80
    class dzialac wejscie
    class wylowoc,skrocic,sprawdzic,zmierzyc,zlozyc,przeksztalcac,przelozyc,rozwijac samorekursja
```

Trzy grafy razem: **graf wywołań** decyduje *w jakiej kolejności*
(SCC + porządek topologiczny), **graf granic** niesie *co wiemy*
(376 α, 1391 granic dla węża), a **krata** rozstrzyga *czy to się
składa* (joiny, kandydaci).
