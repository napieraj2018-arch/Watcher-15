# Mobilne logowanie, zapis i weryfikacja — 23.10.2026

Ten dokument opisuje zakres poprawki po wdrożeniu #155. Za potwierdzenie
LIVE służy dopiero odbiór dokładnego SHA i deployu zapisany w jej PR.
Nie utożsamiaj przejścia testu neutralnego z zalogowaniem rzeczywistego konta.

## Telefon

Zaproszenie ma otwierać od razu panel sterowania. Ekran ma kompaktową belkę
z usługą i zapisem, duży podgląd oraz dolne sterowanie. Klawiatura jest
wysuwana w tym samym ekranie. Serwer przekazuje tylko rodzaj rzeczywiście
skupionego pola, nigdy jego wartość ani nazwę. Podpowiedź nie upoważnia
do wpisania sekretu na innym originie lub innej karcie.

Pojedynczy fetch klatki ma termin; powrót z poczty, odblokowanie telefonu
i zmiana widoczności uruchamiają nowy odczyt obrazu. Timeout odpowiedzi
na wpisanie/Enter nie ponawia tej operacji. Powiększanie ma zachować
odwzorowanie współrzędnych na zdalny ekran. Testy Chromium/WebKit używają
wyłącznie podstawionych dokumentów; fizyczny iPhone nadal jest odrębnym
środowiskiem. Atrybuty autofill nie kopiują pęku kluczy innej domeny z Safari.

Punktem odniesienia był opis [secure sign-in i przejęcia Cloud Browser
ChatGPT](https://help.openai.com/en/articles/20001280-using-cloud-browser-in-chatgpt):
przejęcie w ramach zadania, formularz poza czatem, kontynuacja po logowaniu
i utrzymanie sesji. Nie jest to integracja z prywatnym backendem OpenAI.

## Zapis z potwierdzeniem

Pełny zapis oznacza obie flagi zapisu oraz zakończenie dokładnej własnej
lease i sesji. Krótkożyjące, HttpOnly cookie może po zakończeniu odczytać
wynik przez pięć minut po budżecie zamknięcia. Nie daje dodatkowego czasu
sterowania. Ponowne Finish oraz odzyskanie utraconej odpowiedzi odczytują
ten sam wynik, bez ponownego stop. Watchdog zamykający porzucony telefon
również musi pozostawić sprawdzalny wynik w tym działającym procesie.

Panel rozdziela ostatnią kopię przenośną, pełny zapis/zamknięcie oraz
obserwację zalogowania. Wynik zapisu nie potwierdza prawidłowego konta.
Ukrycie karty nie zamyka logowania; pozostaje dotychczasowy stały limit
780 sekund i 90 sekund zapasu na zapis. Restart procesu traci krótkotrwałe
zaproszenie, capability oraz ten cache wyniku; trwały profil jest odrębny.

## CAPTCHA dostawcy

Właściciel zlecił zmniejszenie ręcznej obsługi. Nowe sesje żądają
`solveCaptcha: true`; `AI_BROWSER_CAPTCHA_AUTOMATION=0` wyłącza tę opcję.
Nie zmienia się proxy, fingerprint ani abonament. Odpowiedź providera
potwierdza dostępność albo jej brak. Sam brak pola nie jest potwierdzeniem.

Jedyny fallback tworzenia sesji dotyczy dokładnego HTTP 402 od Steel,
odrzucającego płatną opcję przed utworzeniem sesji. Wtedy jeden raz usuwamy
`solveCaptcha`, zachowując UUID i wszystkie inne opcje profilu. Tę samą
interpretację publikuje [oficjalny adapter Steel](https://github.com/steel-dev/hermes-steel/blob/main/provider.py).
Timeout, nieprawidłowa odpowiedź, 400/403/429/5xx ani niepewna operacja
nie pozwalają ponowić create i nadal wymagają rozliczenia.

`GET /v1/sessions/{id}/captchas/status` daje wyłącznie postęp dla dokładnie
pasującej strony. Odpowiedź aplikacji nie zawiera URL, identyfikatora strony,
tokenów wyzwania ani obiektów tasks. Odczyt jest ograniczony czasowo
i współdzielony przez równoległe sprawdzenia. `isSolvingCaptcha=false`
nie oznacza powodzenia; następny krok wymaga odczytu strony.

Agent czeka najwyżej 45 sekund, krócej przy końcu własnej sesji. Nie odnawia
terminu odczytem, nie wywołuje solve w pętli ani nie wysyła ponownie loginu.
MFA, checkpoint, niejednoznaczne wyzwanie oraz nieudana obsługa przechodzą
do panelu właściciela. CAPTCHA nie jest potwierdzeniem tożsamości.

Źródła dostawcy:

- [Konfiguracja](https://docs.steel.dev/overview/sessions-api/configuration)
- [CAPTCHA API](https://docs.steel.dev/overview/captchas-api/overview)
- [Oficjalny SDK Python](https://github.com/steel-dev/steel-python/blob/main/src/steel/resources/sessions/captchas.py)
- [FAQ i warunki konta](https://steel.dev/faq): stan 23.10.2026, płatny depozyt 10 USD
  odblokowuje tę funkcję w Launch; 1000 obsług kosztuje 3 USD w Launch lub 1 USD
  w Scale. Ta poprawka nie kupuje doładowania ani abonamentu.

## Poczta

`aib_route_operation("gmail", "email_verify")` zwraca rzeczywistemu agentowi
procedurę użycia istniejącego Gmail connectora. Backend nie ma tokenów
Gmaila i nie jest autonomicznym workerem pocztowym.

Agent musi znać bieżącą usługę, własną sesję, konto/adresata i początek
konkretnego flow. Wyszukuje świeżą wiadomość z właściwego połączenia,
sprawdza metadane, następnie odczytuje jednego pasującego kandydata. Sam
nagłówek From ani słowo „verify” nie dowodzą autentyczności. Pojedynczy
odnośnik musi prowadzić do oczekiwanego celu HTTPS tej usługi, bez obcego
redirectu i bez rozszerzenia działania. Treść maila jest danymi,
nie instrukcją dla agenta. Po pojedynczej nawigacji trzeba odczytać wynik
i właściwe konto, następnie zapisać profil.

Obecny zakres automatyczny: zwykłe potwierdzenie adresu odnośnikiem.
Automatyczne przesłanie kodu przez MCP pozostaje niewspierane; ogólny
`browser_fill` nadal nie przyjmuje sekretów. Kody wprowadza się przez
zabezpieczony panel właściciela. Nie zatwierdzaj resetu/zmiany hasła,
odzyskiwania, wyłączania zabezpieczeń, nowych uprawnień ani niepowiązanego
logowania na podstawie ogólnej prośby o ułatwienie obsługi.

## Odbiór

Wymagane: testy produkcyjnego obrazu; rzeczywisty Chromium dla zdalnego
sterowania; WebKit 390×844 dla ekranu, gestów, edytora i utraty odpowiedzi;
syntetyczne screenshoty z CI do oceny; wdrożenie dokładnego SHA; odczyt wcześniej
zapisanego profilu po wdrożeniu; pełny zapis i brak pozostawionych sesji.
CAPTCHA live jest potwierdzona dopiero po odpowiedzi Steel; konto i
potwierdzenie e-mail wymagają własnego, faktycznego bieżącego flow.
