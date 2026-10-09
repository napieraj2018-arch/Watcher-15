# AI Browser — nowe mobilne okno (prototyp interaktywny)

Ten katalog zawiera pierwszą, działającą w zwykłym Chromium wersję interfejsu na iPhone i komputer. **Nie łączy się z prawdziwymi stronami ani kontami.** Nie wymaga haseł i niczego nie publikuje. Nie jest jeszcze częścią panelu produkcyjnego.

## Co działa w interfejsie

- Dolny pasek adresu i przyciski Wstecz/Dalej.
- Karty: nowa, wybierz, zamknij, historia i oddzielne stosy dla Przychodnia / Architekt / Test.
- Menu, status i szybkie skróty.
- Obszar dotykowy minimum 44 × 44 px dla przycisków; safe-area i szerokości 320–1365 px.
- Escape, Ctrl/Cmd+L oraz Ctrl/Cmd+T, fokus dialogu i etykiety dla czytników ekranowych.
- Bezpieczna walidacja adresów, brak wstrzyknięć HTML, brak zewnętrznego ruchu sieciowego.
- Brak cookies, haseł i zapisywania historii w localStorage.

**Ograniczenie:** adres i karty są interaktywne, ale treść stron pozostaje wyraźnie oznaczonym podglądem. To nie jest jeszcze działające surfowanie po zewnętrznych stronach.

## Uruchomienie lokalne

Uruchom polecenia w repozytorium:

    cd ux/mobile
    python -m http.server 8000

Następnie http://127.0.0.1:8000/workspace.html.

## Testy rzeczywistego Chromium

Workflow: .github/workflows/mobile-workspace-ux.yml

    python -m pip install playwright==1.59.0
    python -m unittest discover -s ux/mobile/tests -v

Testy obejmują iPhone, wąski ekran, desktop, przyciski, klawiaturę, karty, historię, przestrzenie firm, odrzucanie niebezpiecznych adresów i brak ruchu do obcych domen. Screenshoty testów trafiają do artefaktu GitHub Actions.

## Potrzebna integracja — jeszcze wyłączona

Użytkownik ma widzieć zwykłe okno, a sesję cloud powinien uruchamiać backend po użyciu karty. Nie usuwa to wymogu sesji Steel; usuwa potrzebę ręcznego szukania technicznego okna Live.

1. Osoba wybiera przestrzeń i stronę. Backend sprawdza rolę użytkownika i przynależność firmy.
2. Serwer rezerwuje atomowo profil z dzierżawą konkretnego tenanta/zadania. Nigdy nie przyznaje kontroli na podstawie samej nazwy profilu z frontend.
3. Jeśli sesja już działa, backend ją wykorzystuje. Jeśli zajęta: zwraca stan kolejki, a nie pętlę ponawiania start.
4. Sesja Steel jest uruchamiana automatycznie po żądaniu ze stałym profilem, bez ujawniania kluczy i cookies klientowi.
5. Gdy strona jest gotowa, prywatny widok strony pojawia się w oknie UI. Przejęcie sterowania dla MFA wymaga bezpiecznego, krótkotrwałego dostępu tylko dla właściciela.
6. Karty mogą współdzielić jeden profil wyłącznie w obrębie tej samej firmy i tenanta. Przełączenie firmy nie miesza cookies.
7. Zamykanie sesji potwierdza zapis pełnego profilu oraz stan READY po stronie Steel, a dopiero potem zwalnia dzierżawę. Niepewny zapis oznacza potrzebę naprawy, nie nową serię logowań.

Backend BFF będzie mógł zostać podłączony po wdrożeniu izolacji tenantów; dzisiejszy wspólny MCP nie jest wystarczającym kontraktem komercyjnym.

## Wzorce produktów

Safari — dolny pasek adresu i znane karty: https://support.apple.com/en-euro/guide/iphone/ipha9ffea1a3/ios

Arc Search — szybka wyszukiwarka, uproszczone sterowanie kciukiem: https://resources.arc.net/hc/en-us/articles/20887042551831-Arc-for-iOS-Android-Arc-Search

Browserbase — podgląd agenta i przekazanie kontroli człowiekowi: https://www.browserbase.com/blog/what-is-a-browserbase-browser

Steel — trwałe profile i oddzielne procesy sesji: https://docs.steel.dev/overview/profiles-api/overview

Apple — wygodne obszary dotykowe: https://developer.apple.com/design/human-interface-guidelines/buttons

To niezależny projekt kodu i wyglądu, nie kopia innych aplikacji.
