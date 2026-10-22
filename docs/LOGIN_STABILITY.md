# AI Browser — trwałość logowania i mobilne podłączenie kont

**Aktualizacja kodu: 23.10.2026. Bez zmiany haseł, cookies, IP i abonamentów.**

Opis poniżej dotyczy zachowania kodu i jego testów. Dostępność na produkcji
trzeba potwierdzić zgodnością SHA aktywnego wdrożenia z wersją zawierającą
poprawkę. Sama obecność dokumentu ani PASS testu lokalnego nie potwierdzają
wdrożenia, zalogowania do serwisu ani działania na rzeczywistym iPhonie.

## Czas zadania, zapis profilu i wznowienie

W trybie pięciu równoległych sesji każde zadanie otrzymuje własny capability
i blokadę profilu. Dwa czaty mogą pracować na różnych profilach, ale nie na
tym samym profilu jednocześnie. Stan profilu nie zastępuje capability.

| Zdarzenie | Obecny limit / znaczenie |
| --- | --- |
| Automatyczne zapisanie i zamknięcie przez owner guard | Najpóźniej 780 sekund (13 minut) od przyznania sesji; krócej, jeżeli uruchamianie zużyło część budżetu providera. Zachowuje 90 sekund zapasu przed terminem niższego runtime. |
| Wygaśnięcie capability | 850 sekund; późniejszy limit nie daje dodatkowego czasu pracy po rozpoczęciu zamykania. |
| Niższa warstwa runtime / provider | Runtime ma limit 870 sekund, a żądanie Steel timeout 900 sekund. Nie należy planować pracy do tych późniejszych terminów. |
| Mobilne zaproszenie do logowania | Maksymalnie 600 sekund; domyślne 900 sekund starego klienta jest przyjmowane i ograniczane do 600. |
| Wznowienie po restarcie procesu | Brak trwałego wznowienia capability i zadania. Zapisany profil może być użyty w nowym, osobno autoryzowanym zadaniu. |

Przy udanym starcie guard ustala nieprzedłużalny termin jako
`min(780, początkowe_remaining_seconds_runtime - 90)`. Gdy runtime nie
udostępnia tego pomiaru, obowiązuje dotychczasowe maksimum 780 sekund.
Budżet wyczerpany przed przyznaniem sesji uruchamia własną ścieżkę zapisu
i zamknięcia zamiast wydania pozornie zdrowej capability.

`browser_start`, właścicielskie `browser_status`, aktywne wiersze
`browser_sessions` i faktyczny watchdog używają tego samego terminu.
Pola `remaining_seconds`, `auto_save_close_in_seconds`,
`capability_expires_in_seconds` oraz `durable_resume_supported: false`
ujawniają rzeczywisty zakres. Odczyt statusu nie przedłuża żadnego limitu.
Samo skrócenie liczby w statusie bez skrócenia watchdogu nie jest naprawą
wolnego startu — regresja musi sprawdzać zaplanowane zamknięcie.

### Równoczesny odczyt podczas startu i zamknięcia

Lista sesji rozróżnia `starting` i `closing`. Utworzenie rekordu managera
poprzedza wydanie capability, a jego usunięcie może poprzedzać końcowe
potwierdzenie zapisu profilu. Te krótkie, kontrolowane fazy nie oznaczają
osieroconej sesji. Slot i blokada profilu pozostają zajęte do zakończenia
odpowiedniej operacji. Niepotwierdzony wynik nadal pozostawia stan
wymagający odzyskiwania.

Wcześniej współbieżne `browser_sessions` mogło w tym oknie ustawić trwałą
globalną kwarantannę nawet po późniejszym poprawnym starcie lub pełnym
zapisie i zamknięciu. Regresje odtwarzają odczyt dokładnie pomiędzy zmianą
rekordu a zwróceniem wyniku. Poprawka nie czyści automatycznie istniejących
flag i nie uznaje każdej nowej kwarantanny za ten historyczny wyścig.

### Przerwany start i przerwane zamykanie

Jeśli przerwany start pozostawi dokładnie jeden nowy rekord właściwego
profilu z tej konkretnej próby, guard może dokończyć jego zapis i zamknięcie
w ograniczonym czasie. Nie wybiera sesji po samej nazwie, nie dotyka rekordów
obecnych przed startem i nie odzyskuje capability innego czatu. Powodzenie
wymaga pełnych potwierdzeń zapisu oraz braku tego rekordu; niejasny kandydat,
niepełny zapis lub timeout pozostawiają kwarantannę.

Adapter Steel odróżnia zamknięcie połączenia CDP od rozpoczęcia i
potwierdzenia zwolnienia zdalnej sesji. Anulowanie przed pierwszym release
nie może sprawić, że kolejne własne zamknięcie pominie go na zawsze.
Jeśli release już rozpoczęto, niepewny wynik nie daje prawa do kolejnego
zapisu w ciemno ani zwolnienia slotu. Ta poprawka nie dodaje niezależnego
terminalnego GET providera i nie czyści wcześniejszej kwarantanny.

Długie zadanie wymaga zapisanego checkpointu przed zamknięciem. Obecny kod
nie uruchamia automatycznie kolejnej sesji i nie odzyskuje zadania po
restarcie. `profile_saved` ani `full_profile_saved` nie dowodzą aktualnej
tożsamości w serwisie; tę trzeba odczytać w nowej sesji.

## Dlaczego powtarza się logowanie

To są różne, niezależne przyczyny i każda wymaga innego potwierdzenia:

1. **Niespójne cookie i localStorage po odtworzeniu Steel.** W realnym syntetycznym teście `SteelSelfTest` logika wyliczyła spójną parę, ale Chromium po zastosowaniu jej nie potwierdził: issue #111. Najpierw naprawa i walidacja restore, inaczej żaden VPN nie pomoże.
2. **Zmienna tożsamość sieciowa.** Steel przechowuje profile, lecz nowe sesje mogą korzystać z różnych wyjściowych IP. Usługi kontowe mogą wtedy wyświetlać dodatkową weryfikację. Lokalizacja Render Frankfurt nie określa IP stron otwieranych przez zdalnego Chromium w Steel. Dokumentacja Steel określa hostowanie przeglądarek w `us-east` i konfigurację IP przez `useProxy`.
3. **Wygasła sesja / MFA / kontrola serwisu.** Nawet stałe IP, profil i fingerprint nie gwarantują trwającej autoryzacji. Rozpoznać faktyczny stan konta na stronie; nie powtarzać nieudanych logowań automatycznie.
4. **Usterka nawigacji i zamkniętej strony.** 10.10 przy profilu `Meta - Anita` na Instagram Highlights zarejestrowano `TargetClosedError` po `page.goto`; issue #118, PR #119 poprawia kod błędu, ale nie stabilność samego połączenia.

## Plan redukcji logowań

**Krok 1 — bez kosztów.** Zawsze korzystać z działających oficjalnych połączeń OAuth/API, jeśli dostarczają żądane dane. Dla Anity mamy potwierdzone `instagram`, `facebook_organic` i `google_my_business`; 20 recenzji GBP pobrano bez wchodzenia w login Google. Archiwalne Instagram Highlights nadal wymagają osobnej wizualnej weryfikacji, bo 24-godzinne Story API nie jest tym samym.

**Krok 2 — trwałość profilu.** Dla każdego docelowego konta jeden profil Steel, stabilny `profileId`, `persistProfile: true`, odczekanie statusu `READY` po release, test po pełnym restarcie oraz syntetyczny dowód prawdziwego readback Chrome. Nie mieszaj różnych kont/fingerprintów i nie otwieraj równocześnie tego samego profilu w dwóch pracach. Uwierzytelnienie należy potwierdzić bieżącym odczytem właściwej strony.

**Krok 3 — stabilny adres IP wyłącznie po zgodzie kosztowej.** Oficjalny Steel Dedicated IP pozwala przypisać statyczny IP do profilu przez `useProxy:{type:"fixed",id:"fixed:…"}`. Cennik Steel 10.10.2026 wskazuje **Scale: 250 USD miesięcznie + zużycie** i **Dedicated IP: 5 USD/IP/miesiąc** (plus transfer proxy; wymagany plan z funkcją). Startowy Launch ma 10 współbieżnych sesji, ale tabela funkcji mówi, że dedicated IP nie jest w Launch. Szczegóły:
https://docs.steel.dev/overview/sessions-api/dedicated-ips
https://docs.steel.dev/overview/sessions-api/configuration
https://steel.dev/pricing

Nie kupować adresu IP ani abonamentu na własną rękę. Jeśli przyszłe warunki konta przewidują stały IP, trzeba potwierdzić faktyczny plan, koszty transferu, region (Polska) i preferowany profil. **Nie włączać przypadkowego VPN na Renderze**: Steel obsługuje ruch przeglądarki z własnej infrastruktury. Nie rotować IP, nie podszywać się pod urządzenie i nie traktować stabilnego IP jako metody obejścia zabezpieczeń Meta.

**Krok 4 — telefon tylko do potwierdzeń.** Autoryzowane OAuth/SSO albo sesja Steel z mobilnym podglądem pozwala użytkownikowi zatwierdzić MFA/2FA w aplikacji Facebook/Instagram na iPhonie. Aplikacja mobilna nie przekazuje automatycznie swojego keychain do innej zdalnej sesji Chromium; nie obiecywać kopiowania cookies z telefonu.

## Warunki powodzenia

- Nowy profil i wznowiona sesja należą do właściwego konta Meta, bez checkpoint.
- Po zamknięciu i restarcie w nowej instancji browser UI potwierdza tę samą tożsamość i widoczność dozwolonego materiału.
- Dwóch niezależnych klientów nie może współdzielić profilu ani IP przydzielonego komuś innemu.
- Żadna próba nie tworzy powtarzanych loginów, wysyłek kodów, zmian haseł, żadnych nowych opłat bez zgody.

**Zakres potwierdzenia:** syntetyczna poprawka trwałości #138 przeszła 11.10
test nowej sesji i restartu Render, zgodnie z zapisem w `AGENTS.md`. To nie
potwierdza zalogowania rzeczywistego konta Meta. Dla konkretnego konta nadal
potrzebny jest bieżący odczyt właściwej tożsamości; może być wymagana
pojedyncza autoryzacja użytkownika. Historyczne #111 / #118 opisują przyczyny
i ograniczenia, a nie automatyczny dowód nowego incydentu w każdej sesji.

## Mobilne okno logowania — iPhone (poprawka 12.10.2026)

W nowym właścicielskim handoff `/owner-mobile-login` jednorazowy link służy **wyłącznie pierwszemu przyjęciu zaproszenia**. Po pierwszym wejściu sesja jest przypisana do krótkotrwałego, bezpiecznego cookie tej samej przeglądarki. Powrót strzałką „Wstecz” lub ponowne otwarcie zaproszenia z **tego samego Safari/in-app browser** ma wznowić istniejący ekran zapisu, zamiast zużywać zaproszenie powtórnie. Z innej przeglądarki lub po faktycznym wygaśnięciu nowy użytkownik nie może odzyskać sesji samym linkiem.

Przy logowaniu wyświetlaj interaktywny podgląd Steel jako osobną stronę na **pełnym ekranie**, a nie w poziomym iframe wewnątrz wysokiego panelu iPhone (powodowało czarne pasy i mikroskopijny formularz Facebooka). Start żąda `headless=false` aby istniejąca warstwa `steel_context_fix` ustawiła viewport 508×1074. Po zalogowaniu wróć przyciskiem „Wstecz” do krótkotrwałego ekranu i wybierz „Zapisz profil i zakończ”. Nie nazywaj zapisu potwierdzonym logowaniem bez niezależnego odczytu tożsamości w **nowej sesji**.

Nie przedłużaj automatycznie TTL, nie powielaj sesji i nie publikuj surowego URL playera ani fragmentu zaproszenia w logach/raportach. Przy nieweryfikowalnej starej sesji użyj wyłącznie jej autoryzowanego `profile_cancel_setup` z własnym identyfikatorem i wymagaj `full_profile_saved` przed nowym setup. Poprawka nie zmienia dostępu do cudzych profili.

## iPhone Steel player — widoczna strona bez możliwości kliknięcia (12.10.2026)

Rzeczywisty zrzut z profilu `Meta - Karolina Machnicka` pokazuje stronę Facebook w środku bezpośredniego `api.steel.dev` playera, z dużymi czarnymi polami. Użytkownik nie może wybrać pola ani wpisywać. Wyświetlanie obrazu z WebRTC NIE jest dowodem działania zdalnych wejść.

Dwie warstwy sterowania według [Steel Configuration](https://docs.steel.dev/overview/sessions-api/configuration) i [Human-in-the-Loop](https://docs.steel.dev/overview/sessions-api/human-in-the-loop):
- Provider POST /sessions: `debugConfig.interactive: true`, `debugConfig.systemCursor: true`.
- Link do właścicielsko uwierzytelnionego playera: jawne `interactive=true&showControls=true`, niezależnie od potencjalnego `interactive=false` w `debugUrl`.
Ani nazwa profilu, ani link do obrazowego podglądu nie wystarczają do dowodu interakcji; wynik wymaga **dotknięcia pola i faktycznej odpowiedzi kursora/klawiatury na iPhonie**.

Upstream Steel ma osobny [otwarty błąd iOS WebKit input](https://github.com/steel-dev/steel-browser/issues/270), dotyczący przede wszystkim klawiatury osadzonego iframe; u nas wykorzystujemy pełny ekran, ale dostawca może nadal mieć usterkę dotykową. Nie zastępować tej zależności niezweryfikowaną pętlą logowania ani wstrzykiwaniem haseł przez AI. Jeśli jawne włączenie `interactive` nie pomaga na prawdziwym telefonie, następny krok to diagnostyka tego konkretnego playera z dostawcą lub osobny, autoryzowany interfejs obsługi zdalnej sesji. **Nie deklarować naprawy dotyku wyłącznie na podstawie CI.**


## iPhone — własny panel dotykowy bez WebRTC Steel (kod z 22.10.2026)

Problem: oficjalny Steel WebRTC player wyświetla obraz na iPhonie, ale dotyk i/lub klawiatura nie reagują (upstream iOS/WebKit issue #270). Wymuszenie `debugConfig.interactive=true`, `systemCursor=true` i `interactive=true` w URL zostało wdrożone, **ale nie ma potwierdzonego PASS na prawdziwym iPhonie**.

Alternatywę obsługują `session_ownership/owner_mobile_handoff.py` oraz
`session_ownership/owner_mobile_touch.py`:

- `GET /owner-mobile-login/touch` — natywny panel iPhone'a ze zrzutem strony i przyciskami, bez WebRTC/iframe i bez nowych haseł w ChatGPT;
- `GET /owner-mobile-login/touch/frame` — świeży, ulotny JPEG tylko z aktualnej sesji przypisanej do uprzednio wydanego, jednorazowego setupu, nie jest zapisywany;
- `POST /owner-mobile-login/touch/action` — ograniczone `tap`, `scroll`, `key` (`Enter`, `Tab`, `Backspace`), `back`, `forward`, `reload` oraz `text` wyłącznie do realnego, zaznaczonego pola. Hasło wpisywane w panelu jest przesyłane HTTPS do serwera na czas wykonania `fill()`, bez zwracania treści do asystenta i bez rejestracji w logach. Trafia wyłącznie do pola typu `password` na dokładnie dozwolonym originie wybranej usługi. Uchwyt pola jest związany z konkretnym dokumentem; ponowne sprawdzenie originu przed wypełnieniem chroni przed zmianą strony w trakcie operacji. To input **we własnym panelu**, o czym informuje jego interfejs.
- Wszystkie wejścia wymagają ważnego `__Host-aib-owner-login` (HttpOnly, SameSite Strict), dokładnie przypisanej lease i capability oraz braku kwarantanny. Operacja używa blokady wyłącznie swojej sesji. Dla mutacji POST wymagane są dodatkowo zgodny `Origin`, `Content-Type` i walidowany JSON z limitami. Brak dowolnych URL, skryptów, dostępu do cudzych profili, odczytu haseł przez model, automatycznego publikowania lub automatycznego rozwiązania MFA.

### Klawiatura i podstawowa nawigacja

Tekst może trafić do zwykłego pola `input` oraz do `textarea`. Typ pola
wielowierszowego nie jest porównywany z listą typów `input`. Natywny Enter
oraz przycisk Enter najpierw przesyłają niewysłany tekst z ostatniego
edytowanego lokalnego pola, a dopiero po potwierdzeniu zatwierdzają formularz.
Błąd lub zajęty kontroler nie mogą zatwierdzić pustego/starego formularza
ani usunąć niewysłanego tekstu. Enter klawiatury podczas kompozycji tekstu
oraz powtórzone zdarzenie przytrzymanego Entera nie wysyłają formularza.

Panel ma stałe akcje Wstecz, Dalej i Przeładuj stronę. Są odrębne od
odświeżenia samego obrazu. Nie przyjmują adresu URL ani skryptu od klienta,
działają pod blokadą własnej sesji i zachowują kontrolę dozwolonego originu.
Brak wcześniejszej lub następnej pozycji historii jest zwykłym wynikiem,
a nie powodem do ponownego logowania.

### Obsługiwane wejścia do logowania

Serwer sam dobiera stałą stronę logowania i dozwolone originy. Nie przyjmuje
listy originów od wywołującego. Ścieżka i parametry podanego `login_url` nie
mogą zmienić strony docelowej. Rozpoznawane są wyłącznie jawnie zapisane
hosty HTTPS; domena z podobnym sufiksem nie zostanie zaakceptowana.

| Usługa | Początkowa strona logowania | Dozwolone dodatkowe przejścia w tej samej karcie |
| --- | --- | --- |
| Facebook | `https://www.facebook.com/login/` | Jawnie zapisane hosty Facebook: `facebook.com`, `www`, `m`, `business`, `web`. Istniejące wejście `m.facebook.com` zachowuje mobilną stronę główną. |
| Instagram | `https://www.instagram.com/accounts/login/` | `instagram.com`, `www.instagram.com` i powyższe hosty Facebook dla SSO. |
| ChatGPT | `https://chatgpt.com/auth/login` | `www.chatgpt.com`, `chat.openai.com`, `auth.openai.com`, `auth0.openai.com`, `setup.auth.openai.com` oraz `accounts.google.com`. |
| Metricool | `https://app.metricool.com/login` | `accounts.google.com` i powyższe hosty Facebook dla SSO. |
| Canva | `https://www.canva.com/login/` | `canva.com`, `accounts.google.com` i powyższe hosty Facebook dla SSO. |
| Google | `https://accounts.google.com/ServiceLogin` | `myaccount.google.com`, `mail.google.com`. |
| WordPress — Architekt | `https://architekt.radom.pl/poradnik/wp-login.php` | Wyłącznie `https://architekt.radom.pl`. |
| WordPress — Napieraj i Synowie | `https://weterynarz.radom.pl/wp-login.php` | Wyłącznie `https://weterynarz.radom.pl`. |

Zakres SSO przypisany jest do wybranej usługi: np. panel ChatGPT nie pozwala
przejść do Metricool. Nie dodano automatycznego wybierania osobnego okna
OAuth ani obsługi formularzy wewnątrz obcego iframe. Podane wejścia nie
oznaczają obsługi każdego wariantu logowania oferowanego przez usługę.

### Dowody i bramka wdrożenia

Testy offline sprawdzają własność sesji, zakres originów, zmianę strony w
trakcie wpisywania, błędne URL i zachowanie zapisu. Test Chromium korzysta
z lokalnie podstawionych dokumentów pod tymi originami: sprawdza kliknięcia,
pola i przejścia w tej samej karcie, ale nie jest logowaniem do realnych
ośmiu usług ani testem rzeczywistego iPhone'a. Przed użyciem prawdziwego
hasła potrzebny jest test dotyku na nieosobistym formularzu; tożsamość po
autoryzacji trzeba potwierdzić w sekwencji zapis→stop→nowa sesja.

Historyczny incident #148 nie pozostaje automatyczną blokadą: komentarz
[6129272443](https://github.com/napieraj2018-arch/Watcher-15/issues/148#issuecomment-6129272443)
odnotował niezależne, uwierzytelnione potwierdzenie `Completed` (32 sekundy)
oraz poprawne zamknięcie własnej sesji administracyjnej. Nie zastępuje to
kontroli stanu sesji aktywnych dziś.

Przed wdrożeniem należy potwierdzić HEAD/CI i aktualny inwentarz. Aktywne
zadania, także `read_only`, muszą zakończyć się przez własną ścieżkę zapisu
i zamknięcia; nie wolno usuwać ich po nazwie ani przerywać wdrożeniem.
`recovery_required`, `missing_session_quarantined` lub
`provider_reconciliation_required` wymagają rozliczenia konkretnego,
bieżącego stanu. Zwykły upływ czasu nie potwierdza zapisu profilu.
Publiczne `/health/steel` ani samo HTTP 200 z release nie są niezależnym
odczytem terminalnego stanu dokładnej sesji u providera. Nie należy jednak
wymagać ponownego rozliczenia historycznego #148 jako nowego incydentu,
jeśli nowe odczyty nie pokazują żadnej nierozliczonej sesji.
