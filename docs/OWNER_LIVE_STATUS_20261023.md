# AI Browser — jedno źródło aktualnego stanu (owner beta)

**Snapshot:** 2026-10-23, wieczór (Europe/Warsaw). **Zawsze sprawdź produkcję przed działaniem**; stan zmienia się po wdrożeniu, zamknięciu sesji i wygaśnięciu dostępu.

## Potwierdzone LIVE przed #161

- Repo `napieraj2018-arch/Watcher-15`, gałąź `ai-browser-cloud`.
- Render: serwis `srv-db34e6ks728c73bae4sg`, plan Free, `autoDeploy=no`, jedna instancja.
- Bieżący potwierdzony SHA: `22dc8ca509ee1e2a7d4068113a9649ca2f5508cb` (PR #159), deploy `dep-dbdmj9rncjis73anga10` LIVE.
- 38 szyfrowanych przenośnych profili potwierdzonych w katalogu; ich obecność **nie** potwierdza bieżącego zalogowania.
- Wdrożone PR #157–#159: wymagane jawne opt-in CAPTCHA, zapisy profili natywnych i przenośnych, szyfrowane zadania `aib_task`, walidacja claim/lease/revision oraz operation_id.
- Rzeczywiste dwa zadania neutralne mają `completed`, `saved_closed` i potwierdzone checkpointy. Odczyt tego samego checkpointu z innej autoryzowanej rozmowy: **PASS**. Zakończenie *niedokończonego* zadania z innej rozmowy i awaria przy *aktywnej* sesji: **jeszcze nieudowodnione**.
- Wcześniej zaliczono neutralne odtworzenie cookie/localStorage/IndexedDB po zapisanym zamknięciu i wdrożeniu oraz pięć odizolowanych sesji w owner beta. To **nie** jest test 5 rzeczywistych kont, fizycznego iPhone'a ani autonomicznej pracy 24/7.

## Nowy incydent #160 — nie ignorować

23.10 o 17:19:57 i 17:53:29 UTC start technicznego profilu `Hosting - Test` dwukrotnie zakończył się `BrowserContext.set_storage_state` → `ERR_BLOCKED_BY_ADMINISTRATOR` dla `https://app.steel.dev`. Steel `POST /sessions` zwrócił 201, później dla dokładnej sesji `release` zwrócił 200. To dowód błędu importu zabronionego origin, **nie dowód usunięcia wszystkich profili**. Nie próbować automatycznego ponownego logowania ani nie omijać blokady dostawcy. Ten origin należy obsługiwać przez oficjalny panel poza przeglądarką zarządzaną przez tę samą usługę.

[PR #161](https://github.com/napieraj2018-arch/Watcher-15/pull/161) to ograniczona poprawka: rozpoznanie blokowanego importu bez odrzucania danych z szyfrowanej kopii, zachowanie poprawnej flagi wcześniejszej natywnej hydratacji, czytelny błąd MCP i testy. **Dopóki PR nie zostanie scalony, CI nie przejdzie i dokładny SHA nie trafi na Render, nie nazywać tej poprawki LIVE.**

## Dzienna praca — reguły, które nie mogą zniknąć

1. Najpierw `browser_sessions` i `aib_task(list)`, potem tylko potrzebne działania. Nie restartuj Render ani nie wdrażaj przy aktywnej sesji innej rozmowy.
2. W wieloetapowych pracach użytkownika domyślnie używaj `aib_task`: nowa claim, bezpieczny checkpoint, unikaj duplikatów, obowiązkowa weryfikacja po niejednoznacznym kliknięciu.
3. Zapisany profil ≠ aktywne uwierzytelnienie. Sprawdź właściwą witrynę, konto i aktualny stan; nowe MFA pozostaje decyzją właściciela.
4. Przy błędzie dostawcy: rozlicz dokładną sesję w Steel i we własnym sejfie przed kolejnym uruchomieniem. Nie resetuj guardu restartem.
5. **Nie wykonuj** niezleconych publikacji, resetów haseł, transakcji, doładowań ani wyłączania zabezpieczeń. Najpierw API/konektor, gdy jest dostępny.
6. Limity: maksymalnie pięć właścicielskich sesji Steel (neutralne testy), około 13 minut sesji, Render Free może się usypiać. Trwała kolejka jest **pasywna**, a nie samodzielnym workerem.
7. Repo jest PUBLICZNE. Nie wpisuj do niego prywatnych wiadomości, kluczy, cookies, kodów, nazw prywatnych kont ani identyfikatorów sesji dostawcy.

## Kiedy wolno napisać „gotowe do codziennego użytku”

Zamknąć [issue #160](https://github.com/napieraj2018-arch/Watcher-15/issues/160) dopiero po dowodach:
- poprawka storage restore w LIVE i wiarygodny brak utraty danych;
- jedno konkretne prawdziwe zadanie ChatGPT zakończone przez `aib_task`;
- inna autoryzowana rozmowa przejmuje *niedokończone zadanie* po potwierdzonym saved-close i kończy je bez duplikatów;
- bezpieczne zachowanie przy awarii aktywnej sesji i dokładne rozliczenie providera;
- test fizycznego iPhone'a lub jawnie wykazana blokada dostępu do fizycznego urządzenia;
- pełny saved-close, właściwy owner guard, brak osieroconych sesji po własnych testach.

**Status komercjalizacji:** NO-GO. Ten odbiór dotyczy *jednego właściciela*; osobno wymagane wieloklienckie bezpieczeństwo, izolacja, usuwanie natywnych danych, SSRF i płatności.

Wcześniejsze „HOLD” w AGENTS.md i BROWSER_CAPABILITIES.md opisują historyczne snapshoty i **nie mogą automatycznie unieważniać nowszych, niezależnie potwierdzonych LIVE odbiorów**.
