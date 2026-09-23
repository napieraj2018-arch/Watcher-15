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

Stan produkcyjny pozostaje celowo konserwatywny: **7 kanałów produkcyjnych** — Wakacje.pl, TUI Poland, ITAKA, Rainbow, Sun & Fun, EXIM tours i Grecos. Kanał jest promowany dopiero po zachowaniu dokładnego składu 2+2 (dzieci 5 i 7 lat), potwierdzeniu bieżącej dostępności i odczytaniu końcowej ceny całej rodziny. Dodatkowe filtry jakościowe działają fail-closed: brak wiarygodnych danych nie może zostać zastąpiony danymi z sąsiedniej oferty ani luźną heurystyką.

Najważniejsze ustalenia:
- **EXIM tours** — kanał `production`. Żywe karty zachowują `AC1=2`, `KC1=2`, `KA1=5|7`, pokazują „2 dorosłych 2 dzieci”, stan „Dostępne online” oraz osobną `Cena całkowita` obok ceny `Dorosły od`. Walidacja na szerszym oknie potwierdziła rodzinne sumy niezależne od ceny dorosłego (m.in. 12 616 zł dla rodziny przy 5 369 zł dla dorosłego). Produkcyjny watcher nadal stosuje ścisłe okno 1–3 dni, 5–8 nocy, właściwe lotniska i fail-closed dla jakości; przy braku ofert w bieżącym oknie poprawnie zwraca 0 bez alarmu.
- **Travelplanet** — interfejs przyjmuje 2 dorosłych i dzieci 5/7, ale podczas przejścia do wyników obecny przepływ automatyczny gubi dzieci i serializuje wyszukiwanie jak dla samych dorosłych. Taki wynik jest blokowany jako niebezpieczny dla alarmów. Diagnostyka analizuje bundlowany kod frontendu i sposób serializacji occupancy, aby odtworzyć prawidłowy payload zamiast zgadywać parametry.
- **Sun & Fun** — pełny test żywego wyszukiwania `room1=2,5,7` potwierdził „2 dorosłych 2 dzieci”, dokładną datę wylotu, konkretną dostępną ofertę i jawną końcową **„Cena całkowita 8 304 zł”**. Kontrola date-drift odrzuca wyniki, w których serwis sam przesuwa wylot. Parser jakości wymaga, aby gwiazdki, ocena, liczba opinii i cena należały do tego samego bloku oferty; brak kompletnej jakości blokuje alarm, ale nie unieważnia zweryfikowanego kanału cenowo-dostępnościowego. Dedykowany adapter Sun & Fun jest podłączony także do ogólnego `channel_runner.py`.
- **Grecos** — kanał `production`. Live API `/api/sitecore/OffersList/LoadMoreOffers` zachowuje dokładne `Adults=2&Children=2` oraz `Child1`/`Child2` odpowiadające dzieciom 5 i 7 lat. `Merlin_FullPriceParsed` został zweryfikowany jako cena zależna od składu grupy: dla tego samego pakietu porównujemy 2+2 z osobnym zapytaniem 2+0; jeżeli odpowiednika 2+0 nie ma, rekord przechodzi tylko wtedy, gdy końcowa suma jest większa niż suma dwóch cen `Merlin_AdultPrice`, dzięki czemu cena dla dwóch dorosłych nie może zostać uznana za rodzinną. Końcowy smoke test zwrócił dwie bieżące oferty 2+2 z Warszawy za 15 020 zł i 15 232 zł; matcher lotniska został poprawiony, aby surowe `Warszawa` nigdy nie było fałszywie oznaczane jako `Warszawa-Radom`. Link prowadzi teraz do właściwej strony hotelu. Przed alarmem wykonywany jest świeży recheck API, a brak wiarygodnej oceny/liczby opinii nadal blokuje alert.
- **Fly.pl** — dokładna serializacja rodziny jest już potwierdzona w żywym URL wyników: `filter[person]=2`, `filter[child]=2`, `filter[childAge][1]=01-01-2021` i `filter[childAge][2]=01-01-2019`. Wyszukiwarka ma lotniska Warszawa-Modlin, Warszawa-Okęcie i Warszawa-Radom, filtry All Inclusive, TripAdvisor oraz osobny tryb ceny `za wszystkich`. Kanał pozostaje `diagnostic`, bo końcowy total musi jeszcze zostać potwierdzony jako zależny od tego exact 2+2, a nie tylko jako alternatywny widok ceny dla dorosłych.
- **Nekera** — dokładne 2+2 jest już potwierdzone: zapytanie `adults=2` z dwoma powtarzanymi parametrami `child=2021-01-01` i `child=2019-01-01` przechodzi do `/hotels/` i pozostaje w stanie wyników. Nekera ujawniła również właściwy przełącznik `pricetype=1` oznaczający `za wszystkich`; diagnostyka porównuje teraz te same oferty exact 2+2 z osobnym zapytaniem 2+0. Dopóki ten test nie wykaże party-sensitive family total i bieżącej dostępności konkretnej oferty, kanał nie awansuje do `production`.
- **Oasis Tours** — backend BlueVendo został zlokalizowany jako `POST /api-bv/search-search`; w działającym zapytaniu widzimy m.in. `adults=2`, daty, długość i region. Osobny workflow analizuje bundlowany kod Next.js w celu ustalenia dokładnego pola dzieci i wieku. Obecny test UI nadal wysyła adults-only, więc nie wolno jeszcze ufać jego cenom jako 2+2.
- **Coral Travel, Join UP!, eSky, TraveliGo** — nadal wymagają alternatywnej drogi dostępu z powodu blokad lub braku użytecznej treści w środowisku headless.

### Stabilność diagnostyki

Workflowy diagnostyczne dla głównych i drugorzędnych adapterów mają osobne grupy `concurrency` zależne od typu zdarzenia i numeru issue. Dzięki temu raport z jednego kanału nie anuluje poprawnego testu innego źródła tylko dlatego, że oba zostały uruchomione niemal jednocześnie.

### Grecos — production gate

Grecos jest kanałem `production`, ale alarmy pozostają fail-closed. Adapter wymaga exact 2+2 (5/7), żywej ceny rodzinnej zależnej od składu, terminu 1–3 dni, 5–8 nocy, All Inclusive, właściwego lotniska i ponownego sprawdzenia API. Brak wiarygodnej oceny >=8.0 lub liczby opinii >=30 oznacza brak alarmu, a nie obchodzenie filtra. Workflow kanału działa niezależnie co 15 minut.
