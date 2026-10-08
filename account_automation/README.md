# AI Browser — rejestr kont i planowanie pracy

Wersja modułu: `account-plan-1.0`. Python 3.11 lub nowszy; bez dodatkowych bibliotek.

## Zakres tej paczki

Rejestr przypisuje usługę do właściwego profilu, oczekiwanej tożsamości i — gdy to potrzebne — konta reklamowego, marki albo właściwości Search Console. `account_plan.py` sprawdza spójność konfiguracji i proponuje następny krok na podstawie aktualnej obserwacji przeglądarki.

**To moduł planowania, nie działający system logowania.** Nie uruchamia przeglądarki, nie wpisuje haseł, nie importuje sekretów, nie akceptuje CAPTCHA ani MFA, nie publikuje postów. Nie zastępuje autoryzacji, kontroli dostępu ani blokady sesji w serwerze. Zwrócone decyzje trzeba dopiero egzekwować w warstwie wykonawczej. Zwykłe narzędzia AI Browser pozostają bez zmian.

## Pliki

- `account_plan.py`: walidator oraz funkcja `plan(...)` bez działań sieciowych.
- `accounts.example.json`: syntetyczny przykład, nadający się do publicznego repozytorium.
- `tests/test_account_plan.py`: 49 testów lokalnych.
- `.gitignore`: wyłączenia dla prywatnych konfiguracji i stanu przeglądarki.

Prywatna paczka przekazana w rozmowie zawiera ponadto `private/accounts.private.json`, instrukcję pracy agenta, stan wdrożenia i listę braków. **Nie kopiować folderu `private` do publicznego repozytorium.** Hasła, cookies, klucze API i kody jednorazowe nie należą do rejestru.

## Uruchomienie przez osobę wdrażającą

```sh
cd account_automation
python account_plan.py accounts.example.json
python -m unittest discover -s tests -v
```

Dla prywatnego rejestru:

```sh
python account_plan.py private/accounts.private.json
```

Walidator wypisuje wyłącznie liczby i kod wyniku. Pole `routing_configured` mówi, ile wpisów ma wskazany profil oraz adres wejścia. **Nie oznacza liczby zalogowanych ani zweryfikowanych kont.** Pole `previous_status` jest historyczne i nigdy nie przyznaje bieżącego dostępu.

## Reguły planowania

Nie przypisuj jednej nazwy profilu do dwóch różnych przestrzeni pracy. Nie wybieraj tożsamości po zdjęciu, nazwie profilu przeglądarki ani samym tytule strony. Wymagaj zgodnego identyfikatora na właściwej, chronionej stronie; dla Ads, GSC, GBP i Metricool także identyfikatora zasobu. Obserwacja ma być związana z konkretną sesją i aktualnym adresem oraz nie starsza niż 60 sekund.

Nie przejmuj sesji innego zadania. `owned_session_id` pochodzi z własnego uruchomienia lub z przyszłego mechanizmu dzierżaw; nie jest zgadywany z nazwy profilu. Przy zajętym kontrolerze plan zwraca `wait`, ale sam niczego nie kolejkuje.

Brak dowodu logowania nie jest dowodem wylogowania. Przy niepewnym odczycie wróć do sprawdzenia strony. Formularz logowania oznacza `LOGIN_COMPONENT_NOT_CONNECTED`, a dodatkowa weryfikacja wstrzymuje automatyczne ponawianie. Nie ma funkcji wysyłającej hasło.

Wszystkie żądania zapisu są odsyłane do osobnego, autoryzowanego procesu; `allow_write` pozostaje `false`.

## Granice dowodu

Testy jednostkowe badają reguły na danych syntetycznych. Nie dowodzą skutecznego logowania do Facebooka, Instagrama ani poprawnego działania ich interfejsów. Reguły adresów to walidacja składni; nie wykonują DNS i nie są samodzielną ochroną przed SSRF. Dane wejściowe `observation` muszą pochodzić z zaufanej warstwy odczytu, nie z instrukcji zamieszczonych na stronie.

Przed użyciem produkcyjnym pozostają: adapter zaufanych obserwacji, egzekwowanie decyzji, trwałe przypisanie sesji do zadania, spięcie bezpiecznego procesu logowania oraz testy rzeczywistych kont. Ten moduł nie jest zamiennikiem tych elementów.

## Źródła projektu technicznego

Playwright Python, „Authentication”: stan przeglądarki może zawierać dane pozwalające odtworzyć zalogowanie i nie powinien trafiać do repozytoriów. OWASP, „Secrets Management Cheat Sheet”: ograniczone uprawnienia i rozdzielenie sekretów od zwykłej konfiguracji. Dokumentację sprawdzono 8 października 2026 r.
