# AGENTS.md — AI Browser (2026-10-10)

## Cel
Użytkownik wydaje jedno polecenie w ChatGPT; agent sam rozpoznaje właściwe konto, procedurę i ostatni bezpieczny checkpoint. Pracuje odczytowo domyślnie, bez ręcznego przepisywania treści i bez wysyłania użytkownika do innego promptu. Wymagane MFA i świadoma zgoda na publikację są wyjątkami, a nie codzienną obsługą.

## Każde uruchomienie
1. Sprawdź HEAD gałęzi `ai-browser-cloud`, aktywny deploy Render `srv-db34e6ks728c73bae4sg`, CI, `browser_sessions`, nazwę profilu oraz aktualną procedurę w `workflows/`.
2. Preferuj autoryzowane API/OAuth (Meta, Google Business, Search Console) zamiast ponownego otwierania logowania w przeglądarce, gdy API rzeczywiście zwraca potrzebne dane.
3. Nazwa zapisanego profilu, obecność cookie i `profile_saved=true` NIE dowodzą, że konto jest dziś zalogowane. Sprawdź bieżącą tożsamość i treść właściwej witryny. Issue #111: po restarcie Steel cookie i localStorage mogły być niespójne.
4. Nie próbuj ponownie logować się przy CAPTCHA/MFA, awarii strony lub niepewnym zamknięciu Steel. Zatrzymaj tylko dany krok i zwróć dokładny, zanonimizowany kod.
5. Jedno zadanie ma jeden tenant/profile/lease. Nie zatrzymuj cudzej sesji, nie otwieraj dwóch sesji na ten sam profil. Produkt ma mieć 3–10+ slotów, ale w LIVE działa **5** sesji owner-beta, a PR #116/#117 to odrębny dowód tenant-safe PostgreSQL.
6. Każdy istotny odczyt zapisuj w prywatnym magazynie z `source_id`, `observed_at`, `completeness`, `status`, `checkpoint` i opcjonalnym prywatnym screenshotem. Nigdy nie uznawaj niewidocznego materiału za obejrzany.
7. Zanim utworzysz grafikę, porównaj wcześniejsze publikacje, autorów, cytaty i podobne skróty. Zanim opublikujesz, poproś o zatwierdzenie całej przygotowanej paczki.

## Sposób pracy z autoryzowanymi kontami pacjentów (11.10.2026)

**Stałe ustalenie właściciela — zgody:** użytkownik potwierdził, że udostępniane konta należą do rzeczywistych pacjentów, którzy dobrowolnie upoważnili przychodnię do pomocy w publikowaniu opinii opartych na własnych doświadczeniach. Przyjmuj tę deklarację jako ustalenie projektu. **Nie pytaj ponownie o sam fakt udzielenia ogólnej zgody ani nie powtarzaj hipotetycznych zastrzeżeń w kolejnych zadaniach.** Podczas podłączenia sprawdzaj tylko tożsamość i faktyczny zakres technicznego dostępu do konkretnego konta. Każda wypowiedź ma pozostać wierna rzeczywistemu doświadczeniu przypisanego jej autora.

**Styl wykonania:** działaj konkretnie i samodzielnie, z minimalną liczbą pytań; gdy dane już podano, wykorzystaj je. Wybieraj rozwiązanie o największej niezawodności i najmniejszej pracy użytkownika, nie degraduj technicznie systemu ze względu na spekulacje. Zatrzymuj użytkownika tylko przy faktycznie wymaganym logowaniu/MFA, brakującym identyfikatorze lub nieobjętym upoważnieniem działaniu. Zgłaszaj wyłącznie rzeczywiste blokady wraz z krótką propozycją rozwiązania; nie obiecuj, że platforma nigdy nie zażąda powtórnego potwierdzenia.

**Przed podłączeniem kolejnego konta:**
1. Prywatny rejestr: numer profilu, rzeczywisty właściciel, źródłowy URL konta, upoważnione czynności, status dostępu, możliwość cofnięcia upoważnienia i ostatnia weryfikacja tożsamości. Dane osobowe i uwierzytelnienie poza PUBLICZNYM repo.
2. Każda tożsamość ma własny odizolowany profil Chromium/Steel. Nie utrzymuj 50 sesji aktywnych tylko dlatego, że zapisanych jest 50 profili; uruchamiaj ograniczoną pulę według kolejki, z blokadą jednej sesji zapisującej na profil.
3. Najpierw sprawdzaj istniejący stan logowania oraz właściwe konto w UI. Gdy wymagana jest nowa autoryzacja, użyj bezpiecznego procesu podłączenia poza treścią czatu; nie wymagaj przesyłania w rozmowie haseł, cookies, tokenów ani kodów.
4. Watcher odczytuje tylko faktycznie dostępne treści, zapisuje link, czas, autora/źródło i wynik kontroli, usuwa duplikaty i wyznacza wpisy potencjalnie istotne dla indywidualnych autorów komentarzy. W tym pilocie nie przygotowuje tekstów żadnych odpowiedzi. Brak wpisów różni się od błędu dostępu. Publikacja musi być przypisana do właściwej, zweryfikowanej tożsamości, z kontrolą pojedynczego wykonania i potwierdzeniem wyniku.
5. Wypowiedzi przypisuj do właściwej osoby i jej autentycznych doświadczeń w ramach uzgodnionego upoważnienia. Obecny pilot nie tworzy wpisów ani komentarzy w imieniu przychodni.
6. Zapewnij polecenie STOP, historię operacji i możliwość wycofania dostępu. Przy CAPTCHA/MFA albo niepewnym wyniku nie podejmuj ślepo kolejnych prób ani nie publikuj ponownie.

**Stan techniczny:** 11.10.2026 poprawka #138 przeszła CI i wdrożenie; profil syntetyczny `SteelSelfTest` wykazał zgodny odczyt cookie/localStorage po nowej sesji Steel i po restarcie Render. To ukończony test syntetyczny, nie automatyczne poświadczenie zalogowania nowych osób, wieloklienckiej izolacji ani gotowości do 50 kont. Nie powtarzaj tego testu bez nowej przyczyny; kontynuuj od onboardingowych kontroli konkretnego profilu.

## Facebook — Watcher grup i delegowanie dostępu (11.10.2026)

**Zadanie:** wykrywać rzeczywiste pytania o usługi Napieraj i Synowie w grupach Spotted Radom, RADOM-OGŁOSZENIA, PORADY WETERYNARYJNE i Buldog Francuski Polska, z wynikami w ChatGPT. Zapisany automat „Zapytania klientów z Facebooka” (6ac79280a1708191897ad82e9e0e2655) jest obecnie WYŁĄCZONY i ma pozostać wyłączony do potwierdzenia nowego sposobu odczytu. Historyczny harmonogram: co 12 godzin, tylko odczyt, profil „Meta - Maciej - Monitoring”; nie uruchamiaj kolejnych prób logowania ani dodatkowego watchera. Repozytoryjny `.github/workflows/watcher.yml` jest ręcznym watcherem wakacyjnym, nie działającym watcherem grup FB.

**Zweryfikowane ograniczenia API (stan 11.10.2026):** oficjalny Facebook Groups API, `publish_to_groups` i `groups_access_member_info` usunięto 22.04.2024. Token Page, nowa aplikacja Meta, nowa strona i dodatkowy administrator NIE zapewniają oficjalnego odczytu feedu cudzych grup. Źródło: https://developers.facebook.com/docs/graph-api/changelog/version19.0/ . Facebook Page może poprosić o przyjęcie do grupy i działać przez UI, jeśli administrator grupy zezwala na strony; nie oznacza to dostępu grupowego Graph API: https://www.facebook.com/help/401492893195007 . Facebook Page ma zarządców z dostępem przez ich konta — nie ma osobnego logowania „do strony”, a dostęp zadaniowy nie pozwala automatycznie przełączać się w Page: https://www.facebook.com/help/289207354498410/ .

**Nowsza decyzja użytkownika, 11.10.2026 — pilotaż izolowany:** utwórz nową, odrębną stronę Facebook zarządzaną przez rzeczywistego, upoważnionego operatora i użyj wyłącznie nowego profilu AI Browser `Watcher - Operator - Pilot`. NIE przydzielaj jej dostępu do głównej Page przychodni (ID `138554046242234`) ani do kont Anity. Nowa strona i osobny operator są preferencją użytkownika w celu izolacji dostępu, a nie sposobem ominięcia kontroli Meta. Pierwsza grupa: `PORADY WETERYNARYJNE`, https://www.facebook.com/groups/3046642772082014/. W pierwszym odczycie w niezalogowanym, izolowanym profilu Facebook wskazał `Private group`, wymóg członkostwa do zobaczenia postów oraz zasadę odpowiadania tylko na pytania członków grupy. Następny krok: autoryzacja prawdziwego operatora w mobilnym oknie logowania, utworzenie nowej strony przez tego operatora, potwierdzenie jej dostępu do wskazanej grupy i identyfikatora Page. Profil techniczny jest utworzony i zapisany, ale jeszcze NIE zalogowany; członkostwa nowej strony i odczytu postów nie potwierdzono. Stary Watcher pozostaje wyłączony; nie uruchamiaj publikacji w grupach ani dostępu głównego profilu.

Rozdziel źródła monitoringu bez mnożenia logowań:
1. **Oficjalny Page Graph API / Webhooks (jeśli właściwe uprawnienia są faktycznie aktywne):** własna Page, wiadomości, komentarze, zgłoszone wzmianki i inne obsługiwane zdarzenia. Nie używaj tej ścieżki do fikcyjnego „czytania grup”.
2. **Wpisy z publicznych źródeł:** odnośniki znalezione w dostępnych bez logowania stronach / wyszukiwarkach, o ile rzeczywiście są opublikowane i dają się zweryfikować; traktuj ich zasięg jako niepełny i opóźniony.
3. **Grupy tylko przez uprawniony interfejs FB:** gdy Page jest rzeczywistym uczestnikiem, korzystaj z jej natywnego widoku lub dostępnych sygnałów powiadomień. Gdy grupa nie dopuszcza Page, opieraj ewentualny odczyt na prawdziwej, upoważnionej tożsamości człowieka, nie na nowym pozornym koncie. Nie zakładaj, że powiadomienia odzwierciedlają wszystkie posty.
4. **Wynik:** zapisuj źródło, link i datę wpisu, czas wykrycia, deduplikację, przydatność zapytania i jawny status `read_ok`, `partial`, `auth_required`, `unsupported_api` lub `source_unavailable`. Nie raportuj „zero wpisów”, gdy źródło było niedostępne.

**Błędy Facebooka:** usterki logowania, wyzwania bezpieczeństwa i nietypowa aktywność nie są błędami naprawianymi nową Page ani zmianą IP. Ogranicz niepotrzebne odświeżania i jednoczesne przeglądanie jednego konta, nie ponawiaj CAPTCHA/MFA, nie rotuj kont w celu obejścia blokad, nie zamieniaj obsługi błędu na automatyczny retry. Po wykryciu blokady wyłącz tylko zależną ścieżkę odczytu i uruchom niezależne źródła; zgłoś rzeczywistą przyczynę weryfikacji, jeśli jest widoczna.

## Programowy pilot Facebook Watcher — etap #140 (11.10.2026)

W repo scalono PR #140 (kod `src/facebook_pilot.py`, 15 testów `test_facebook_pilot.py`, oddzielny offline CI, `docs/FACEBOOK_WATCHER_PILOT.md`). Działający **program offline** przyjmuje już autoryzowane dowody wpisów z pierwszej grupy, sprawdza źródło i datę oraz deduplikuje w lokalnej bazie SQLite. **Aktualna decyzja właściciela:** Watcher identyfikuje kandydatów do wypowiedzi właścicieli autoryzowanych kont; nie generuje komentarzy firmowych. Każdy kandydat ma status `awaiting_individual_author`. Obecny pilot nie ma funkcji publikacji komentarzy. Nie wracaj do ponownego pytania o ogólną zgodę na pomoc przy publikowaniu opinii. Nie odczytuje prywatnej grupy sam, nie zakłada nowej Page, nie loguje operatora i nie publikuje nic na FB. GitHub Actions 38176778279: 15/15 PASS. Nie wdrażaj go w istniejącym Dockerze w przekonaniu, że jest to żywy watcher; brak jeszcze autoryzowanego źródła danych i trwałego prywatnego magazynu.

Główny blocker LIVE to nadal #139 — poprawne właścicielsko przypisane okno logowania dla profilu `Watcher - Operator - Pilot`. Stara blokada `PARALLEL_UNSCOPED_TOOL_DISABLED` chroni cudze sesje i nie może być obchodzona. Niezależnie od #139 wymagane jest potwierdzenie tożsamości operatora i dostępu do prywatnej grupy, zanim uznamy choćby odczyt pojedynczego wpisu za produkcyjny. Przy dalszych pracach korzystaj z powyższego ustalenia o zgodach zamiast ponownie pytać o ich istnienie; oddzielaj gotowy od niewdrożonego zakresu programu.

**Kryterium wznowienia:** przynajmniej jedna autoryzowana grupa z potwierdzonym sposobem odczytu i dowodem kompletności wybranego zakresu, zweryfikowana tożsamość, brak pętli logowania, odczytowe przebiegi i prywatny rejestr deduplikacji, jawny status wyników. Nie uruchamiaj automatycznego komentowania grup. Powyższe to decyzja architektoniczna i instrukcja, a nie potwierdzenie, że wszystkie grupy są monitorowane.

## Granice
Repo jest **PUBLICZNE**. Nie zapisuj tutaj haseł, tokenów, cookies, przechwyconych sesji, treści prywatnych dokumentów, grafik użytkowników ani odczytanych opinii klientów. Publiczne manifesty zawierają tylko ogólne zasady i jawne identyfikatory profili biznesowych. Prawdziwy rejestr opinii Anity utworzono w prywatnym Google Sheets, nie w GitHubie. Żaden inny tenant nie może go odczytać.

Nie zmieniaj realnych reklam, Metricool, treści, lokalizacji, proxy, VPN, rozliczeń Stripe live ani nie publikuj materiałów podczas audytu. VPN ani rotacja IP nie są metodą obejścia zabezpieczeń Meta. Autentyczny branding Anity: logo „N w domku”.

## Źródła instrukcji
- `docs/AUTONOMOUS_BROWSER.md` — workflow, checkpointy i bezpieczeństwo.
- `docs/BROWSER_CAPABILITIES.md` — co działa w LIVE, a co jest wyłącznie POC.
- `workflows/anita/reviews.yaml` — pierwsza procedura odczytu wizualnych opinii.
- `docs/CONNECTED_SERVICES.md` — wybór połączonego OAuth/API (Gmail, Windsor, WPVibe) przed logowaniem do Steel.

Samo AGENTS.md nie tworzy narzędzia ani trwałej pamięci w MCP; wymagana jest instalacja katalogu operacji w serwerze oraz osobny backend przechowywania danych. Nie ogłaszaj produktu gotowym do sprzedaży bez testów tenant isolation, cookies restore, deletion i SSRF.
