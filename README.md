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
- **Grecos** — kanał `production`. Live API `/api/sitecore/OffersList/LoadMoreOffers` zachowuje dokładne `Adults=2&Children=2` oraz `Child1`/`Child2` odpowiadające dzieciom 5 i 7 lat. Porównanie tego samego pakietu dla różnych składów grupy potwierdziło, że `Merlin_FullPriceParsed` jest ceną zależną od całej grupy, np. 9 276 zł dla exact 2+2 wobec 4 624 zł dla 2 dorosłych. Adapter rozróżnia tę wartość od `Merlin_AdultPrice`, filtruje dokładne daty wylotu, długość, lotnisko i AI, przegląda kilka stron API oraz wykonuje świeży recheck przed alarmem; brak wiarygodnej oceny/liczby opinii blokuje alarm.
- **Fly.pl** — kanał został przełączony z marketingowej strony Last Minute na właściwą wyszukiwarkę `/szukaj-wycieczek/`. Ta powierzchnia ma osobne pola dorosłych/dzieci, lotniska Warszawa-Modlin, Warszawa-Okęcie i Warszawa-Radom, filtry All Inclusive, liczbę opinii TripAdvisor oraz obok ceny `/os.` osobną cenę oznaczoną `za wszystkich`. Diagnostyka rozszerza teraz śledzenie serializacji uczestników w kodzie JS. `Za wszystkich` nie zostanie zaakceptowane jako cena rodzinna, dopóki wynik nie zachowa dokładnie 2+2 z wiekiem 5/7.
- **Nekera** — strona jest dostępna; diagnostyka sieciowa wykryła dedykowane skrypty formularza i ofert (`searchbarListingForm.js`, `searchbarBaseForm.js`, `pluginOfferCollection.js`). Diagnostyka śledzi obecnie serializację uczestników w JS zamiast zgadywać parametry z DOM.
- **Oasis Tours** — kanał ma własny workflow `source-12-oasis_pl.yml`; diagnostyka śledzi serializację uczestników w kodzie strony, ale dokładne 2+2 i końcowa cena nie są jeszcze potwierdzone.
- **Coral Travel, Join UP!, eSky, TraveliGo** — nadal wymagają alternatywnej drogi dostępu z powodu blokad lub braku użytecznej treści w środowisku headless.

### Stabilność diagnostyki

Workflowy diagnostyczne dla głównych i drugorzędnych adapterów mają osobne grupy `concurrency` zależne od typu zdarzenia i numeru issue. Dzięki temu raport z jednego kanału nie anuluje poprawnego testu innego źródła tylko dlatego, że oba zostały uruchomione niemal jednocześnie.
