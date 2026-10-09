# AI Browser — izolacja profili wielu klientów (prototyp PostgreSQL)

**Status: schemat i testy w osobnej gałęzi, nie stosować do istniejącej bazy Floot.**

To niezależny dowód bezpieczeństwa na pustej bazie PostgreSQL 16. Nie migruje żadnych istniejących kont, cookies ani sesji. Sprawdza wymaganie sprzedaży: klient A nie może odczytać ani zmienić zasobu klienta B nawet po manipulacji SQL.

## Zasada tożsamości

Wersja testowa przypisuje osobną rolę logowania PostgreSQL do każdego tenanta. Funkcja browser_product.authenticated_tenant() odczytuje tożsamość z session_user, a nie parametru żądania lub zmiennej app.tenant_id, którą można podrobić przez SQL.

Polityki Row Level Security (RLS), z FORCE ROW LEVEL SECURITY, obejmują workspaces, profiles i browser_tasks. Klient dostaje dostęp tylko do wybranych kolumn. Wewnętrzny identyfikator natywnego profilu Steel pozostaje poza jego uprawnieniami.

Klient nie ma uprawnienia DELETE do surowych profili. Usunięcie wymaga osobnego, audytowanego procesu obejmującego również Steel, nagrania i zaszyfrowane kopie.

## Zakres testu

- Odseparowanie SELECT dla profili, zadań i przestrzeni A i B.
- Odmowa INSERT do obcego tenanta i UPDATE jego danych.
- Brak możliwości odczytu provider_profile_ref i tabeli mapowania ról.
- Podmiana app.tenant_id na cudzy UUID nie zmienia tożsamości sesji.
- Klient może tworzyć tylko swoje przestrzenie i profile.
- Zewnętrzne klucze złożone browser_tasks wiążą tenant_id, workspace_id i profile_id.
- Wyłączenie powiązania roli (enabled=false) odbiera dostęp do chronionych tabel.

## CI — tylko testowa baza danych

Workflow: .github/workflows/tenant-rls-ci.yml, ephemeral PostgreSQL 16 bez danych klientów.

Uruchom migrację i test:

    psql -h 127.0.0.1 -U postgres -v ON_ERROR_STOP=1 -f tenant_security/001_tenant_isolation.sql
    psql -h 127.0.0.1 -U postgres -v ON_ERROR_STOP=1 -f tenant_security/tests/test_isolation.sql

CI używa tymczasowego POSTGRES_HOST_AUTH_METHOD=trust tylko w izolowanym kontenerze GitHub Actions. NIGDY nie stosować trust na serwerze produkcyjnym.

## Warunki użycia komercyjnego

Model osobnej roli DB per tenant wymaga automatycznego zarządzania tysiącami kont, rotacji haseł i bezpiecznego połączenia aplikacji z właściwą rolą. Przy większej skali warto rozważyć niezależnie audytowany mechanizm JWT/RLS wspierany przez dostawcę bazy lub izolację oddzielnymi bazami. Sam tenant_id w żądaniu UI nie jest dowodem tożsamości.

RLS nie zastępuje: autoryzacji w BFF, transakcyjnych dzierżaw i kolejki, ochrony egress/SSRF, szyfrowania sekretów, 2FA, pełnego usuwania natywnych profili i backupów, polityki retencji ani audytu penetracyjnego.

To jest test wyłącznie warstwy danych, nie ukończony produkt.


## Poprawka bezpieczeństwa z 09.10 — autorytatywny stan zadania

Testowana wcześniej rola klienta posiadała `GRANT INSERT(...,state)` i
`GRANT UPDATE(state)`. To umożliwiało bezpośrednie oznaczenie zadania jako
`running`/`done` mimo braku potwierdzenia backendu.

Po zmianie rola klienta:
- może dodać zadanie bez kolumny `state`, ze stanem domyślnym `queued`;
- nie może zmienić stanu istniejącego zadania;
- nie może utworzyć zadania z dowolnie ustawionym `state`;
- nadal ma dostęp RLS tylko do swojego tenant_id.

**Granica:** nie utworzono jeszcze autoryzowanego serwisu pracownika z
kontrolowanymi przejściami stanów. To nie uruchamia realnej kolejki ani
obsługi zadań. Wdrożenie pozostaje testem osobnej bazy PostgreSQL 16.
