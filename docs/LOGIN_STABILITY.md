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
