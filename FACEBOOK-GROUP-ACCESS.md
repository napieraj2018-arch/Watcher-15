# Facebook Groups: weryfikacja sesji i dostępu (projekt, NIE aktywny monitoring)

**Status 08.10.2026:** 4/4 dokładne adresy grup zapisane w \`config/facebook_local_monitor.json\` na \`main\`; nadal wyłączone, ponieważ brak zweryfikowanego automatycznego odczytu postów.

| Grupa | ID | Dostęp |
|---|---|---|
| Spotted Radom | 1886172518407420 | publiczna, Facebook wymaga loginu przy automatycznym odczycie |
| RADOM-OGŁOSZENIA | 158171638326502 | publiczna, Facebook wymaga loginu przy automatycznym odczycie |
| PORADY WETERYNARYJNE | 3046642772082014 | prywatna, posty wyłącznie dla członków |
| Buldog Francuski Polska | 1756386991256822 | prywatna, posty wyłącznie dla członków |

Istniejący bezpłatny Watcher na gałęzi \`main\` nadal monitoruje wyłącznie dwie publiczne **strony** (nie grupy). Nie modyfikować go, dopóki pilot nie przejdzie realnych testów.

## Przetestowane

1. Playwright w GitHub Actions (bez konta) dla grup \`Spotted Radom\` i \`RADOM-OGŁOSZENIA\` zgłasza \`login_or_verification_required\`, 0 nowych postów. **Nie uznawać za sukces.**
2. Próby alternatywnych publicznych \`share/g/\` także kończą się na /login; pojedynczy znany URL posta może być dostępny, ale to nie jest kanał odkrywania nowych postów. GitHub Actions [#37770712332](https://github.com/napieraj2018-arch/Watcher-15/actions/runs/37770712332).
3. Profil \`Meta - Maciej - Monitoring\` jest cloud_persisted, lecz kolejny restart pokazał ekran \`Log in to Facebook\`. Nie oznaczać profilu jako zalogowanego.
4. Jednorazowy test modułu \`src/facebook_group_access_probe.py\` ma 11/11 poprawnych testów logiki. GitHub Actions [#37770294158](https://github.com/napieraj2018-arch/Watcher-15/actions/runs/37770294158). **Nie jest to potwierdzenie odczytu żywych postów grup.**

## Następny krok (tylko z udziałem właściciela przy logowaniu)

- Utworzyć nowy jednorazowy link setup dla profilu \`Meta - Maciej - Monitoring\`, czas do 10–15 minut. Poprzednie okno Steel zamknęło się i sesja wymaga nowego logowania.
- Właściciel sam wpisuje hasło i kod 2FA w zdalnej przeglądarce i akceptuje ewentualne potwierdzenie na iPhonie. Nie zbieraj kodów/hasła w ChatGPT.
- Po przejściu na zalogowaną stronę Facebooka właściciel wybiera Save profile and close.
- W uruchomionym przez asystenta AI Browser w trybie \`read_only\` sprawdzić profil dwukrotnie, przez osobne sesje stop/start. Potwierdzić konto, widoczne linki do rzeczywistych postów oraz członkostwo w obu grupach prywatnych; gdy członkostwo nie istnieje, niczego nie dołączać automatycznie.
- Liczyć tylko permalinki należące do konkretnego ID grupy. Nie kopiować treści, użytkowników ani ciasteczek do publicznego repo.

## Wyraźne ograniczenie kosztów

Silnik AI Browser jest teraz uruchamiany na Steel Cloud. Launch ma \`$30\` *jednorazowych* darmowych kredytów (nie jest darmowy bez ograniczeń), a sesje są rozliczane według czasu działania po wyczerpaniu kredytów. Nie uruchamiać harmonogramu co 15 minut na Steel Cloud, dopóki nie ma bezpiecznego sposobu zachowania sesji na darmowym runnerze oraz pewnego limitu kosztu 0 zł.

## Bezpieczeństwo i dostarczanie alertów

- Grupy prywatne: żadnych tekstów, nazwisk, permalinków ani innych danych postów w **publicznych** Issues. Wymagane prywatne powiadomienie (np. SMTP z sekretu lub prywatne repo); nie mylić testowych bot-authored Issues #69/#70 z potwierdzeniem bezpiecznej obsługi grup prywatnych.
- Nie obchodzić CAPTCHA, checkpointów, ograniczeń API, ani nie pisać automatycznych komentarzy.
- Zachować minimalny zakres: wyłącznie posty dostępne dla upoważnionego członka grupy i tylko za zgodą platformy oraz administratorów, gdy jest wymagana.
- Nie włączać alertów ani harmonogramu na podstawie samego \`200 OK\` lub samego tytułu grupy. Potwierdzić rzeczywiste datowane wpisy, brak duplikatów, oraz działające doręczenie prywatnego alertu.

