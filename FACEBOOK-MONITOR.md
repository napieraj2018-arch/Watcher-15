# Facebook Local Monitor — prototyp 0 zl

**Status: eksperymentalny / WYLACZONY.** Modul w osobnej galezi GitHub.
Nie dotyka istniejacego Watcher-15 ani zadnych kont reklamowych.

## Cel

- Co 15 minut sprawdzic wybrane, jawnie wskazane strony/grupy Facebooka.
- Odszukac nowe posty z prosba o weterynarza lub architekta.
- Odfiltrowac powtorki i wyslac email z linkiem do wpisu.
- Bez automatycznego komentowania, lajkowania ani wysylania DM.
- Bez hasla i cookies Facebooka w repozytorium lub logach.

## Dwa sposoby odczytu

1. \`facebook_local_monitor.py --probe\` — jednorazowy test standardowym Playwright/Chromium bez logowania. Zwraca kod 3, kiedy posty sa niedostepne. Przygotowano tez obsluge Playwright storage_state przez sekret \`FB_STORAGE_STATE_B64\`, ale NIE jest on obecnie uzupelniony. Nie zaleca sie jego recznego eksportowania z iPhone'a.
2. \`facebook_monitor_ai_browser.py\` — preferowana droga przy korzystaniu z wlasnego profilu: laczy sie z naszym AI Browser MCP, uruchamia zapisany profil \`Meta - Maciej - Monitoring\` w trybie \`read_only\` i czyta tylko widoczne linki oraz strony postow. Profil i cookies pozostaja w szyfrowanym magazynie AI Browser. Github nie otrzymuje ciasteczek.

## Uruchomienie / koszty

- Sam harmonogram i kod monitoringu: bezplatny GitHub Actions w publicznym repozytorium.
- Czas harmonogramu: minuty 07, 22, 37, 52 kazdej godziny UTC (best effort; GitHub moze sie opozniac).
- Rzeczywisty monitoring NIE jest wlaczony. Plik workflow z harmonogramem jest tylko na galezi \`feature/facebook-local-monitor\`; GitHub uruchamia cron wylacznie z galezi domyslnej.
- Nawet po przeniesieniu do \`main\`, job jest wylaczony, dopoki repozytorium nie otrzyma wartosci \`FB_WATCH_ENABLED=true\` w *Actions variables*.

## Jednorazowe czynnosci potrzebne do testu na zywo

1. Uzytkownik loguje sie WYLACZNIE w bezpiecznym oknie AI Browser na wlasne konto do osobnego profilu \`Meta - Maciej - Monitoring\`. Kod SMS/2FA pozostaje u uzytkownika. Nie podawaj loginow, hasel ani ciasteczek w czacie.
2. Test: \`profile_list\`, \`browser_start\` w trybie \`read_only\`, otworzenie jednej strony Facebooka; potwierdzenie ze sa widoczne NOWE wpisy z datami i permalinkami. Zapisac rezultat BEZ nazwisk i tekstow wpisow w publicznych logach.
3. Przekazac do GitHub Secret \`AI_BROWSER_MCP_URL\` (pelny URL serwera MCP; jest sekretem), ale nie wpisywac go do kodu. GitHub Secret ma byc widoczny tylko workflowom zezwolonym przez wlasciciela.
4. Dodac do GitHub Actions Secrets \`FB_SMTP_HOST\`, \`FB_SMTP_PORT\` (zwykle 465), \`FB_SMTP_USER\`, \`FB_SMTP_PASSWORD\` (haslo aplikacji, nie glowne haslo Google), \`FB_ALERT_TO\`.
5. Uruchomic recznie pojedynczy workflow \`workflow_dispatch\` i potwierdzic email z kontrolowanym wpisem testowym. Pierwszy skan celowo tworzy baseline — nie wysyla starych wpisow.
6. Po tescie zgodnosci i stabilnosci dopiero dac \`FB_WATCH_ENABLED=true\` i uruchomic 15-minutowy harmonogram.

## Ograniczenia i bezpieczenstwo

- Automatyczne pozyskiwanie danych z Facebooka moze naruszac aktualne warunki Meta bez jej uprzedniej zgody. Wlasny profil FB NIE jest odpowiednikiem uprawnienia do masowego odczytu. Projekt nie obchodzi CAPTCHA, checkpointow, 2FA ani ograniczen serwisu.
- Mozliwa jest blokada konta, przekierowanie do logowania albo brak dat i linkow w HTML. Dla profilu osobistego to realne ryzyko biznesowe.
- Nie ma gwarancji dostepu do zamknietych grup. Nie mozna obiecac stuprocentowego wykrywania kazdego posta.
- Render free ma limit pamieci 512 MiB; przy 10–15 stronach AI Browser moze przekroczyc ten limit. Po tescie 2 zrodel trzeba wykonac test obciazeniowy 5 i 15 zrodel.
- Nie zapisujemy postow ani cookies do publicznych logow i repozytorium. Lokalny cache zawiera tylko hashe linkow i identyfikatory zrodel.
- Jesli Facebook nie udostepnia postow, skaner raportuje blad dostepu, a NIE „brak nowych wpisow”.
- Wersja AI Browser przerywa prace, jesli ktos juz korzysta z przegladarki — nie przerywa logowania ani pracy uzytkownika.
- Alerty sa informacjami do samodzielnego sprawdzenia. Odpowiedzi w grupach pozostaja reczne; automat nie publikuje.

## Testy i pliki

- \`src/facebook_local_monitor.py\` — rozpoznawanie polskich zapytan, URL-i, deduplikacja, SMTP.
- \`src/facebook_monitor_ai_browser.py\` — MCP, sesja read-only, baseline osobno dla kazdego zrodla.
- \`config/facebook_local_monitor.json\` — na start tylko 2 strony, pozostale dodajemy po potwierdzeniu.
- \`tests/test_facebook_local_monitor.py\` oraz \`tests/test_facebook_monitor_ai_browser.py\`.
- \`.github/workflows/facebook-local-monitor-test.yml\` — bezpieczne testy, tylko jednorazowy odczyt.
- \`.github/workflows/facebook-local-monitor-15m.yml\` — harmonogram za bramka opt-in.

## Wynik bazowego testu 2026-10-08

11 testow logiki przeszlo. Playwright na GitHub Actions odczytal ekran \`login_required\` na obu stronach; 0 odczytanych postow. Dopiero poprawny test sesji Meta pozwoli podjac decyzje o uruchomieniu.
