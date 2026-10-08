# AI Browser — zgodność profilu po restarcie (test techniczny)

Data: 08.10.2026. Status: osobna gałąź testowa, NIE wdrożono zmiany odzyskiwania profili.

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
