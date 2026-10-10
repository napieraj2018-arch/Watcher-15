# AI Browser — OWNER BETA: prywatny pilot dla właściciela

Status weryfikacji: 2026-10-10 (Europe/Warsaw). **To jest publiczne repozytorium kodu; nie wolno umieszczać tutaj loginów, nazw prywatnych klientów, cookie, tokenów, arkuszy ani recenzji.** „Prywatny” oznacza kontrolowany dostęp do uruchomionej instancji przez uwierzytelnione MCP, nie prywatność repozytorium.

## Czego można używać

- Jedno konto właściciela ChatGPT, maksymalnie **5** niezależnych profili przeglądarki naraz w trybie `AI_BROWSER_SESSION_GUARD=multi`, z `AI_BROWSER_PARALLEL_OWNER_BETA=1`. Domyślny limit kodu to **1**, dopóki nie zostanie jawnie skonfigurowany.
- Każda rozmowa otrzymuje odrębny nieudostępniany uchwyt `aib_...`. Tego samego profilu nie wolno używać z drugiej rozmowy w tym samym czasie.
- Na iPhonie: narzędzia MCP w ChatGPT. Stary mobilny podgląd/zdalne logowanie HTTP są **zablokowane** w trybie wielu sesji, bo nie zapewniają izolacji uchwytów.
- Odczyt danych i diagnostyka zgodna z uprawnieniami; zmiany na stronach wyłącznie na podstawie bieżącego, wyraźnego polecenia użytkownika.
- Zamknięcie własnej sesji przez `browser_stop`, potwierdzenie zapisu i brak kwarantanny. Standardowy watchdog próbuje zatrzymać sesję po około 13 minutach; to nie jest trwały proces autonomiczny na wiele godzin.

## Rozdział pracy

| Tryb | Dopuszczalne | Zakazane |
| --- | --- | --- |
| Odczyt informacji | Profil należący do bieżącej pracy, stan strony i źródłowe dowody | Uznanie nazwy profilu za dowód zalogowania |
| Meta/Instagram | Odczyt po potwierdzeniu autentycznego konta w widoku | Automatyczne ponawianie loginu/MFA, zmiana haseł, masowe logowania |
| Opinie klientów | Prywatny rejestr poza repozytorium, unikanie duplikatów | Przenoszenie tekstów opinii do GitHub, publikacja bez osobnego polecenia |
| Diagnostyka | Syntetyczne profile, bezpieczne komunikaty o błędach | Używanie prawdziwych kont jako fixture |
| Równoległość | 2–5 rozłącznych sesji z jednym właścicielem | Dzielenie uchwytu pomiędzy rozmowami, 10 sesji bez testu providera |

## Bramka wdrożenia

1. Sprawdź HEAD `ai-browser-cloud`, rzeczywiście uruchomiony commit Render, zakończone CI i **świeżą** listę sesji. Nie traktuj kodu scalonego w GitHub jako wdrożonego.
2. Jeśli `browser_sessions` pokazuje aktywne sesje — **nie wdrażaj, nie restartuj ani nie zmieniaj zmiennych środowiskowych**. Nie zatrzymuj cudzych sesji.
3. Gdy instancja jest bezczynna, uruchom offline Docker CI oraz co najmniej dwie rzeczywiste sesje testowe, sprawdzając niezależność profili, błąd przy szóstym starcie, poprawny stop i brak kosztowych pętli retry.
4. Przy każdej niepewności dotyczącej zapisu, strony dostawcy lub uwierzytelnienia: **BLOCKED**; zachowaj profile, bez automatycznego ponawiania logowania.
5. Weryfikuj rollback na zachowanej gałęzi `owner-beta-rollback-live-20261010-228f9c7` (ostatni potwierdzony LIVE z tej kontroli); restart wyłącznie podczas bezczynności.
6. Nigdy nie przenoś prywatnych danych firmowych do tego publicznego repozytorium.

## Status funkcji (w chwili audytu 10.10.2026)

| Obszar | Status | Znaczenie |
| --- | --- | --- |
| Jeden właściciel, pięć rozłącznych sesji | **LIVE (ograniczone)** | 5 aktywnych profili technicznych; nie dowodzi stabilności pięciu kont Meta |
| Kontrakt MCP mobile `browser_sessions` | **PASS** | Lista zgodna ze schematem po PR #122 |
| Testy równoległości Docker | **PASS** | Symulowany provider i prawdziwy MCP 2.3, bez prawdziwego logowania |
| Rozpoznawalny błąd `TargetClosedError` | **CODE MERGED / NOT LIVE** | PR #119; nie naprawia samoczynnie zamkniętej strony |
| Odtworzenie spójnego cookie/localStorage | **BLOCKED** | #111 — przed dowodem po realnym restarcie nie obiecuj „bez ponownych logowań” |
| Instagram archiwalne wyróżnienie | **BLOCKED** | Nie uznawaj ośmiu slajdów za odczytane bez bezpośredniego potwierdzenia |
| Katalog procedur Anity | **DRAFT** | PR #120; brak automatycznej publikacji |
| Komercyjne konta klientów | **NO-GO** | Brak pełnej tożsamości tenantów, audytu, kolejki i zweryfikowanej trwałości |

## Reguła raportowania

Rozróżniaj `LIVE` (wdrożony i obserwowany), `PASS` (konkretny test zaliczony), `DRAFT` (propozycja), `BLOCKED` (warunek niezaliczony) oraz `NO-GO` (zakaz uruchomienia dla klientów). Nie utożsamiaj sukcesu `full_profile_saved=true` z potwierdzeniem tożsamości serwisu.

Ten plik opisuje procedury właściciela. Nie stanowi gwarancji działania Meta/Instagram, nie aktywuje płatnych usług i nie zawiera prywatnych danych.
