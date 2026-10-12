# AI Browser — trwałość logowania Meta / Instagram / Google

**10.10.2026. Plan techniczny, bez zmiany haseł, cookies, IP i abonamentów.**

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

**Stan: NIEZALICZONY** — testy dotyczące realnego profilu Meta wymagają bieżącego poprawnego odczytu i mogą nadal wymagać pojedynczej autoryzacji użytkownika. Problem #111 / #118 blokuje uznanie rozwiązania za wdrożone.

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


## iPhone — własny panel dotykowy bez WebRTC Steel (PROTOTYP, 12.10.2026)

Problem: oficjalny Steel WebRTC player wyświetla obraz na iPhonie, ale dotyk i/lub klawiatura nie reagują (upstream iOS/WebKit issue #270). Wymuszenie `debugConfig.interactive=true`, `systemCursor=true` i `interactive=true` w URL zostało wdrożone, **ale nie ma potwierdzonego PASS na prawdziwym iPhonie**.

Opracowano alternatywę `session_ownership/owner_mobile_touch.py`:
- `GET /owner-mobile-login/touch` — natywny panel iPhone'a ze zrzutem strony i przyciskami, bez WebRTC/iframe i bez nowych haseł w ChatGPT;
- `GET /owner-mobile-login/touch/frame` — świeży, ulotny JPEG tylko z aktualnej sesji przypisanej do uprzednio wydanego, jednorazowego setupu, nie jest zapisywany;
- `POST /owner-mobile-login/touch/action` — ograniczone `tap`, `scroll`, `key` (`Enter`, `Tab`, `Backspace`) oraz `text` wyłącznie do realnego, zaznaczonego pola. Hasło wpisywane w panelu jest przesyłane HTTPS do serwera tylko na czas wykonania `locator.fill()`, bez zwracania treści do asystenta i bez rejestracji w logach. Hasło może trafić tylko do rzeczywistego pola typu `password` na stronie HTTPS w domenie `facebook.com`; pozostałe domeny odrzucane. Uwaga: to input **we własnym panelu**, nie w natywnym formularzu Facebooka; użytkownik musi być o tym wyraźnie poinformowany, jeśli ta wersja kiedykolwiek zostanie uruchomiona.
- Wszystkie wejścia wymagają ważnego `__Host-aib-owner-login` (HttpOnly, SameSite Strict), dokładnie jednego lease guard, brak kwarantanny, dla mutacji POST dodatkowo zgodny `Origin`, `Content-Type`, walidowany JSON z limitami. Brak dowolnych URL, skryptów, dostępu do cudzych profili, odczytu haseł przez model, automatycznego publikowania lub automatycznego rozwiązania MFA.

To **offline kandydat do wdrożenia**, nie sprawdzony zdalny panel. Nie wolno go wdrażać ani rozpoczynać nowej sesji w obecnym stanie `SteelSelfTest:recovery_required`. Zgłoszenie #148 wymaga niezależnej rekoncyliacji sesji Steel oraz statusu zapisu; sam release HTTP 200 nie zwalnia lokalnego lease. Po rozwiązaniu kwarantanny potrzebne są: QA na nieosobistym polu formularza, potem manualny test autoryzacji i zapis→stop→nowa sesja prawdziwej tożsamości. Nie używać prawdziwych haseł do testów aplikacyjnych.

