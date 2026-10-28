# Połączenia API zamiast ponownego logowania

## Aktualny odczyt i dostęp — 28.10.2026 (nie traktuj jako stałych uprawnień)

Przy każdym następnym poleceniu właściciela wykorzystaj najpierw już
podłączoną usługę ChatGPT **tylko gdy pozwala na realny odczyt lub zapis**
na dokładnie wskazanym koncie. Zapisane połączenie, nazwa profilu albo
wyświetlone zero nie dowodzi dostępu. Nie reklamuj „bez limitów 24/7”
— bieżący Render to Free (autoDeploy off), Steel ma limit długości sesji,
Floot Free limity hostingu. Kolejka checkpointów `aib_task` nie uruchamia
samodzielnie pracy, gdy czat nie działa. AI Browser plugin ma już
uprawnienie specyficzne „Allow all actions”; **nie podnoś uprawnień
globalnych ani nie proś ponownie o ten sam dostęp**.

**Rzeczywiste testy tego dnia:**

- `Windsor_ai/searchconsole` udostępnia w katalogu 7 property, w tym
  `sc-domain:weterynarz.radom.pl` i `sc-domain:architekt.radom.pl`,
  ale bezpośredni `get_data` zwrócił komunikat, że Free dopuszcza
  1 konto, gdy połączonych jest 15, i **dummy zeroes**. Zwracane liczby
  NIE są prawdziwymi danymi SEO. Wstrzymaj analizy z tego API do chwili
  potwierdzonego nieprzykładowego wyniku. `GSC Wizard` jest
  `payment_required`; nie ponawiaj bez zmiany planu.
- Przez **nasz istniejący AI Browser** profil `Google - Weterynarz`
  osobno otworzył realne Google Search Console, w pasku URL Inspection
  pokazano „weterynarz.radom.pl”, panel Przegląd miał dane indeksowania,
  a sesję read-only zamknięto z `full_profile_saved=true`. To
  obserwacja konkretnego panelu, **nie** certyfikat ważności konta
  na przyszłość; sprawdzaj aktualny URL/profil, a nie sam status auth.
- `Google - Architekt - GSC` w innym nowym read-only otworzył jedynie
  `/search-console/about`; nie oznaczaj jako zalogowany. Sesję
  poprawnie zamknięto `full_profile_saved=true`; jeśli brak
  poprawnej tożsamości, właściciel autoryzuje konto sam.
- `vidIQ` zwrócił `channels=[]` dla aktualnie podłączonego konta.
  Właściwy NKW `UC7EQ32QjfKQ7bFiVdGAhB-A` **nie został w ten
  sposób potwierdzony**. Nie wykonuj edycji/wysyłki na losowy kanał.
  Przez Chrome Google może odmówić logowania z CDP; do docelowego
  YouTube API użyj systemowego OAuth, nie stealth/obejścia zabezpieczeń.
- `Google Drive` połączony. `GitHub` i `Render` działają przez
  osobne aplikacje, bez potrzeby utrzymywania okna Steel. Stan
  `provider_reconciliation_required` czytaj jako blokadę, a nie zgodę
  na restart lub przejęcie sesji.
- WordPress kliniki: R65 JS `#2202` i R66 JS `#2205` są wcześniej
  potwierdzone LIVE w issue `#160`. Nie wgrywaj ich ponownie.
  R66 dotyczy tylko karty Macieja na okulistyce, nie innych lekarzy.
- Dla kodu `connector_router.py` nowe trasy `youtube`,
  `google_search_console`, `github`, `render`, `google_drive`
  oznaczają **podpowiedź sposobu obsługi**, nie uzyskanie nowych
  uprawnień, stanu zalogowania lub wykonanie zadania.
  Dostęp 24/7 wymaga niezależnie zatwierdzonego schedulera i
  infrastruktury, a sesje Steel mają być krótkotrwałe i zapisywane.

**Bezpieczne wdrożenie routera:** PR #181 ma być scalany po pełnym
CI exact-head. Podczas aktywnego WordPress WRITE / public QA / closing
nie deployować. Pusta lokalna lista sesji nie wystarczy: sprawdź
niezależny provider-inventory, neutralne saved-close i brak kwarantanny.
Wstrzymane poprzednio godzinowe zadania przeglądarki pozostawić
wstrzymane. Zmiana kodu nie uzasadnia resetu cookies, Floot, Neon,
płatności ani ponownego żądania haseł.


Zasada: przy poleceniu publikowania Reels, posta, odczytu poczty,
WordPress lub opinii Google najpierw sprawdź dostępne, już podłączone
aplikacje ChatGPT. Wykonuj w nich autoryzowaną czynność BEZ uruchamiania
Steel, jeśli narzędzie obsługuje dokładnie żądany format i konto.

**Wznowienie pracy, 23.10.2026:** istniejące zgody użytkownika obowiązują
w zatwierdzonym zakresie. Sprawdź aktualną tożsamość i dostępność konkretnej
operacji; nie proś o ponowne logowanie ani zgodę na GitHub tylko dlatego,
że poprzedni czat się przerwał. Puste dane, timeout, brak pojedynczego
uprawnienia i wylogowanie to różne stany. Katalog tras pomaga wybrać
narzędzie, ale nie wykonuje autoryzacji i nie odzyskuje zadania.

Poniższe wyniki kontroli połączeń pochodzą z 10.10.2026; nie są
potwierdzeniem dzisiejszego dostępu. Schemat operacji, format materiału
i właściwe konto sprawdzaj bezpośrednio przed użyciem:

- Gmail: osobna aplikacja ChatGPT już działa. OAuth wyklucza potrzebę
  przechowywania hasła Gmaila w AI Browser. Użyj Gmail do odczytu,
  szkiców lub wysyłania, zależnie od zgody i zakresu narzędzi.
- Windsor.ai: konto Instagram @architekt.radom i Facebook Page Anity.
  Instagram action create_video_post publikuje Reels (wymaga podanego,
  dostępnego dla platformy URL MP4/MOV 3 s–15 min; można dołączyć
  cover_url JPEG albo thumb_offset). Nie zgaduj gotowego filmu;
  publikacja z podanym materiałem wymaga właściwej marki.
  Windsor facebook_organic ma posty i zdjęcia; obsługę Reels
  Facebook należy osobno zweryfikować, nie utożsamiać z Instagram API.
- WPVibe: WordPress https://architekt.radom.pl/poradnik i
  https://weterynarz.radom.pl mają potwierdzony odczyt, ale zapis,
  upload i publikację sprawdza się osobno na właściwej witrynie.
- Google Business: recenzje właściwej wizytówki Anity są dostępne
  przez Windsor google_my_business; archiwalne Stories/Highlights IG
  nie były zwrócone przez API i wymagają autoryzowanego odczytu
  wizualnego, którego nie należy udawać.
- Metricool: dotychczasowa kolejka Anity nie może być modyfikowana
  przez samą diagnostykę. Nie dotykaj profili weterynaryjnych.

Jeżeli aplikacja ChatGPT nie obsługuje danego kroku lub nie ma
prawidłowego uprawnienia, dopiero wtedy AI Browser z właściwym
trwałym profilem; odczytaj bieżący stan autoryzacji. Nazwa profilu
ani zapisany cookie nie są dowodem zalogowania. Przy CAPTCHA odczytaj stan
wbudowanej obsługi Steel i odczekaj wyłącznie jej ograniczony budżet.
Wymagane osobiste MFA lub nieobsłużone wyzwanie wykonuje użytkownik
w mobilnym oknie, po czym agent odczytuje bieżący stan.
Nie przenoś tokenów z połączonych aplikacji ChatGPT do publicznego
repozytorium, Render environment ani logów.

Zapisywanie haseł: preferowane są OAuth + szyfrowany vault z wąskim
uprawnieniem i pochodzeniem z bezpiecznego formularza, NIE hasła
wpisywane w czat ani w publiczny GitHub. Hasło master odzyskiwania
w razie wyzwania użytkownik przechowuje we własnym menedżerze haseł.


## YouTube Studio / Google — osobny błąd polityki logowania (24.10.2026)

W mobilnym handoff profilu do YouTube Studio właściciel zaobserwował komunikat Google
`Couldn't sign you in — This browser or app may not be secure`. Nie wynika z niego
błędne hasło, skasowane cookies ani nieprawidłowe zapisanie całego profilu.
Nazwa/obecność trwałego profilu **nie** oznacza aktualnej autoryzacji Google.

- Dokumentacja Google wskazuje, że logowanie może zostać zablokowane w
  przeglądarkach wbudowanych lub sterowanych programowo. Dla zdalnego
  Chromium/CDP (Steel) ponawianie logowania nie jest potwierdzoną naprawą.
  Nie obchodź blokady przez spoofing User-Agent, wyłączanie polityk, rotację
  adresów IP, stealth, import sesji z innej osoby ani automatyczne powtarzanie
  prób. CAPTCHA to inny mechanizm i nie rozwiązuje tej odmowy.
- **Natychmiastowa droga ręczna:** otwórz `https://studio.youtube.com/`
  w zwykłym Safari/Chrome na urządzeniu właściciela. Jego sesja w Safari
  NIE jest automatycznie przenoszona do zdalnego Steel i nie upoważnia
  do deklarowania, że ChatGPT zalogował się do panelu.
- **Docelowa droga programowa:** oddzielne, świadomie zatwierdzone OAuth 2.0
  Google dla **YouTube Data API**, prowadzone w systemowej przeglądarce
  i z bezpiecznym przekierowaniem. Uprawnienia i token odświeżania trzymać
  w prywatnym zaszyfrowanym magazynie na właściciela/kanał, nie w
  publicznym repo, historii narzędzi ani cookie Steel. Użyć state/PKCE
  tam, gdzie właściwe dla rodzaju klienta. Każde żądanie musi potwierdzać
  właściwy kanał i zakres autoryzacji.
- YouTube Data API umożliwia m.in. aktualizację tytułów, opisów, tagów,
  ustawianie pojedynczej miniatury i harmonogramu **prywatnego filmu
  nigdy wcześniej nieopublikowanego**. Aktualizacje `videos.update`
  mogą wyczyścić pominięte właściwości w części `snippet`/status; przed
  zapisem odczytać pełny wymagany zasób i robić kontrolowany update.
  Potwierdzić dokładne video ID, kanał, końcowe wartości i read-back.
  Funkcje wyłącznie interfejsu Studio (np. natywne testy wariantów miniatur)
  nie są obiecywane jako dostępne przez API.
- Wcześniejsze połączenie Gmail/Drive **nie daje automatycznie** uprawnień
  YouTube. Nie deklarować, że OAuth YouTube jest skonfigurowane bez
  autoryzacji i odczytu bieżącego kanału. Żadne dane uwierzytelniające
  z innych konektorów nie mogą być kopiowane do AI Browser.
- **Bieżący status:** błąd logowania Google potwierdzony na ekranie;
  integracja bezpośredniego OAuth YouTube Data API w AI Browser NIE
  jest jeszcze wdrożona ani autoryzowana. Nie klasyfikować jako PASS.

Oficjalne źródła:
- https://support.google.com/accounts/answer/7675428
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/youtube/data/reference/rest/v3/videos/update
- https://developers.google.com/youtube/data/reference/rest/v3/thumbnails/set

## Operacyjny wybór połączenia z poziomu AI Browser MCP

Narzędzie `aib_route_operation(service, operation, brand)` jest bezpiecznym
katalogiem opcji, np.:

- Instagram Reel Anity: `instagram`, `reel`, `anita` →
  ChatGPT Windsor.ai `instagram/create_video_post`; wymaga konkretnego
  dostępnego URL wideo i odczytu bieżących uprawnień / ID konta.
- Facebook post Anity: `facebook`, `post`, `anita` →
  Windsor `facebook_organic/create_post`; wpis na Facebooku nie oznacza,
  że opublikowano również Reel w Instagramie.
- Gmail: `gmail`, `email_read`, bez marki →
  podłączona aplikacja `Gmail/search_emails`, bez hasła browsera.
- Zwykłe potwierdzenie e-mail: `gmail`, `email_verify`, bez marki →
  połączony Gmail wybranego właściciela. Agent sprawdza bieżący flow,
  adresata, czas, nadawcę oraz dokładną domenę i cel odnośnika przed
  pojedynczym otwarciem we własnej sesji. Ta trasa nie czyta poczty
  samodzielnie i nie kopiuje OAuth do Rendera.
- WordPress: `wordpress`, `wordpress_publish`, `anita` →
  WPVibe `discover_abilities` i dopiero po weryfikacji właściwej
  witryny dostępna funkcja zapisu lub publikacji.
- GBP recenzje Anity: `google_business`, `business_reviews`, `anita` →
  Windsor `google_my_business/get_data` dla właściwego location.
- Archiwalne Highlights lub funkcja bez oficjalnego API →
  właściwy zapisany profil Steel dopiero po bieżącym potwierdzeniu
  tożsamości zalogowanego konta.

**Ważna różnica:** to katalog tras, NIE most do sekretów ani samodzielna
integracja OAuth. Funkcja zawsze zwraca `connector_connected=not_checked`
i `account_authenticated=not_checked`. Agent musi sprawdzić konkretne
połączenie bezpośrednim narzędziem aplikacji ChatGPT, potwierdzić identyfikator
konta i dostępność wymaganej operacji. Publikacja wymaga wskazanego
materiału i odpowiedniego upoważnienia. Nie wolno na podstawie katalogu
ogłaszać, że Reel się opublikował, ani zastępować Reels zdjęciem.

## Trwałość profilu i rzeczywiste blokady

Wdrożenie [#154](https://github.com/napieraj2018-arch/Watcher-15/pull/154)
potwierdzono 23.10.2026 o 05:40 Europe/Warsaw. Neutralny test przeszedł
wpisywanie tekstu, karty, odświeżanie i pełne zapisane zamknięcie;
bieżąca poprawka obejmuje wykryty timeout nawigacji wstecz/dalej.
Wcześniejszy odbiór [#153](https://github.com/napieraj2018-arch/Watcher-15/pull/153)
potwierdza na neutralnym profilu zapis cookie/localStorage, pełne zamknięcie
i zgodny odczyt strony w nowej sesji (23.10.2026, 00:28 Europe/Warsaw).
Wcześniejszy syntetyczny odbiór #138 obejmował również restart Render,
zgodnie z `AGENTS.md`. Nie traktuj dawnego #111 jako automatycznej awarii
wszystkich zapisanych profili; te testy nie potwierdzają jednak aktualnego
zalogowania prawdziwych kont. Każdy nowo scalony kod wymaga osobnego
potwierdzenia wdrożenia. Zakres: `docs/BROWSER_CAPABILITIES.md`.

Historyczna sesja #148 została niezależnie rozliczona jako
[Completed](https://github.com/napieraj2018-arch/Watcher-15/issues/148#issuecomment-6129272443).
Nowy błąd zapisu, utrata lease lub niepewne zwolnienie providera nadal
wymagają sprawdzenia przed ponownym startem albo wdrożeniem; nie czyść
kwarantanny restartem. Kontynuuj niezależne autoryzowane prace API.

Właściciel 23.10.2026 zlecił obsługę zwykłych potwierdzeń e-mail oraz
wspieranych CAPTCHA bez ponownego pytania o ten sam zakres. Nie zatwierdzaj
przez to resetu hasła, odzyskiwania, zmiany adresu, nowych uprawnień OAuth
ani niepowiązanego logowania. Nie wykonuj ślepych ponowień i nie rozszerzaj
originów mobilnego handoff. Hasła, kody i tokeny nie trafiają do czatu ani
publicznego repo. Zapisany profil nie jest trwałym wznowieniem zadania.
