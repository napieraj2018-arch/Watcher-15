# Facebook Watcher — pilot jednej grupy (11.10.2026)

## Zakres
To adapter **w istniejącym repo Watcher-15**, nie kolejna aplikacja.
Pierwsza grupa: PORADY WETERYNARYJNE (ID 3046642772082014).
Przeznaczony profil: `Watcher - Operator - Pilot`, osobno od konta Macieja, głównej Page 138554046242234 i kont Anity.

## Co jest naprawdę napisane
`src/facebook_pilot.py` przyjmuje paczkę dowodów postów z już autoryzowanego źródła, weryfikuje dokładną grupę, URL, datę i status dostępu, rozpoznaje potencjalne pytania weterynaryjne, odrzuca nieistotne/za stare wpisy, zapisuje **kandydata do indywidualnego komentarza**, bez układania tekstu komentarza w imieniu przychodni ani w imieniu innej osoby, i atomowo usuwa duplikaty w lokalnej bazie SQLite.

Nie przechowuje pełnej treści postów ani nazw autorów, nie loguje ich na standardowe wyjście. Wynik importu zawiera tylko statusy i liczniki. Pilne zapytania oznacza do przeglądu.

Ten kod **nie loguje** użytkownika do Meta, **nie pobiera** postów z zamkniętych grup, **nie zakłada** strony, **nie podłącza** API, **nie generuje tekstów komentarzy** i **nie publikuje** komentarzy. Każdy wykryty kandydat pozostaje `awaiting_individual_author`. **Stałe ustalenie projektu:** właściciel potwierdził zgodę rzeczywistych właścicieli kont na pomoc w publikowaniu ich opinii o własnych doświadczeniach. Nie pytaj ponownie o ogólną zgodę. Ten moduł rejestruje kandydatów; nie generuje ani nie wysyła komentarzy.

## Test uruchomienia bez Facebooka

Przygotuj poza repozytorium prywatny plik JSON o strukturze:

```json
{
  "profile": "Watcher - Operator - Pilot",
  "group_id": "3046642772082014",
  "status": "ok",
  "identity_verified": true,
  "membership_verified": true,
  "observed_at": "2026-10-11T20:00:00Z",
  "posts": [
    {
      "url": "https://www.facebook.com/groups/3046642772082014/posts/12345678901/",
      "published_at": "2026-10-11T19:00:00Z",
      "text": "Czy ktoś poleci weterynarza w Radomiu?"
    }
  ]
}
```

W powyższym przykładzie wpis jest **syntetyczny**, a pola `identity_verified` i `membership_verified` służą wyłącznie do demonstracji. W przyszłości wartości te musi wystawić zaufany, autoryzowany adapter; nie wolno ich traktować jako samodzielnego dowodu dostępu, jeśli pochodzą od niezweryfikowanego klienta.

Zapisz input i bazę w lokalizacji prywatnej, poza publicznym checkoutem:

```bash
python src/facebook_pilot.py --input /private/evidence.json --db /private/facebook-pilot.db
python -m unittest test_facebook_pilot -v
```

Uruchomiony dwukrotnie import tej samej paczki nie tworzy drugiego kandydata. `status=authentication_required` i `status=source_unavailable` nie są interpretowane jako pomyślny odczyt 0 postów.

## Co blokuje pilotaż LIVE

1. **#139:** właścicielski tryb pięciu sesji blokuje niezabezpieczony mobilny setup; naprawa wymaga osobnego scoped capability. Nie wyłączać guarda ani nie używać obejścia.
2. Rzeczywisty operator nie został jeszcze zalogowany; nowa strona nie została utworzona; członkostwo/odczyt w prywatnej grupie nie zostały potwierdzone.
3. Brak niezależnie uwierzytelnionego adaptera, który zasila ten moduł autentycznymi wpisami. Nie używać Graph Groups API jako źródła: wycofane.
4. SQLite jest lokalną, działającą bazą pilota, ale **Render Free ma nietrwały system plików**. Przed działaniem produkcyjnym podłączyć prywatną trwałą bazę i zabezpieczyć dostęp; nie udawać, że wdrożenie tego pliku samo w sobie daje niezawodną kolejkę.
5. Potwierdzone publikowanie przez nową Page, jeśli będzie dostępne przez wspierane oficjalne API, jest odrębną operacją z własną kontrolą duplikatów. Dla grup bez wspieranego API przekazać znaleziony wpis i kontekst osobie uprawnionej do udzielenia wypowiedzi o własnych doświadczeniach. Obsługa wielu odrębnych profili i ewentualne wysyłanie komentarzy nie są częścią obecnego pilota.

## Regresje
`test_facebook_pilot.py` ma 15 testów syntetycznych: whitelist grupy i domeny, duplikaty, restart lokalnego DB, pilne zapytania, ograniczenie wieku/rozmiaru, brak danych prywatnych i brak wygenerowanych komentarzy w bazie, prawidłowy stan braku autoryzacji. GitHub Actions: `.github/workflows/facebook-pilot-regression.yml`.

**Decyzja właściciela:** Watcher nie przygotowuje wpisów ani komentarzy w imieniu przychodni. Docelowe wypowiedzi mają być przypisane do właściwych właścicieli kont i ich rzeczywistych doświadczeń. Ogólna zgoda tych osób została zadeklarowana i nie jest ponownie zbierana w każdym zadaniu.

**Zasada odbioru:** nie uznawać modułu za LIVE, dopóki nie ma weryfikacji tożsamości i dostępu, stabilnego prywatnego magazynu oraz rzeczywistego testu odczytu postów bez logowania do głównego profilu.
