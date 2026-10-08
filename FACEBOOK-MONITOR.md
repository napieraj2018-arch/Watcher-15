# Facebook Radom Watcher — darmowy pilot

## Co robi

Dwa pierwsze źródła:
1. https://www.facebook.com/p/Spotted-RADOM-100044524445707/
2. https://www.facebook.com/polecamradom/

Nasz skrypt odczytuje **wyłącznie widoczne publiczne podglądy wpisów** przy pomocy Playwright/Chromium na GitHub Actions, nawet jeśli strona zawiera przycisk "Log in" w stopce. Nie używa konta osobistego, ciasteczek ani haseł. Nie odpowiada, nie klika i niczego nie publikuje na Facebooku.

Nowy post z jednoznaczną prośbą o pomoc weterynaryjną lub architektoniczną, którego widoczny względny znacznik czasu wskazuje wiek najwyżej 120 minut, generuje GitHub Issue. Issue zawiera tylko temat (weterynarz/architekt), nazwę publicznej strony i publiczny permalink. Repozytorium i Issues są publiczne; cytaty i treści postów nie są publikowane.

GitHub przydziela Issue kontu napieraj2018-arch i może wysłać powiadomienie na połączony Gmail. Powiadomienia e-mail robota GitHub Actions zostały praktycznie sprawdzone za pomocą testowych Issues #69 i #70 dnia 8 października 2026.

Pierwsze uruchomienie zapisuje bazę znanych postów **bez alertów o historycznych publikacjach**. Kolejne uruchomienia zapisują tylko hashe permalinków w prywatnym cache GitHub Actions. Jeśli strona jest nieczytelna, system nie ogłasza "braku nowych wpisów"; zakłada jedno przypisane Issue informujące o problemie dostępu, nie co 15 minut.

## Uruchomienie i zatrzymanie

- GitHub Actions: .github/workflows/facebook-local-monitor-15m.yml
- Harmonogram: minuty 07, 22, 37 i 52 każdej godziny UTC, czyli średnio co 15 minut. GitHub nie gwarantuje startu dokładnie o zadanej minucie.
- Po scaleniu do gałęzi głównej nastąpi także pierwsze uruchomienie typu push (baseline).
- Brak płatnych API, brak dodatkowego Render i brak potrzeby logowania do Facebooka na potrzeby tych **dwóch publicznych źródeł**.
- Aby wstrzymać działanie, ustaw w GitHub Actions variables repozytorium zmienną FB_WATCH_ENABLED na false lub usuń workflow; uruchomienia manualne mogą nadal działać.
- Osobną listę źródeł przechowuje config/facebook_local_monitor.json.
- Brakujące informacje na stronie oznaczają utratę pokrycia, nie dowód braku zapytań.

## Granice

**To nie jest monitoring wszystkich postów/komentarzy**. W teście GitHub widział jeden ostatni publiczny post na każdej z dwóch stron. Starsze, ukryte i prywatne wpisy i komentarze mogą pozostać niewidoczne. Test nie dowodzi dostępu do grup zamkniętych. Częstość 15 minut nie gwarantuje pełnego pokrycia.

Nie należy wgrywać sesji Facebooka do publicznego repozytorium. Konto Meta - Maciej - Monitoring w AI Browserze istnieje, ale nie przeszło zalogowania po 2FA; do tego pilota **nie jest potrzebne**.

Automatyczny odczyt może być ograniczany przez Meta lub jej regulamin; kod nie obchodzi CAPTCHA, checkpointów ani ograniczeń dostępu. Dla prywatnych grup potrzeba osobnego podejścia i zgód.

## Weryfikacja

- 08.10.2026 pierwsza próba bez obsługi publicznego login bannera: status login_required.
- Następnie parser poprawiono: test odczytał z obu stron po jednym poście.
- Potwierdzono testy klasyfikacji, deduplikacji i znaczników czasu.
- Potwierdzono bot-authored GitHub Issue #70 i jego dostarczenie e-mailem.
- Dodatkowy test bazowy dwóch kolejnych skanów potwierdził zapis hashy; część odczytów Facebooka była jednak intermittently niedostępna, więc aktywne alarmowanie o dostępności jest potrzebne.
- Harmonogram produkcyjny uruchamia się dopiero po scaleniu kodu do main.

## Pliki

- src/facebook_local_monitor.py — pobieranie publicznych wpisów, filtrowanie, deduplikacja
- src/facebook_notify.py — Issue z linkiem, pojedynczy alarm o problemie dostępu
- tests/test_facebook_local_monitor.py, tests/test_facebook_notify.py — testy jednostkowe
- src/facebook_monitor_ai_browser.py — eksperymentalny adapter prywatnego profilu, NIE jest częścią aktualnego harmonogramu
- .github/workflows/facebook-local-monitor-test.yml — oddzielny workflow do testów


## Nowe grupy zgłoszone 8 października 2026

Użytkownik przesłał zrzuty trzech dodatkowych grup. Zapisane w \`config/facebook_local_monitor.json\`:

- \`RADOM-OGŁOSZENIA\` — facebook.com/groups/158171638326502/; 63,0 tys. członków, URL i tożsamość zweryfikowane. \`enabled=false\` ponieważ test GitHub Actions [#37765758813](https://github.com/napieraj2018-arch/Watcher-15/actions/runs/37765758813) zakończył się stanem \`login_or_verification_required\`, 0 widocznych postów. Włączenie mimo błędu dałoby fałszywe poczucie kompletnego monitoringu.
- \`Spotted Radom\` (grupa ok. 21,1 tys. członków) — dokładny adres ID grupy niepotwierdzony; oczekuje na skopiowany link z aplikacji Facebook. Nie pomylić z obserwowaną już stroną \`Spotted : RADOM\` ani grupą \`Spotted: Radom\` z ok. 67 tys. członków, której działanie zostało wstrzymane.
- \`PORADY WETERYNARYJNE\` — pokazana jako grupa we wpisie o psim okuliście, URL/ID niepotwierdzone. Oczekuje na skopiowany link. Przy późniejszej kwalifikacji zapytań należy pamiętać o geograficznej przydatności: pytanie ograniczone do Krakowa lub południa woj. świętokrzyskiego nie jest automatycznie wartościowym leadem w Radomiu.

**Stan faktyczny:** 2 aktywne strony Facebooka; 3 nowe grupy zapisane jako źródła oczekujące na adres/dostęp. Nie ma jeszcze skutecznego ciągłego odczytu nowych postów z tych trzech grup. Obecny system co 15 min nie wymaga loginu i działa na dostępnych publicznych podglądach dwóch stron.

