# AI Browser — wyłączność sesji (kandydat, NIE PRODUKCJA)

**Aktualny kontroler Render 0.5.2 oraz zapisane logowania Meta pozostają bez zmian.** Ta gałąź nie jest wdrażana przez Render automatycznie.

## Zaobserwowany problem

Dwa czaty sterowały tą samą sesją. W dzienniku przeglądarki widać przejście z trybu odczytu do zapisu podczas pracy na grupach Facebooka. Samo sprawdzenie listy sesji przed operacją nie chroni przed takim wyścigiem.

## Zaimplementowane w oddzielnej gałęzi

* session_ownership.py — koordynator jednego zadania: losowy token właściciela, ścisłe sprawdzenie sesji/profilu/trybu/domeny, serializacja odczytów, kontrola przekierowań, zapis pełnego profilu przed zwolnieniem. Brak logowania, publikowania i automatycznej zmiany trybu.
* legacy_tool_interlock.py — proponowany etap migracji: blokada 46 starych poleceń sterowania przez MPC, z pozostawieniem trzech narzędzi odczytu listy profili, listy sesji i dziennika. Blokada ma być włączona dopiero po udostępnieniu nowych narzędzi uprawnionemu agentowi.
* tests/ — testy syntetyczne, bez sekretów i bez logowania na kontach.
* .github/workflows/ai-browser-session-guard-tests.yml — GitHub Actions automatycznie sprawdza składnię i testy przy zmianach w tej gałęzi.

**Ważne:** nie jest to jeszcze produkcyjna ochrona przed innym czatem. Starsze narzędzia i niezależne trasy mobilne nadal korzystają z żywego menedżera. Trzeba podłączyć je wszystkie do jednego punktu kontroli albo wyłączyć niechronione ścieżki oraz zrobić test dwóch niezależnych połączeń MCP. Podmiana samych narzędzi nie blokuje wewnętrznych wywołań menedżera i tras ASGI. Nie wolno częściowo uruchamiać tej blokady.

Dotychczas przygotowana baza Floot ma funkcje dzierżaw, ale nie są spięte z kontrolerem. Narzędzia budowania Floot osiągnęły dzienny limit. Nie przenosimy zablokowanych operacji innym kanałem.

## Weryfikacja

W lokalnym pakiecie rozmowy przeszło **47 testów** (34 dla koordynatora, 13 dla interlocku). W publicznym repozytorium zapisano mniejszą, równoważną paczkę regresji — jej rzeczywista liczba i status są w GitHub Actions. Testy syntetyczne nie potwierdzają działania w prawdziwym MCP.

Uruchomienie w repozytorium: przejdź do katalogu session_ownership i wykonaj polecenie: python -m unittest discover -s tests -v.

## Warunek zakończenia zadania

Nowy broker sesji musi: 1) powstrzymać drugi czat przed zmianą trybu, kliknięciem i zamknięciem sesji pierwszego czatu; 2) zachować aktywne logowanie Macieja po zapisie i ponownym otwarciu; 3) odmówić każdej operacji przy braku dowodu własności; 4) nie psuć odczytu obu Business Suite; 5) nie wymagać haseł podczas zwykłej pracy.
