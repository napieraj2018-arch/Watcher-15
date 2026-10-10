# AGENTS.md — AI Browser (2026-10-10)

## Cel
Użytkownik wydaje jedno polecenie w ChatGPT; agent sam rozpoznaje właściwe konto, procedurę i ostatni bezpieczny checkpoint. Pracuje odczytowo domyślnie, bez ręcznego przepisywania treści i bez wysyłania użytkownika do innego promptu. Wymagane MFA i świadoma zgoda na publikację są wyjątkami, a nie codzienną obsługą.

## Każde uruchomienie
1. Sprawdź HEAD gałęzi `ai-browser-cloud`, aktywny deploy Render `srv-db34e6ks728c73bae4sg`, CI, `browser_sessions`, nazwę profilu oraz aktualną procedurę w `workflows/`.
2. Preferuj autoryzowane API/OAuth (Meta, Google Business, Search Console) zamiast ponownego otwierania logowania w przeglądarce, gdy API rzeczywiście zwraca potrzebne dane.
3. Nazwa zapisanego profilu, obecność cookie i `profile_saved=true` NIE dowodzą, że konto jest dziś zalogowane. Sprawdź bieżącą tożsamość i treść właściwej witryny. Issue #111: po restarcie Steel cookie i localStorage mogły być niespójne.
4. Nie próbuj ponownie logować się przy CAPTCHA/MFA, awarii strony lub niepewnym zamknięciu Steel. Zatrzymaj tylko dany krok i zwróć dokładny, zanonimizowany kod.
5. Jedno zadanie ma jeden tenant/profile/lease. Nie zatrzymuj cudzej sesji, nie otwieraj dwóch sesji na ten sam profil. Produkt ma mieć 3–10+ slotów, ale w LIVE nadal jest **1**; PR #116/#117 to offline PostgreSQL proof.
6. Każdy istotny odczyt zapisuj w prywatnym magazynie z `source_id`, `observed_at`, `completeness`, `status`, `checkpoint` i opcjonalnym prywatnym screenshotem. Nigdy nie uznawaj niewidocznego materiału za obejrzany.
7. Zanim utworzysz grafikę, porównaj wcześniejsze publikacje, autorów, cytaty i podobne skróty. Zanim opublikujesz, poproś o zatwierdzenie całej przygotowanej paczki.

## Granice
Repo jest **PUBLICZNE**. Nie zapisuj tutaj haseł, tokenów, cookies, przechwyconych sesji, treści prywatnych dokumentów, grafik użytkowników ani odczytanych opinii klientów. Publiczne manifesty zawierają tylko ogólne zasady i jawne identyfikatory profili biznesowych. Prawdziwy rejestr opinii Anity utworzono w prywatnym Google Sheets, nie w GitHubie. Żaden inny tenant nie może go odczytać.

Nie zmieniaj realnych reklam, Metricool, treści, lokalizacji, proxy, VPN, rozliczeń Stripe live ani nie publikuj materiałów podczas audytu. VPN ani rotacja IP nie są metodą obejścia zabezpieczeń Meta. Autentyczny branding Anity: logo „N w domku”.

## Źródła instrukcji
- `docs/AUTONOMOUS_BROWSER.md` — workflow, checkpointy i bezpieczeństwo.
- `docs/BROWSER_CAPABILITIES.md` — co działa w LIVE, a co jest wyłącznie POC.
- `workflows/anita/reviews.yaml` — pierwsza procedura odczytu wizualnych opinii.

Samo AGENTS.md nie tworzy narzędzia ani trwałej pamięci w MCP; wymagana jest instalacja katalogu operacji w serwerze oraz osobny backend przechowywania danych. Nie ogłaszaj produktu gotowym do sprzedaży bez testów tenant isolation, cookies restore, deletion i SSRF.
