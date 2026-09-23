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
- `production` — kanał może generować alarm dopiero po potwierdzeniu składu grupy i ceny końcowej.
- `diagnostic` — źródło działa technicznie i jest w trakcie mapowania formularza/rezerwacji.
- `registered` — kanał jest zarejestrowany i czeka na pełny adapter.
- `blocked_*` — serwis blokuje zwykły automat; nie może być traktowany jako główne źródło.

Reguła bezpieczeństwa: cena `/os.`, cena dla 2 dorosłych albo cena z listingu bez potwierdzenia składu grupy **nigdy nie może uruchomić alarmu**.

### Aktualny zestaw 15 kanałów

Wakacje.pl, TUI Poland, ITAKA, Rainbow, Coral Travel, Travelplanet, Fly.pl, EXIM tours, Join UP! Polska, Nekera, Grecos, Sun & Fun, eSky Wakacje, TraveliGo oraz Oasis Tours.

Co godzinę działa lekki health-check wszystkich źródeł. Raz dziennie uruchamia się diagnostyka struktury formularzy dla kanałów nieprodukcyjnych. Produkcyjne adaptery ofertowe działają niezależnie i mogą być uruchamiane co 15 minut.

## Diagnostyka 2026-09-23

Stan produkcyjny pozostaje celowo konserwatywny: **4 kanały produkcyjne** — Wakacje.pl, TUI Poland, ITAKA i Rainbow. Kanał jest promowany dopiero po zachowaniu dokładnego składu 2+2, potwierdzeniu dostępności i odczytaniu końcowej ceny całej rodziny.

Najważniejsze ustalenia:
- **EXIM tours** — rozpoznano parametry dokładnej rodziny: `ac1=2`, `kc1=2`, `ka1=5|7`. Rozpoznano też identyfikatory lotnisk: Warszawa `3850`, Warszawa-Modlin `4380`, Warszawa-Radom `4381`. Aktualne zapytanie 2+2 dla tych lotnisk nie zwraca jeszcze rekordu wycieczki z możliwą do potwierdzenia ceną końcową, więc kanał pozostaje diagnostyczny.
- **Travelplanet** — interfejs przyjmuje 2 dorosłych i dzieci 5/7, ale podczas przejścia do wyników obecny przepływ automatyczny gubi dzieci i serializuje wyszukiwanie jak dla samych dorosłych. Taki wynik jest blokowany jako niebezpieczny dla alarmów.
- **Sun & Fun** — zmapowano strukturę formularza: `rooms[0].adults=2`, a dzieci mają jawne pola `rooms[0].children[n].age`. Automat potrafi już utworzyć dwoje dzieci; trwa walidacja ustawienia wieku 5/7, wylotu i końcowej ceny rodziny.
- **Grecos** — ciężka diagnostyka DOM potrafi zawisnąć; kolejny adapter powinien używać lżejszej ścieżki formularza/API zamiast skanowania całej strony.
- **Fly.pl, Nekera, Oasis Tours** — strony są dostępne, lecz potrzebują dedykowanych selektorów uczestników; ogólne heurystyki nie są wystarczająco wiarygodne do awansu na produkcję.
- **Coral Travel, Join UP!, eSky, TraveliGo** — nadal wymagają alternatywnej drogi dostępu z powodu blokad lub braku użytecznej treści w środowisku headless.
