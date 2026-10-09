# AI Browser — zgodność profilu po restarcie (test techniczny)

Aktualizacja 09.10.2026: kod opcjonalnego odzyskiwania został scalony, lecz został wyłączony po nieudanym teście na zdalnym Steel. Odczyt diagnostyczny jest w gałęzi głównej, ale nie został jeszcze wdrożony na Renderze.

## Zaobserwowany problem

Profil techniczny SteelSelfTest: po ręcznym kliknięciu „Zapisz znacznik testowy” strona podaje cookie OBECNE, localStorage OBECNE, zgodność PASS. Po zapisaniu, zamknięciu i ponownym otwarciu w nowej sesji: oba obecne, ale zgodność BRAK POTWIERDZENIA. Powtórzono zarówno z profile_flush przed zamknięciem, jak i bez niego.

To problem zgodności stanu testowego; nie oznacza automatycznie utraty zalogowania Meta. Zbiorcze zdarzenia profilowe wskazują też równoległy dostęp do SteelSelfTest w innych zadaniach, więc analiza czasu zapisu wymaga izolacji.

## Zmiana w steel_context_fix.py

Domyślnie nie zmienia zachowania: aktualny profil natywny ma pierwszeństwo przed backupem. Wyłącznie po ustawieniu AI_BROWSER_PORTABLE_PRIORITY_PROFILES na listę dokładnych nazw pozwalamy wskazanym PROFILOM TESTOWYM traktować zaszyfrowaną kopię jako pierwszy wybór przy konfliktach cookie/localStorage.

Nie dodawać do listy kont Macieja, Anity, Google czy produkcyjnych profili klientów przed odrębnym, rzeczywistym testem. Nigdy nie mieszać cookies między nazwami profili. Przełącznik nie zapisuje wartości, haseł ani cookie do logów.

## Plan odbioru

1. Wersja testowa i 25 testów syntetycznych w GitHub Actions — wstępny warunek.
2. Uruchomienie z pustą listą sesji, bez zatrzymania cudzego zadania.
3. AI_BROWSER_PORTABLE_PRIORITY_PROFILES=SteelSelfTest.
4. W izolowanej nowej sesji technicznej zapisz cookie + localStorage, sprawdź PASS, zapisz profil, zamknij, uruchom NOWĄ sesję, sprawdź ponownie PASS.
5. Jeżeli wynik nadal nie jest PASS, wróć do pustej listy i nie zmieniaj produkcyjnych profili. Sprawdź pochodzenie kopii i natywnych danych, a nie wymuszaj kolejnego logowania.
6. Jeżeli test jest poprawny, nie rozszerzaj automatycznie działania na Meta; wymagana osobna kontrola trwałości sesji i tożsamości.

Faza testowa nie scala ani nie publikuje materiałów social, nie zmienia haseł i nie modyfikuje ustawień bezpieczeństwa kont.

## 09.10.2026 — stan potwierdzony, następny odbiór

Na zdalnym Steel próba priorytetu przenośnej kopii wyłącznie dla SteelSelfTest **NIE przeszła**: cookie i localStorage były obecne, ale wynik po ponownym uruchomieniu pozostał niezgodny. W odpowiedzi przywrócono `AI_BROWSER_PORTABLE_PRIORITY_PROFILES` do pustej wartości. Wdrożenie cofające to ustawienie jest LIVE (Render dep-db3uvjei0phs73ecufm0), a `AI_BROWSER_SESSION_GUARD` pozostaje w trybie `probe`. Prawdziwe profile innych kont nie były objęte eksperymentem.

09.10 przygotowano i scalono PR #75: nieinwazyjną diagnostykę tylko dla profilu technicznego. Odczyt ma pokazać liczbę testowych elementów i booleany zgodności osobno dla: natywnego profilu Steel, szyfrowanej kopii i stanu końcowego. **Nie pokazuje wartości, nazw cookie, kluczy localStorage, hashy, haseł ani tokenów.** Przewidziano także rozróżnienie kodowania URL wartości cookie. Żaden inny profil nie uzyska tej diagnostyki.

CI gałęzi głównej po scaleniu: **179 testów Docker PASS**, run 37893008443. Poprzedni błąd pakowania tests/ został naprawiony w gałęzi testowej zanim kod scalono.

**Nie uznawaj diagnostyki za uruchomioną na Renderze.** Podczas próby wdrożenia aktywna była sesja CloudSelfTest innego zadania, więc serwer pozostawiono bez restartu. Zweryfikuj `browser_sessions` ponownie i NIE wywołuj deployu przy aktywnej sesji. Nie próbuj zatrzymywać jej przez sam fakt upływu czasu.

Następna praca, po zwolnieniu serwera:
1. Sprawdź zgodność najnowszej gałęzi, 179 zielonych testów i brak aktywnych sesji.
2. Wdróż nowy commit bez zmiany env, potwierdź Render LIVE oraz `AI_BROWSER_SESSION_GUARD_PREFLIGHT_OK tools=51 routes=35`.
3. Otwórz jedną własną sesję SteelSelfTest, zapisz wyłącznie booleany `synthetic_fixture_evidence` i wynik publicznego testu zgodności, bez wartości znaczników.
4. Rozstrzygnij, czy błąd pochodzi już z zaszyfrowanej kopii, natywnego profilu, połączenia źródeł czy z zachowania strony po nawigacji; dopiero potem projektuj następną zmianę.
5. Jeżeli którykolwiek odczyt jest niepewny, zakończ wyłącznie własną sesję techniczną i nie zmieniaj ustawień produkcyjnych kont.

NIE aktywować pełnej blokady sesji (`AI_BROWSER_SESSION_GUARD=1`), dopóki nie przejdzie osobny test dwóch klientów i ścieżki powrotu po niepewnym zapisie.

## 09.10.2026 — dokładny znacznik, test produkcyjnego Steel zakończony sukcesem (tylko techniczny profil)

PR #90 scalił diagnostykę rozpoznającą **dokładne** cookie `aibrowser_test_cookie` z `Path=/browser-check` oraz klucz localStorage `aibrowser_public_test_marker`. Stary test oparty na dowolnych parach z tej samej domeny był niejednoznaczny. Nowy odczyt nie zwraca żadnych wartości, identyfikatorów, nazw kluczy ani hashy.

GitHub Actions run 37946868193: **265 testów w pełnym Docker PASS** i **70 testów offline PASS** (nakładające się zestawy). Główna gałąź powtórzyła zieloną budowę run 37947212672. Render deploy **dep-db4fv4t9fdbs73brc7og** jest LIVE, commit 0cbda604bfc2b5239a658dbe821ae8711b078fa2; start potwierdził `AI_BROWSER_SESSION_GUARD_PREFLIGHT_OK tools=51 routes=35`.

Zdalny test w trybie `AI_BROWSER_PORTABLE_PRIORITY_PROFILES=''` (puste, natywne pierwszeństwo):

- Początkowo profil `SteelSelfTest` miał właściwe cookie w natywnym i przenośnym profilu, ale brak dokładnego klucza localStorage w natywnym. Przenośna kopia zawierała dokładną parę z różnymi wartościami — UI potwierdziło `BRAK POTWIERDZENIA`.
- Kliknięto `Zapisz znacznik testowy` **wyłącznie na technicznej stronie bez danych użytkownika**. UI pokazało `Cookie OBECNE / LocalStorage OBECNE / PASS`. `profile_flush` i `browser_stop` potwierdziły zapis zaszyfrowanej kopii oraz pełnego profilu.
- Po ponownym otwarciu nowej sesji (i później **kolejnym** zamknięciu/otwarciu) wynik UI pozostał `PASS`. Dokładna diagnostyka: natywny `cookie_readable_count=1, storage_exact_key_count=0`; portable `1/1, exact_pair_matches=true`; resolved `1/1, exact_pair_matches=true`. `backup_recovery_applied=true`; brak nowych logowań.
- Wszystkie własne sesje testowe zamknięto z `full_profile_saved=true`. Nie dotykano profili Meta ani Google. Wyłączenie `AI_BROWSER_SESSION_GUARD=1` nadal obowiązuje; tryb `probe` nie egzekwuje ochrony.

**Wniosek:** na zdalnym Steel odzyskiwanie konkretnej pary testowej z **poprawnej kopii** działa po wielokrotnym restarcie. Poprzednie `BRAK POTWIERDZENIA` wynikało ze starej, już niezgodnej pary w kopii, a nie z wykazanej niewydolności mechanizmu na poprawnych danych. To **nie** jest dowód niezawodnego odtwarzania wszystkich prawdziwych zalogowanych kont, automatycznego uzdrawiania już uszkodzonej kopii ani poprawnego działania w wielu równoległych klientach. Bloker sprzedażowy `profile_coherent_restore` pozostaje nierozstrzygnięty do czasu testów rzeczywistych kont i izolacji tenantów.
