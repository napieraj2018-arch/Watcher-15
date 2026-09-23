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

Stan produkcyjny pozostaje celowo konserwatywny: **4 kanały produkcyjne** — Wakacje.pl, TUI Poland, ITAKA i Rainbow. Kanał jest promowany dopiero po zachowaniu dokładnego składu 2+2, potwierdzeniu dostępności, odczytaniu końcowej ceny całej rodziny oraz możliwości bezpiecznego zastosowania aktywnych filtrów jakościowych.

Najważniejsze ustalenia:
- **EXIM tours** — bezpośrednio potwierdzono stan wyszukiwania `AC1=2`, `KC1=2`, `KA1=5|7`; strona pokazuje „2 dorosłych 2 dzieci”, „5 lat” i „7 lat”. Skład 2+2 jest więc wiarygodnie zachowany. Nadal brakuje karty/rezerwacji z jawną ceną końcową całej rodziny, dlatego kanał nie został sztucznie awansowany.
- **Travelplanet** — interfejs przyjmuje 2 dorosłych i dzieci 5/7, ale podczas przejścia do wyników obecny przepływ automatyczny gubi dzieci i serializuje wyszukiwanie jak dla samych dorosłych. Taki wynik jest blokowany jako niebezpieczny dla alarmów.
- **Sun & Fun** — wykonano pełny test żywego wyszukiwania `room1=2,5,7`. Strona potwierdziła „2 dorosłych 2 dzieci” i dla dokładnego wylotu 24.09.2026 zwróciła jawną **„Cena całkowita 8 304 zł”**. Dodano też twardą kontrolę daty, ponieważ zapytania na 25/26.09 były automatycznie przesuwane przez serwis na 27.09; takie przesunięte wyniki są teraz odrzucane. Kanał pozostaje diagnostyczny tylko dlatego, że trzeba jeszcze niezawodnie przypisać do konkretnej karty hotelu liczbę gwiazdek, ocenę i liczbę opinii wymagane przez aktywny watcher.
- **Grecos** — znaleziono bezpośredni JSON API ofert: `/api/sitecore/OffersList/LoadMoreOffers`. Bieżące wywołanie zawiera m.in. `Adults=2`, daty, długość pobytu i typ oferty. Zidentyfikowano też kontrolkę pasażerów „Dorośli 2 / Dzieci 0”. Następny krok to wydobycie parametrów liczby/wieku dzieci i przejście na lekki adapter API zamiast ciężkiego skanowania DOM.
- **Fly.pl, Nekera, Oasis Tours** — strony są dostępne, lecz potrzebują dedykowanych selektorów uczestników; ogólne heurystyki nie są wystarczająco wiarygodne do awansu na produkcję.
- **Coral Travel, Join UP!, eSky, TraveliGo** — nadal wymagają alternatywnej drogi dostępu z powodu blokad lub braku użytecznej treści w środowisku headless.
