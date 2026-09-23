# Watcher-15

Stały system monitoringu uruchamiany automatycznie przez GitHub Actions co 15 minut.

## Aktywny watcher — wakacje last minute 2+2

- 2 dorosłych + dzieci w wieku 5 i 7 lat
- maksymalnie **7000 zł łącznie**
- All Inclusive / Ultra All Inclusive
- wylot w ciągu **1–3 dni**
- **5–8 nocy**
- priorytet **Warszawa-Radom**, następnie Warszawa / Modlin
- hotel minimum **4★**
- ocena minimum **8.0/10** i co najmniej **30 opinii**
- cena musi być policzona dla dokładnie **2+2**
- przed alarmem wykonywana jest druga kontrola strony oferty i ceny rodzinnej
- powtórny alert tej samej oferty dopiero po spadku ceny o co najmniej 250 zł

## Alarmy

Po znalezieniu zweryfikowanej oferty system tworzy GitHub Issue i przypisuje je do konta `napieraj2018-arch`, dzięki czemu GitHub może wysłać powiadomienie zgodnie z ustawieniami konta.

## Odporność

Watcher działa co 15 minut z przesunięciem względem pełnych kwadransów, przechodzi przez kilka stron najtańszych wyników i ma miesięczny keepalive, aby harmonogram publicznego repozytorium nie wygasł po długiej bezczynności.

## Kolejne watchery

Reguły są w `config/watchers.json`. Ten sam mechanizm może później służyć do monitorowania lotów, cen produktów, samochodów, nieruchomości i innych wyszukiwań.

## Architektura wielu źródeł

Watcher-15 ma rejestr **15 niezależnych kanałów** w `config/channels.json`.

Statusy:
- `production` — kanał może generować alarm dopiero po potwierdzeniu dokładnie 2 dorosłych + dzieci w wieku 5 i 7 lat, bieżącej dostępności oraz końcowej ceny całej rodziny.
- `diagnostic` — źródło działa technicznie i jest w trakcie mapowania formularza/rezerwacji.
- `registered` — kanał jest zarejestrowany i czeka na pełny adapter.
- `blocked_*` — serwis blokuje zwykły automat; nie może być traktowany jako główne źródło.

Reguła bezpieczeństwa: cena `/os.`, cena dla 2 dorosłych albo cena z listingu bez potwierdzenia składu grupy **nigdy nie może uruchomić alarmu**.

### Aktualny zestaw 15 kanałów

Wakacje.pl, TUI Poland, ITAKA, Rainbow, Coral Travel, Travelplanet, Fly.pl, EXIM tours, Join UP! Polska, Nekera, Grecos, Sun & Fun, eSky Wakacje, TraveliGo oraz Oasis Tours.

Co godzinę działa lekki health-check wszystkich źródeł. Raz dziennie uruchamia się diagnostyka struktury formularzy dla kanałów nieprodukcyjnych. Produkcyjne adaptery ofertowe działają niezależnie i mogą być uruchamiane co 15 minut.

## Diagnostyka 2026-09-23

Stan produkcyjny pozostaje celowo konserwatywny: **9 kanałów produkcyjnych** — Wakacje.pl, TUI Poland, ITAKA, Rainbow, EXIM tours, Travelplanet, Grecos, Sun & Fun i Oasis Tours. Kanał jest promowany dopiero po zachowaniu dokładnego składu 2+2 (dzieci 5 i 7 lat), potwierdzeniu bieżącej dostępności i odczytaniu końcowej ceny całej rodziny. Dodatkowe filtry jakościowe działają fail-closed: brak wiarygodnych danych nie może zostać zastąpiony danymi z sąsiedniej oferty ani luźną heurystyką.

Najważniejsze ustalenia:
- **EXIM tours** — kanał `production`. Żywe karty zachowują `AC1=2`, `KC1=2`, `KA1=5|7`, pokazują „2 dorosłych 2 dzieci”, stan „Dostępne online” oraz osobną `Cena całkowita` obok ceny `Dorosły od`. Walidacja na szerszym oknie potwierdziła rodzinne sumy niezależne od ceny dorosłego (m.in. 12 616 zł dla rodziny przy 5 369 zł dla dorosłego). Produkcyjny watcher nadal stosuje ścisłe okno 1–3 dni, 5–8 nocy, właściwe lotniska i fail-closed dla jakości; przy braku ofert w bieżącym oknie poprawnie zwraca 0 bez alarmu.
- **Travelplanet** — kanał `production`. Własny request wyników zachowuje `nl_occupancy_adults=2`, `nl_occupancy_children=2` i `nl_ages_children=[5,7]`; żywe rekordy ofert mają `adult:_2_child:_2`, `age:_5,7` oraz token pasażerów `AAC5C7`. Końcowy `total_summary` jest przypisany do tego samego rekordu, a produkcyjny adapter dodatkowo wymaga, aby ta sama paczka miała inną cenę w kontroli `2+0`. `originalTotalPrice` z JWT nie jest używany jako family total. Przed alarmem wykonywany jest drugi świeży odczyt 2+2.
- **Sun & Fun** — pełny test żywego wyszukiwania `room1=2,5,7` potwierdził „2 dorosłych 2 dzieci”, dokładną datę wylotu, konkretną dostępną ofertę i jawną końcową **„Cena całkowita 8 304 zł”**. Kontrola date-drift odrzuca wyniki, w których serwis sam przesuwa wylot. Parser jakości wymaga, aby gwiazdki, ocena, liczba opinii i cena należały do tego samego bloku oferty; brak kompletnej jakości blokuje alarm, ale nie unieważnia zweryfikowanego kanału cenowo-dostępnościowego. Dedykowany adapter Sun & Fun jest podłączony także do ogólnego `channel_runner.py`.
- **Grecos** — kanał `production`. Live API `/api/sitecore/OffersList/LoadMoreOffers` zachowuje dokładne `Adults=2&Children=2` oraz `Child1`/`Child2` odpowiadające dzieciom 5 i 7 lat. `Merlin_FullPriceParsed` został zweryfikowany jako cena zależna od składu grupy: dla tego samego pakietu porównujemy 2+2 z osobnym zapytaniem 2+0; jeżeli odpowiednika 2+0 nie ma, rekord przechodzi tylko wtedy, gdy końcowa suma jest większa niż suma dwóch cen `Merlin_AdultPrice`, dzięki czemu cena dla dwóch dorosłych nie może zostać uznana za rodzinną. Końcowy smoke test zwrócił dwie bieżące oferty 2+2 z Warszawy za 15 020 zł i 15 232 zł; matcher lotniska został poprawiony, aby surowe `Warszawa` nigdy nie było fałszywie oznaczane jako `Warszawa-Radom`. Link prowadzi teraz do właściwej strony hotelu. Przed alarmem wykonywany jest świeży recheck API, a brak wiarygodnej oceny/liczby opinii nadal blokuje alert.
- **Fly.pl** — pozostaje `diagnostic`. URL potrafi zawierać `filter[child]=2` i wiek 5/7, ale po renderze backendowa wartość dzieci wraca do `0`, a analityka ofert zgłasza `number_of_kids=0`. Test „Cena za wszystkich” dawał tę samą kwotę co 2+0, więc źródło jest twardo blokowane przed produkcją.
- **Nekera** — exact 2+2 jest potwierdzone: `adults=2` z `child=2021-01-01` i `child=2019-01-01` przechodzi do wyników. Jednocześnie wykryto twardy blocker: oficjalny tryb `pricetype=1` (`za wszystkich`) został porównany na 40 tych samych listingach 2+2 i 2+0 i we wszystkich przypadkach pokazał identyczny total (`party-sensitive count = 0`). Tych kwot nie wolno uznawać za rodzinne. Następna ścieżka to właściwy endpoint/szczegóły oferty, który rzeczywiście wycenia dzieci.
- **Oasis Tours** — kanał `production`. UI oraz request BlueVendo zachowują dokładnie `adults=2` i `infants=5,7`; siedem identycznych pakietów hotel/pokój/data/wyżywienie/transport przeszło kontrolę 2+2 vs 2+0, a `customertotalprice` zmieniał się wraz ze składem (np. 3102 zł vs 1926 zł). Adapter wymaga żywej dostępności, końcowej ceny rodzinnej, ścisłych filtrów 1–3 dni / 5–8 nocy / AI / lotnisko oraz drugiego rechecku; brak jakości pozostaje fail-closed.
- **Coral Travel, Join UP!, eSky, TraveliGo** — nadal wymagają alternatywnej drogi dostępu z powodu blokad lub braku użytecznej treści w środowisku headless.

### Stabilność diagnostyki

Workflowy diagnostyczne dla głównych i drugorzędnych adapterów mają osobne grupy `concurrency` zależne od typu zdarzenia i numeru issue. Dzięki temu raport z jednego kanału nie anuluje poprawnego testu innego źródła tylko dlatego, że oba zostały uruchomione niemal jednocześnie.

### Grecos — production gate

Grecos jest kanałem `production`, ale alarmy pozostają fail-closed. Adapter wymaga exact 2+2 (5/7), żywej ceny rodzinnej zależnej od składu, terminu 1–3 dni, 5–8 nocy, All Inclusive, właściwego lotniska i ponownego sprawdzenia API. Brak wiarygodnej oceny >=8.0 lub liczby opinii >=30 oznacza brak alarmu, a nie obchodzenie filtra. Workflow kanału działa niezależnie co 15 minut.

### Kontrola bezpieczeństwa Fly.pl — 2026-09-23

Fly.pl nie został dopuszczony do produkcji. Zapytanie przyjmuje `filter[person]=2`, `filter[child]=2` i wiek dzieci 5/7, ale wynik ofertowy nadal zachowuje się jak `2+0`. Kontrola trybu „Cena za wszystkich” wykazała te same kwoty dla 2+2 i dla 2 dorosłych (np. 1 017 zł/os. → 2 034 zł w obu przypadkach). Kanał pozostaje diagnostyczny i nie może alarmować, dopóki detal/rezerwacja nie potwierdzi ceny zależnej od obojga dzieci.

### Stan kanałów — 2026-09-23 09:40 CEST

Zweryfikowany stan `main`: **9 kanałów production** — Wakacje.pl, TUI Poland, ITAKA, Rainbow, EXIM tours, Travelplanet, Grecos, Sun & Fun i Oasis Tours. Fly.pl pozostaje diagnostic, ponieważ backend zeruje dzieci mimo parametrów 2+2; Nekera zachowuje dokładne dzieci 5/7, ale kontrola 2+2 vs 2+0 nie potwierdziła rodzinnego totalu. eSky pozostaje zablokowany HTTP 403. Statusów nie podnosimy bez exact 2+2 + live availability + końcowego family total.

### Rozszerzenie puli źródeł — Rego-Bis

Do puli dodano niezależny kanał `regobis_pl`. Serwis ma dedykowany przepływ „rodzina 2+2”, wymaga wieku/dat urodzenia dzieci i przed finalizacją ponownie sprawdza cenę oraz dostępność dla wybranego składu. Status pozostaje `diagnostic` do czasu technicznego potwierdzenia dokładnego 2+2 (5/7) i końcowej ceny rodzinnej.

### Postęp — Oasis i ANEX

Oasis został awansowany do `production` po potwierdzeniu exact 2+2, żywej dostępności i party-sensitive final total na tych samych pakietach. Dodano także ANEX Tour jako 16. niezależne źródło: żywe wiersze SAMO zawierają `adult-2 child-2`, `AGES=5,7`, wariant pokoju 2+2, dostępność i jawny PLN price. ANEX pozostaje diagnostic, dopóki kontrola tej samej oferty 2+0 nie dowiedzie, że kwota jest końcową ceną rodzinną.

### Prima Holiday — twardy dowód ceny rodzinnej

GraphQL `BluevendoFastCalculation` został sprawdzony bez polegania na cenach `/os.`. Dla dokładnej grupy `[18,18,5,7]` zwraca cztery ceny uczestników i ich sumę jako cenę wyjazdu; kontrola tego samego `tripId` dla `[18,18]` daje inny, niższy total (m.in. 1036 vs 678 PLN oraz 7476 vs 3738 PLN). Prima pozostaje `diagnostic` do czasu spięcia tego kalkulatora z żywym pakietem lotniczym 1–3 dni / 5–8 nocy oraz końcowym recheckiem dostępności, lotniska i jakości hotelu.

### Coral Travel — potwierdzony blocker pakietowy

Właściwe strony pakietowe `coraltravel.pl/tours/*` zwracają w środowisku GitHub/headless interstitial Imperva `Pardon Our Interruption`. Dostępny `booking.coraltravel.pl` ujawnia schemat wieku dzieci, etykietę `CAŁKOWITY` i GDS, ale nie jest dowodem ceny pakietu Coral. Kanał pozostaje blokowany, dopóki nie będzie można potwierdzić na powierzchni pakietowej exact 2+2 (5/7), live availability i final family total.

### Odporność Grecos na timeouty

Po rzeczywistym `ReadTimeout` w produkcyjnym teście API adapter dostał ograniczone retry dla błędów sieciowych i nadal działa fail-closed. Kolejne produkcyjne przebiegi Grecosa zakończyły się sukcesem; zasady exact 2+2 i family total nie zostały poluzowane.

### Minimum celu osiągnięte — 10 kanałów production

Po podwójnej certyfikacji live do `production` wszedł Prima Holiday. Dowód: exact 2+2 w kalkulatorze `[18,18,5,7]`, cztery ceny uczestników sumujące się do finalnego totalu 6558 PLN, ten sam trip dla 2 dorosłych = 3786 PLN, `onrequest=false`, `maxroom=20`, a drugi niezależny odczyt oferty i drugi family calculation ponownie potwierdziły 6558 PLN. Aktualna pula production: **Wakacje.pl, TUI Poland, ITAKA, Rainbow, EXIM tours, Travelplanet, Grecos, Sun & Fun, Oasis Tours, Prima Holiday**. System nadal rozwijamy w stronę 15 niezależnych kanałów.
