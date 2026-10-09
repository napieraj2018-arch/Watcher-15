# AI Browser — model zagrożeń przed pierwszymi klientami

Data: 2026-10-09. Status: projekt zabezpieczeń, nie opis już wdrożonej izolacji.

## Granice zaufania

1. **Użytkownik ↔ UI**. Uwierzytelniona sesja użytkownika (HttpOnly, Secure, SameSite, CSRF) musi być innym sekretem niż dostęp administratora i niż sesja Steel. Użytkownik nie może wybierać surowego identyfikatora profilu lub namespace w API.
2. **UI ↔ Backend dla klientów (BFF)**. Każde wywołanie posiada tenant_id z serwera i zakres uprawnień. Nie ufać identyfikatorowi firmy dostarczonemu przez przeglądarkę. BFF wybiera tylko zasoby bieżącego tenanta.
3. **Agent ChatGPT ↔ MCP**. Narzędzia muszą mieć osobne tokeny klientów z zakresem i terminem ważności. Wspólny link do MCP kontrolujący wszystkie profile jest niedopuszczalny do sprzedaży.
4. **BFF ↔ baza, kolejka, sejf**. W każdym zapisie i odczycie egzekwować tenant_id, RLS, audyt i limity. Bezpośredni token do Steel pozostaje na backendzie. Sekrety klienta szyfrowane oddzielnymi kluczami lub envelope encryption z rotacją.
5. **Backend ↔ przeglądarka Steel**. Każdy tenant korzysta z własnego profilu, własnych namespace i nieprzenoszonych kontekstów. Sesja przypisana do jednego zadania; bez poprawnego tokenu dzierżawy nie wolno wysyłać CDP/kliknięć/stop.
6. **Zewnętrzna witryna ↔ agent**. DOM, załączniki, wiadomości, strony WWW i odpowiedzi narzędzi to dane, a nie instrukcje administracyjne. Użytkownik musi autoryzować publikacje, zakupy i zmiany zabezpieczeń.
7. **Nagrania i screenshoty ↔ odbiorca**. Materiały często zawierają prywatne dane. Nie wysyłać ich do logów tekstowych, automatycznych raportów ani linków publicznych. Ograniczyć retencję, wymagać autoryzacji i watermarku sesji klienta.

## Przykładowy model zasobów

Tenant — UserMembership — Workspaces — ConnectedAccounts — BrowserProfiles — AgentTasks — SessionLeases — AuditEvents.

Każdy zasób ma tenant_id i unikalny niezgadywalny identyfikator. Steel profileId jest mapowany po stronie serwera, nie wyświetlany klientowi. Żadne pole z żądania HTTP nie może samodzielnie ustawiać tenant_id. Użytkownik może mieć kilka przestrzeni w ramach własnego tenanta; przestrzeń nie jest zamiennikiem granicy bezpieczeństwa.

Minimalny kontrakt trasy BFF:

POST /api/workspaces/:workspace_id/tabs/open
- Serwer ustala tenant_id z uwierzytelnionego użytkownika, weryfikuje uprawnienia do workspace_id.
- Sprawdza limit, koszt i dozwolone działania.
- Rezerwuje atomowo, z wygaśnięciem, jeden identyfikator właściciela sesji; zwraca identyfikator tab i status, NIE dane dostępu.
- W tle uruchamia Steel z przypisanym profilem tenanta, dopiero po potwierdzeniu stanu READY. Kolejny klient dostaje status kolejki zamiast przejmowania sesji.
- Działania wymagające zapisu mają osobny poziom autoryzacji i audyt akcji. GET i screenshoty mogą wymagać osobnych zgód na ujawnienie wrażliwej treści.

## P0 — przykłady testów, które MUSZĄ przejść

| Scenariusz | Prawidłowe zachowanie |
|---|---|
| Klient A odczytuje profil Klienta B po podmienieniu UUID | 403 i brak efektów ubocznych |
| Klient B wysyła browser_stop dla sesji A | Odmowa, sesja A dalej działa |
| Klient B wysyła starą dzierżawę po jej przejęciu przez A | Odmowa również po wygaśnięciu i odnowieniu |
| Witryna próbuje nakazać agentowi zmianę klucza API | Instrukcja z DOM ignorowana jako nieufne dane |
| URL wskazuje na 127.0.0.1, 169.254.169.254, DNS rebinding, IPv6 ULA lub schemat file | Odmowa na warstwie backendu i egress |
| Screenshot zawiera dane pacjenta/klienta | Dostęp tylko dla tenant-admin, krótka retencja, zero publicznych URL |
| Użytkownik żąda usunięcia profilu | Usunięcie w Steel, bazie, vault, kopiach i nagraniach; audyt postępu, ponawianie idempotentne |
| Steel wygaśnie albo profil provider status FAILED | Brak automatycznej utraty kopii, zadanie zawieszone, właściciel otrzymuje komunikat |
| Sesja jest zajęta przez inne zadanie | Kolejka, nie pętla startowania co 5 minut i nie wymuszony stop |
| Skończy się budżet lub klient zmieni abonament | Blokada nowych operacji kosztowych bez utraty danych |
| Użytkownik loguje się w dodatkowym MFA | Krótkotrwały, przypisany tylko właścicielowi podgląd, potem ponowne przejęcie przez agenta |
| CDN/profile vault publiczny, bez tokenu | 401 na API, brak enumeracji identyfikatorów i żadnego wycieku profili |
| Pliki klienta A trafiają do zadania klienta B | Odmowa i izolowane obiekty magazynu, test antywirusa/typu/rozmiaru |
| Klucz Steel lub token MCP zostaje wycofany | Weryfikacja odmowy, rotacja i odzyskanie bez ujawnienia klucza w logach |

## P0 — luki w obecnym prototypie

- **Wspólny katalog profili i pojedynczy serwer MCP.** Nie ma udowodnionego tenant-level RLS ani scoped credentials.
- **Strażnik sesji w trybie probe** — sprawdza zgodność kodu, lecz nie egzekwuje wyłączności.
- **Brak kompletnego usuwania natywnych profili Steel** oraz wielowersyjnych kopii zapasowych.
- **Niepełne odtwarzanie**: syntetyczny test strony po restarcie wykazał cookie/localStorage mismatch.
- **Floot i Render w planach free** oraz publiczne URL aplikacji — wymaga osobnej kontroli produkcyjnego bezpieczeństwa, wydajności i ciągłości.
- **Nie ma produkcyjnej kolejki ani kosztów per tenant**; zbyt wiele równoległych prób może przerwać logowania.
- **Brak kompletnego weryfikowanego 2FA handoff**; automatyzacja nie może zastępować uwierzytelnienia bez zgody.

## Wymagane procedury prawne i operacyjne

Przed sprzedażą: regulamin, polityka prywatności, umowa powierzenia przetwarzania danych (GDPR/RODO), identyfikacja ról administrator/procesor, retencja i usuwanie, podprocesorzy, lokalizacje danych, test bezpieczeństwa i proces zgłaszania incydentów. Wartość zapisanych cookies jest porównywalna z danymi umożliwiającymi zalogowanie — traktować ją jak sekret. Dokument powinien przejść niezależny przegląd prawny.

Model ten jest narzędziem do przeglądu i projektowania, a nie audytem penetracyjnym ani gwarancją zgodności z RODO.
