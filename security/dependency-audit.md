# AI Browser — stała kontrola podatności zależności

Status: testowa, tylko odczytowa kontrola pakietów Pythona. Nie importuje kluczy Steel, haseł ani cookies.

## Co sprawdzamy

Workflow GitHub Actions uruchamia pip-audit na runtime requirements.txt przy zmianach Dockerfile/zależności i co tydzień. Narzędzie rozwiązuje zadeklarowane wersje MCP, Playwrighta, cryptography, httpx, psycopg oraz pozostałe zależności i pyta o publiczne komunikaty o podatnościach.

Wynik zapisuje jako krótko przechowywany artefakt JSON w GitHub Actions. Jeżeli wykryta zostanie podatność lub nie można wykonać rzetelnego audytu, zadanie ma zakończyć się błędem — nie należy tego maskować sztucznym sukcesem.

## Czego NIE robi

- Nie aktualizuje automatycznie bibliotek na produkcji ani nie zmienia Dockera na Renderze.
- Nie jest skanerem podatności systemu Ubuntu, obrazu Playwrighta, kodu przeglądarki, Steel ani wszystkich zależności JavaScript.
- Nie dowodzi odporności na luki logiczne lub izolacji klientów.
- Nie jest zamiennikiem audytu SBOM, SAST, DAST, testów penetracyjnych i rotacji sekretów.

## Krytyczne wyzwanie

requirements.txt posiada kilka zakresów wersji (np. MCP i cryptography), więc dwie budowy w różnych dniach mogą pobrać różne wersje przejściowe. Dla wydania komercyjnego wymagany jest **powtarzalny, generowany lockfile z hashami** oraz kontrolowana zmiana zależności po testach regresji. Nie wolno pochopnie aktualizować bibliotek używanych do szyfrowania profili bez testów ponownego otwarcia, zgodności i odzyskiwania.

## Proces aktualizacji

1. Zidentyfikuj dokładny pakiet i wersję zgłoszoną przez pip-audit oraz bezpieczną wersję naprawczą.
2. Przygotuj zmianę zależności na osobnej gałęzi.
3. Wykonaj obowiązkowo: testy profili, 195+ testów Dockera, symulację klientów, Chromium UI i test zapisu/otwarcia profilu technicznego.
4. Wdróż tylko przy pustej liście sesji przeglądarki. Sprawdź LIVE, profil Macieja i konta Google w trybie tylko do odczytu.
5. W razie błędu przywróć poprzedni obraz bez usuwania cookies, zmian kluczy lub żądania nowego logowania.

Źródła: https://github.com/pypa/pip-audit oraz https://owasp.org/www-project-dependency-check/.

Ten raport obejmuje tylko jedną warstwę kontroli komercyjnej gotowości, która wciąż jest NO-GO do czasu izolacji tenantów i pełnego audytu.
