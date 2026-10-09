# AI Browser — automatyczne otwieranie kart i kolejka (PROTOTYP)

Ten moduł ma umożliwić użytkownikowi zwykłe otwarcie nowej karty zamiast szukania i ręcznego uruchamiania technicznej sesji Live.

## Zrealizowane w kodzie offline

- Przycisk otwarcia karty powoduje próbę **automatycznego uruchomienia** w tle; frontend dostaje tylko status i identyfikator karty, nie surowe ID sesji.
- Jeżeli inne zadanie używa przeglądarki, nowe żądanie trafia do FIFO; użytkownik widzi komunikat o kolejce.
- Zapisane sesje mogą być współdzielone przez karty tylko w obrębie dokładnie tego samego użytkownika, zadania, tenanta i przestrzeni.
- Każdy tenant ma niezależny katalog profili i dokładnych dozwolonych domen HTTPS.
- Powtórzenie tego samego request_id w tej samej przestrzeni jest bezpieczne i nie wywołuje kolejnego startu.
- Po nieudanym starcie brak automatycznej serii ponowień; po niepewnym zapisie profil zostaje zablokowany do wyjaśnienia.
- Kolejka ma limity, przeterminowanie, anulowanie i ochronę przed podmienianiem identyfikatorów żądań między tenantami.
- Nie zawiera haseł, cookies, kluczy ani dostępu do rzeczywistego Steel.

**Status:** nie jest wdrożony; testy używają tylko BrowserMock. Nie ma jeszcze prawdziwej kolejki między procesami lub uwierzytelnionego API. Nie wolno sprzedawać tej wersji jako działającej izolacji tenantów.

## Minimalna integracja dla prawdziwego produktu

Wymagane elementy przed podłączeniem:

1. Backend BFF ustala Principal z zalogowanej sesji użytkownika (nigdy z body żądania klienta).
2. Trwała dzierżawa w Postgres/Redis z atomowym fencing tokenem; bieżący in-memory lock jest tylko testem protokołu.
3. Per-tenant Storage, RLS i Steel namespaces; nazwy profili z UI nie mogą pochodzić od dowolnych klientów.
4. Warstwa adaptera Steel implementuje start i tab open i potwierdza zapis READY; nie traktuje HTTP 200 z dashboardu jako tożsamości konta.
5. Poll lub SSE powiadamia UI, że karta jest gotowa, jest w kolejce lub wymaga ręcznego potwierdzenia MFA.
6. Kolejka ma trwałe idempotentne taski, limity kosztów, zatrzymanie i proces rekoncyliacji po awarii.
7. Walidacja adresów jest podwójna: allowlist na BFF oraz ochrona DNS/egress przeciwko SSRF. Regex w tym module NIE jest samodzielną zaporą sieciową.

## Testy

    python -m unittest discover -s workspace_broker/tests -v

CI: .github/workflows/workspace-broker-tests.yml.

Ważne: testy sprawdzają tylko logikę kolejki i izolacji w jednym procesie. Nie są dowodem działania na dwóch czatach, niezależnych klientach ani serwerach, a tym bardziej poprawnego logowania Facebooka.

## Schemat przepływu

Zwykłe kliknięcie karty → sprawdzenie roli i tenanta → rezerwacja dzierżawy → uruchomienie lub kolejka → prywatny widok strony → zapis profilu przy zamknięciu.

Nie ma osobnego przycisku „Live”, ale proces cloud pozostaje niezbędny i powinien działać automatycznie pod spodem.
