# AI Browser — kontrolowany rozruch wyłączności sesji

Stan: kandydat z gałęzi session-ownership-guard-20261008, PR #73 DRAFT. Produkcja nadal pracuje na wersji 0.5.2. Nie zawiera haseł ani cookies.

## Dlaczego teraz NIE deployujemy

Ostatni odczyt browser_sessions pokazał aktywną sesję Meta - Maciej - Monitoring (read_only) używaną przez inne zadanie. Nie wolno jej zatrzymać, restartować Rendera ani włączać nowego strażnika w trakcie pracy.

## Zrealizowane i testowane

1. Nieprzewidywalny identyfikator właściciela przekazywany w istniejącym parametrze session_id bez zmiany schematów MCP.
2. Obcy klient nie może zmienić trybu, odczytać, nawigować, zakończyć ani przejąć sesji.
3. Lista sesji i audit nie ujawniają wewnętrznego identyfikatora; adresy w wynikach mają usunięte parametry i fragmenty.
4. Wspólne zabezpieczenie manager.start, manager.stop, manager._session i tras mobilnych HTTP, a jednocześnie zachowany automatyczny zapis profilu.
5. Nieznany zestaw narzędzi lub niezgodna trasa HTTP zatrzymuje start.
6. Test prawdziwego MCPServer 2.3 na atrapach, w tym symulacja dwóch oddzielnych klientów.
7. Ostatni test GitHub Actions: 83 PASS, run 37828042254.

## Otwarte ryzyka

- Strażnik działa na jednej instancji i w pamięci procesu, bez połączenia z bazą trwałych dzierżaw Floot.
- Podczas dzierżawy funkcja browser_staged_files jest celowo niedostępna, co wymaga osobnego rozwiązania dla przesyłania plików.
- Nie przetestowano współpracy z odszyfrowanym rdzeniem na rzeczywistym Renderze ani dwóch niezależnych konwersacji ChatGPT na działającej usłudze.
- Przy niepotwierdzonym zapisie strażnik zachowuje stan blokady i wymaga nadzorowanej naprawy; nie zwalnia go samoczynnie.
- Flagę AI_BROWSER_SESSION_GUARD=1 należy włączyć dopiero po smoke testach; obecnie domyślnie OFF.

## Etapy po zwolnieniu sesji

1. Sprawdź brak aktywnych sesji, kopie bazowe profili i ostatni commit/CI. Jeśli istnieje praca w toku — odłóż wdrożenie bez przerywania.
2. Scal PR tylko z aktualnym zielonym CI, trzymając flagę OFF; zbuduj obraz, potwierdź Render LIVE i /health/context.
3. Dopiero gdy serwer ponownie jest wolny, włącz flagę w Render i zweryfikuj start oraz katalog 51 narzędzi. Przy niezgodności: OFF i rollback.
4. Na profilu SteelSelfTest, nie na kontach Meta, sprawdź nowy identyfikator aib_, odmowę dla innego klienta i surowego ID, ochronę browser_set_mode, brak ujawnienia ID w browser_sessions oraz poprawny zapis obu profili przed zamknięciem.
5. Uruchom drugi test: ponowne otwarcie SteelSelfTest i potwierdzenie syntetycznych znaczników cookie + localStorage.
6. Sprawdź w trybie tylko odczytu Business Suite obu firm na zapisanym profilu Macieja, nie publikując niczego.
7. Test dwóch niezależnych czatów wraz z trasami mobilnymi. Dopiero po tym ogłaszaj ochronę aktywną.

## W razie awarii

Nie kasuj profili i nie proś użytkownika o ponowne hasła. Ustal stan pełnego profilu Steel i zaszyfrowanej kopii. Wyłącz flagę AI_BROWSER_SESSION_GUARD, wróć do działającego commita i potwierdź health oraz możliwość ponownego otwarcia kont. Nie wdrażaj nowej wersji, kiedy inna sesja jest aktywna.
