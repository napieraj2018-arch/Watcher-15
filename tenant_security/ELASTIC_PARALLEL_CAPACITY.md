# AI Browser — elastyczna równoległość, a nie sztywny limit trzech

**10.10.2026. Wyłącznie proof na odizolowanym PostgreSQL 16, niewdrożony.**

Użytkownik chce równocześnie 3, 4–5, a później więcej prac.
Docelowe rozwiązanie to płynna *konfiguracja limitu* per infrastruktura
i pakiet klienta, bez zmiany kodu po każdym zwiększeniu. W repo dodajemy
migrację `006_configurable_capacity.sql` na dotychczasowy PR #116.

## Co zapewnia baza (z testami)

- Domyślnie **5 aktywnych miejsc** spośród 10 przygotowanych.
- Limit może podnieść tylko uprawniony administrator bazy, i tylko do
  `provider_limit`. Worker i klient WWW nie mają prawa edycji tej tabeli.
- Miejsce ponad aktualnym limitem nie może przyjmować sesji, nawet jeśli
  istnieje fizycznie. Gdy administrator zmniejsza limit, działających
  przeglądarek nie zabijamy. Nowe zadania czekają na zwolnione miejsca.
- Równoległe starty są atomowo dopuszczane transakcjami. Kwarantanna
  po niepewnym zamknięciu **zajmuje budżet slotów**, nie uwalnia go.
- Ten sam profil ma jedno wyłączne miejsce w bazie, także gdy należące do
  niego zadania pochodzą z różnych czatów.
- Znaczniki generacji i lease UUID blokują stare procesy po ponownym
  przydzieleniu sesji; nieprawidłowy retry nie tworzy kolejnej sesji.
- Rola verifier z fikcyjnymi receipts w CI jest oddzielona od worker.
  Produkcja musi sprawdzić rzeczywisty provider close i pełny zapis przed
  zwolnieniem miejsca.
- Test: 32 osobne połączenia -> 5 przyjętych, 27 odmów; zwiększenie limitu
  z 5 do 10 -> kolejnych 5 przyjętych; zmniejszenie z 10 do 5 przy
  zajętych dziesięciu miejscach nie kończy żadnej aktywnej sesji.

## Jak skalować bez kolejnego przepisywania systemu

W bazie `browser_parallel.capacity` administrator ustala
`active_limit` i `provider_limit`; ten drugi musi być wcześniej
potwierdzony dla **konkretnego** konta Steel, nie założony z cennika.

Dostawca Steel publikuje (stan 10.10.2026):
- Launch: **10** równoległych sesji, max 15 minut.
- Scale: **100** równoległych sesji, max 1 godzina.
- Enterprise: **1000+** równoległych sesji, zależne od umowy.

Źródło: https://steel.dev/pricing i
https://docs.steel.dev/overview/pricinglimits.

Aby przejść z 5 na 10 wystarczy administracyjna aktualizacja
`active_limit`, po przetestowaniu budżetów. Przy przejściu na Scale
należy najpierw podnieść potwierdzony `provider_limit` i przygotować
kolejne wiersze w tabeli `slots`. Żadna wartość pochodząca z formularza
klienta, webhooka Stripe lub niezweryfikowanego planu nie może zmienić
globalnej przepustowości.

## Nadal niedostępne produkcyjnie

1. Live `Engine.launch` i `manager.max_sessions` mają **limit 1**.
   Ich zwiększenie bez trwałych per-profile mutex, auth i kontroli
   wszystkich tras MCP/HTTP mogłoby mieszać profile.
2. BFF, bank danych profili Floot, auth i fencing slotów są nadal
   izolowanymi modułami testowymi, bez bezpiecznej migracji.
3. Wcześniej nie przeszedł realny Steel E2E test spójności
   cookie/localStorage, issue #111. Same receipts `profile_saved=true`
   nie potwierdzają poprawnego odtworzenia zalogowania.
4. Prawdziwe per-tenant limity wydatków, billing Steel, monitorowanie
   zamknięć, czekających zadań i recovery after crash wciąż wymagają
   podłączenia i weryfikacji.
5. Nie używać zrównoleglonych sesji dla jednego profilu; każda sesja
   musi należeć do konkretnego zadania i klienta.
6. Przed sprzedażą potrzebne kompletne testy E2E, izolacja tenantów,
   RODO, egress/SSRF, obsługa MFA, monitorowanie i audyt.

**Commercial GO/NO-GO: NO-GO.**
