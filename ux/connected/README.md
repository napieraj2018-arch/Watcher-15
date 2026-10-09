# AI Browser — demo zwykłego okna z automatycznym startem karty

**Wyłącznie lokalny symulator.** Nie wpisuje haseł, nie łączy się ze Steel, Facebookiem, Google ani Instagramem. Nie zastępuje działającego AI Browser na Renderze.

## Co teraz można przetestować

Użytkownik nie klika przycisku Live. Wpisuje adres lub wybiera skrót w zwykłym oknie. Frontend przesyła żądanie do BFF działającego pod **tym samym adresem**. Testowy backend wykorzystuje moduł workspace_broker:

1. Gdy instancja jest wolna, automatycznie tworzy fikcyjną sesję wyłącznie do odczytu.
2. Druga karta tej samej przestrzeni i zadania wykorzystuje tę samą fikcyjną sesję.
3. Gdy aktywne jest zadanie przychodni, otwarcie strony w przestrzeni Architekt pokazuje „W kolejce”, bez pętli logowania.
4. Po świadomym zakończeniu testowego zadania przychodni kolejka obsługuje kartę Architekt.
5. Nietypowy Origin, próba ustawienia cudzej firmy, niedozwolona domena i próba zamknięcia sesji niewłaściwym zadaniem są odrzucane.
6. Odpowiedzi API nie ujawniają technicznego identyfikatora sesji.

**Wszystko dzieje się tylko w pamięci procesu i w lokalnym Chromium.** Prawdziwa treść odwiedzanej strony nadal nie jest wyświetlana.

## Uruchomienie wyłącznie na własnym komputerze

Z głównego katalogu repozytorium uruchom:

    python ux/connected/demo_server.py --port 8060

Następnie otwórz:

    http://127.0.0.1:8060/demo

Serwer nasłuchuje **tylko na 127.0.0.1**. Nie publikuj go w Renderze, Floot, GitHub Pages ani w publicznej sieci; nie ma produkcyjnego uwierzytelniania.

## Testy

Workflow: .github/workflows/auto-window-demo-tests.yml

    python -m pip install playwright==1.59.0
    python -m playwright install --with-deps chromium
    python -m unittest discover -s ux/connected/tests -v

Sprawdza rzeczywisty interfejs w Chromium i wywołania BFF przez localhost. W workflow są również ponawiane podstawowe testy interfejsu i kolejki.

## Co pozostało do uruchomienia u klientów

Nie można podłączyć tej demonstracji bezpośrednio do aktualnego globalnego MCP. Najpierw wymagane są: uwierzytelnianie kont klienta, oddzielne profile tenanta, rzeczywista kolejka i dzierżawy z transakcyjnym fencing tokenem, bezpieczny reverse proxy do widoku strony, izolacja screenshotów, bezpieczna obsługa MFA, usuwanie danych i limity kosztów.

Działający wygląd nie jest równoznaczny z produkcyjną niezawodnością logowania. Każdy przyszły adapter Steel wymaga osobnego testu na profilu technicznym i dwóch niezależnych klientach.
