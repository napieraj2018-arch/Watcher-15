# AI Browser — normalne okno dla człowieka (projekt UI v1)

## Co jest w tym katalogu

- index.html — interaktywny demonstrator, projekt zbliżony do zwykłej przeglądarki na iPhonie i komputerze.
- tests/test_browser_window.py — 20 testów na realnym Chromium (uruchamiane przez GitHub Actions).
- Wszystkie nazwy profili i domeny są SZTUCZNE. Prototyp nie wykonuje żądań do stron WWW i nie czyta cookies, kont lub haseł.
- Zrzuty ekranu z testów: GitHub Actions run 37898066149, załącznik ai-browser-ux-preview-screenshots, ważność siedem dni.

## Dlaczego zamiast linku Live

Użytkownik chce korzystać z przeglądarki jak z Safari. Sesja chmurowego Chromium nadal jest potrzebna technicznie, ale UI nie powinien żądać: "start session", "copy Live URL" czy "set read_only/write" przed każdym użyciem.

Zamiast tego:
1. Użytkownik wybiera profil. Kliknięcie Otwórz wysyła JEDNĄ autoryzowaną prośbę o wznowienie.
2. Serwer sprawdza tenanta, uprawnienia, dzierżawę sesji i stan zapisanego profilu. Jeżeli przeglądarka zajęta, UI wyświetla "Kolejka, pozycja 2", a nie kolejny formularz logowania.
3. Serwer tworzy/odzyskuje krótkotrwałą sesję Steel, pod spodem używając istniejącego trwałego profilu.
4. Klient dostaje jednorazowe, krótkotrwałe połączenie do osadzonego viewer. Token viewera nie jest w pasku adresu ani logach/analytics.
5. Człowiek widzi kartę i stronę; dostępne są Wstecz, Dalej, Odśwież, Karty, Nowa karta, Profil, Więcej. Tylko jeden aktywny sterujący przydział na zadanie.
6. Zapis i autozapis są osobnym stanem: "Zapisano", "Zapis w toku", "Niepewny wynik". Nie pokazuj "Zapisano" przed potwierdzeniem profilu Steel READY oraz kopii zapasowej.
7. Po rozłączeniu urządzenia użytkownik otwiera ten sam profil ponownie, bez logowania, o ile dostawca konta nadal uznaje sesję.

## Kontrakt bezpiecznych endpointów — do wykonania, nie obecna produkcja

Każde żądanie identyfikuje użytkownika poprzez serwerowo zweryfikowany login, a nie podany ręcznie tenant_id. Profil i dane są przypisane do tego tenanta. Przeglądarka nie jest kontrolowana przez samo poznanie publicznego UUID.

- POST /api/window/open { profile_id } => { window_id, status: starting|ready|queued|reauth_required, position? }. Idempotency-Key obowiązkowy, żeby podwójne kliknięcie nie utworzyło dwóch sesji.
- GET /api/window/{id}/status => {status, active_tab_id, tab_count, owner, expires_at}. Bez cookies, WebSocket secret i numerów prywatnych kont.
- POST /api/window/{id}/navigate {tab_id, url} => wynik albo odmowa. Uprawnienia odczyt/zapis stosowane do KAŻDEJ operacji, a nie tylko startu.
- POST /api/window/{id}/new-tab => {tab_id}, owner-only.
- POST /api/window/{id}/switch-tab => {tab_id}, owner-only.
- POST /api/window/{id}/delegate-human => krótkotrwały handoff, połączony z MFA i tym samym kontem; jawne odwołanie.
- POST /api/window/{id}/close => {profile_saved, provider_profile_ready, encrypted_backup_saved}, w razie błędu jawne "niepewne" bez utraty dzierżawy.
- GET /api/profiles => lista wyłącznie własnych profili; brak dostępu do cudzych po wpisaniu UUID.

Są to propozycje API, których jeszcze nie ma. Nie podłączać demonstratora bez weryfikacji tych warunków.

## Ergonomia

- Minimum 44×44 pt obszaru dotykowego.
- Na iPhonie na dole stale widoczne: Wstecz, Dalej, Odśwież, Karty, Więcej. Profil w górnym pasku.
- Pole adresu 16px+ na iOS, aby uniknąć auto-zoom przy wpisywaniu.
- Klawiatura na komputerze: Control/Command+T, Escape, nawigacja tabulatorem.
- Podstawowe stany wizualne: połączenie, oczekiwanie, wymaga logowania, błąd odczytu i brak połączenia; nie uznawać cookies za wystarczające potwierdzenie zalogowania do wybranej firmy.
- Żadnych technicznych etykiet w podstawowym oknie: CDP, port 10000, session_id, Steel API key, MCP token, profile UUID.
- Pełne sterowanie dla klienta i agenta musi przechodzić przez serwerowy broker z fencing — nigdy przez te same równoległe komendy.

## Warunek integracji

UI należy połączyć z backendem DOPIERO po ukończeniu izolacji dwóch zewnętrznych klientów, wygasania/odtwarzania sesji i bezpiecznego handoffu przy MFA. Prototyp nie jest gotowy do publicznego wyświetlania prawdziwych kont.

Źródła dobrych wzorców: Apple HIG Toolbars/Buttons; Browserless Session Management; Steel Profiles; Cloudflare Browser Run Live View.