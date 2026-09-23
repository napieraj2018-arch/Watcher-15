# Watcher-15

Stały system monitoringu uruchamiany automatycznie przez GitHub Actions co 15 minut.

## Aktywne wyszukiwanie — 24–26.09.2026, exact 2+2

Bieżące wyszukiwanie jest przypięte do konkretnych dat, żeby harmonogram nie przesuwał się automatycznie wraz z upływem czasu:

- **rodzina:** 2 dorosłych + dzieci dokładnie 5 i 7 lat,
- **wylot:** czwartek **24.09.2026 wyłącznie od 17:00**, cały piątek **25.09.2026** albo sobota **26.09.2026**,
- **pobyt:** 5–8 nocy,
- **wyżywienie:** All Inclusive / Ultra All Inclusive,
- **lotniska:** priorytet Warszawa-Radom, następnie Warszawa i Modlin,
- **cena:** wyłącznie końcowy total za dokładne 2+2; cena /os. ani 2+0 nigdy nie kwalifikuje oferty,
- **dostępność:** żywa oferta i recheck przed alarmem,
- **link:** alarm ma prowadzić do zweryfikowanej oferty albo do dokładnie odtworzonego wyszukiwania 2+2, jeżeli serwis nie daje stabilnego URL pojedynczej karty.

System ma dwa rozłączne profile cenowo-jakościowe:

1. **OKAZJA ≤7K** — do 7000 zł za rodzinę, hotel 4★+, ocena ≥8.0/10 i ≥30 opinii.
2. **SUPER ≤11K** — 7001–11000 zł za rodzinę, hotel 4★+, ocena ≥8.5/10 i ≥100 opinii.

Każdy kanał pobiera źródło tylko raz. Dopiero po pełnej weryfikacji oferta jest przypisywana do właściwego profilu. Czwartkowa oferta bez potwierdzonej godziny wylotu jest odrzucana fail-closed. Powtórny alert tej samej oferty i profilu powstaje dopiero po spadku ceny o co najmniej 250 zł.

**Stan produkcyjny:** 11 niezależnych kanałów — Wakacje.pl, TUI Poland, ITAKA, Rainbow, Travelplanet, EXIM tours, Grecos, Sun & Fun, Oasis Tours, Prima Holiday i TanieTravel. Rozbudowa do 15 trwa dalej.

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

### Kanał 11 — TanieTravel

TanieTravel został awansowany do `production` po twardym teście API. Kanoniczny request zawiera `adults=2`, `children=2`, `childAges=5,7`, `stars=4plus`, `meal=ai` oraz lotniska WAW/WMI/RDO. Dla 20 identycznych pakietów cena 2+2 różniła się od kontroli 2+0, a wszystkie 20 pakietów wróciły ponownie w drugim świeżym zapytaniu 2+2 z identycznym family total. Adapter pozostaje fail-closed na filtrach ceny, jakości, terminu, długości pobytu, lotniska i drugiego odczytu.

Aktualny stan: **11 kanałów production**. Cel pozostaje **15**.

### Kanał nr 11 — TanieTravel production

TanieTravel został awansowany po trzech niezależnych dowodach. Oficjalny skrypt wyszukiwarki serializuje dzieci jako `ages/childAges=5,7`, All Inclusive jako `meal=ai`, a filtr 4★+ jako `stars=4plus`. Bieżąca strona wynikowa pokazała jednocześnie `2 + 2 (5, 7 lat)`, osobną `Cena za 1 osobę` oraz `Cena za 2+2 (5, 7 lat) / Kup za ... zł`, bez oznaczenia `zł/os.` przy family total. Bezpośrednie API znalazło 20 identycznych pakietów 2+2 vs 2+0 z różnymi totalami, a drugi świeży odczyt 2+2 odtworzył te same pakiety i ceny. Adapter produkcyjny wykonuje dwa odczyty rodzinne oraz osobną kontrolę 2+0 i pozostaje fail-closed dla ceny, jakości, terminu i lotniska. Aktualna pula: **11 kanałów production**.

### Dwa profile wyszukiwania + ścisłe okno wyjazdu

Aktualny monitoring 2+2 działa równolegle w dwóch profilach:

- `OKAZJA ≤7K` — cena rodzinna do 7000 PLN, hotel >=4★, ocena >=8.0/10, co najmniej 30 opinii.
- `SUPER ≤11K` — cena rodzinna 7001–11000 PLN, hotel >=4★, ocena >=8.8/10, co najmniej 100 opinii.

W obu profilach obowiązuje exact 2 dorosłych + dzieci 5 i 7 lat, All Inclusive, 5–8 nocy, właściwe lotniska i ponowna kontrola końcowej ceny rodzinnej. Aktualne okno wylotu to czwartek 24.09.2026 **od 17:00**, cały piątek 25.09.2026 oraz cała sobota 26.09.2026. Czwartkowa oferta bez potwierdzonej godziny wylotu jest fail-closed i nie może wygenerować alarmu.

Każdy alarm musi zawierać link zachowujący możliwie dokładny stan pakietu. Jeżeli źródło nie daje stabilnego deep-linku do pojedynczego pakietu, link prowadzi do dokładnie przefiltrowanego wyniku exact 2+2; nie wolno podmieniać go na luźną stronę hotelu ani ofertę 2+0.

ITAKA ma dodatkową bramkę: zachowanie konkretnego tokenu `id[0]`, obu dat urodzenia dzieci, terminu w page state oraz końcowego `Łącznie`. Wylot czwartkowy wymaga dodatkowo potwierdzonej godziny.

### Tryb poszukiwania 24–26.09.2026 — dwa progi

Aktywny search id: `family-2026-09-24-evening-26`. Każdy kanał production uruchamia dwa niezależne profile: **OKAZJA ≤7K** (0–7000 PLN, min. 4★, 8.0/10, 30 opinii) oraz **SUPER ≤11K** (7001–11000 PLN, min. 4★, 8.8/10, 100 opinii). Oba wymagają exact 2+2 z dziećmi 5/7, 5–8 nocy, All Inclusive, końcowego family total i świeżej dostępności. Wyloty: czwartek 24.09 wyłącznie po 17:00, piątek 25.09 cały dzień, sobota 26.09 cały dzień. Jeżeli kanał nie potrafi potwierdzić godziny czwartkowego wylotu, czwartkowa oferta jest fail-closed i nie może alarmować. Link do oferty/wyszukiwania exact-family jest obowiązkowy w każdym alercie.
