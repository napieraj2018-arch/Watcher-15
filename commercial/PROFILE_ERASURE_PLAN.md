# AI Browser — pełne usuwanie profilu klienta (prototyp procedury)

**Status: tylko testy offline. Nie podłączono do obecnej usługi Render/Floot/Steel.** Ten moduł nie usuwa żadnego z 10 istniejących profili właściciela.

## Dlaczego to krytyczne przed sprzedażą

Zapisywanie profilu trwałego po stronie Steel, szyfrowanej kopii u nas i kolejnych wersji kopii oznacza wiele niezależnych lokalizacji danych pozwalających odtworzyć zalogowanie. Usunięcie tylko wpisu w naszej bazie **nie usuwa natywnego profilu u dostawcy ani archiwalnych wersji**.

Sprawdzono repozytorium oficjalnego SDK Steel Python: `steel.resources.profiles` udostępnia create, update, list, get, lecz nie ma udokumentowanej metody delete w tej wersji. Link: https://github.com/steel-dev/steel-python/blob/main/src/steel/resources/profiles.py . Steel może posiadać inne, nowsze lub komercyjne API, którego nie zweryfikowaliśmy; przed produkcją trzeba **formalnie ustalić i sprawdzić** metodę usuwania oraz retencję u dostawcy. Nie zgadujemy endpointu `DELETE` i nie wykonujemy prób na rzeczywistych profilach.

Oficjalna dokumentacja profilów potwierdza, że przechowują pełną zawartość userDataDir (cookies, hasła, ustawienia) oraz że nieużywane profile podlegają automatycznemu usunięciu po 30 dniach. To nie jest mechanizm obsługi żądań natychmiastowego usunięcia zgodnie z RODO: https://docs.steel.dev/overview/profiles-api/overview

## Zaprojektowany przebieg

1. Użytkownik musi być uwierzytelniony i potwierdzić tę konkretną destrukcyjną operację drugim poziomem weryfikacji. Nie akceptujemy wyłącznie nazwy profilu z interfejsu.
2. Wszystkie nowe sesje i zadania dla profilu zostają zablokowane **atomowym, trwałym znacznikiem erasure/tombstone**.
3. Potwierdzamy, że żadna sesja nie jest aktywna. **Nie zatrzymujemy cudzej sesji automatycznie**.
4. Ustalamy oryginalny, niezmienny identyfikator profilu u dostawcy z mapowania wewnętrznego — bez możliwości podmiany przez klienta.
5. Wywołujemy potwierdzony przez dostawcę proces usunięcia. **Odpowiedź 200/202 to za mało**: wymagany jest odczyt potwierdzający nieistnienie profilu lub udokumentowane zakończenie asynchroniczne.
6. Dopiero po wiarygodnym potwierdzeniu usunięcia u dostawcy usuwamy, w określonej kolejności: dane dostępu w sejfie, zaszyfrowany snapshot, wszystkie wersje historyczne, pliki robocze, nagrania i mapowania profilu.
7. Po każdej operacji wykonujemy test odczytu, potwierdzający brak danych we właściwym tenant_id. Brak widoczności nie jest stanem „zero”.
8. Potwierdzony znacznik końcowy przechowuje minimalną datę/rodzaj zgody, wersję procesu i potwierdzenie wykonania, **bez cookies, hasła, wartości storage i referencji dostawcy w publicznej odpowiedzi**.

## Zachowanie przy awarii

- Brak weryfikacji tożsamości, MFA lub aktywna sesja → nie zaczynaj usuwania.
- Brak potwierdzonego provider delete API → zwróć `PROVIDER_ERASURE_UNSUPPORTED`, pozostaw profil zablokowany, bez fałszywego certyfikatu.
- Provider zwraca błąd, niepewną odpowiedź albo nadal widzi profil → wstrzymaj lokalne czyszczenie (może być to jedyne mapowanie do danych dostawcy).
- Snapshot, sejf lub kopie nie potwierdzają usunięcia → status `paused`, a nie `complete`.
- Po niepewnej operacji nie przywracaj dostępu i nie uruchamiaj automatycznej serii powtórzeń.
- Przy wznowieniu zweryfikuj aktualny stan wszystkich repozytoriów, pomijając już sprawdzone, nieistniejące dane.

## 09.10.2026 — zabezpieczenie przed fałszywym potwierdzeniem usunięcia

Wykryto niebezpieczną lukę w **procedurze testowej**: wcześniej pojedynczy odczyt `final_tombstone_verified=True` mógł zakończyć powtórne żądanie statusem `completed`, nawet gdy zdalny profil lub kopia pojawiły się ponownie. Flaga `confirmed_step_up=True` przekazana przez wywołującego także nie jest wystarczającym dowodem świeżego potwierdzenia użytkownika.

Od teraz koordynator dodatkowo wymaga:
- `verify_fresh_step_up(principal, profile_id) is True` od zaufanego, uwierzytelnionego backendu przed uruchomieniem jakiejkolwiek operacji destrukcyjnej. Backend ma zweryfikować świeżość, jednorazowość oraz związanie potwierdzenia z dokładnym użytkownikiem, tenantem i profilem. Nie wolno brać tej wartości z pola formularza klienta.
- `erasure_receipts_verified(tenant, profile_id) is True` **za każdym razem**, także przy odczycie istniejącego tombstone. Ten odczyt ma niezależnie sprawdzać trwałe potwierdzenie usunięcia natywnego profilu Steel oraz **wszystkich** zaszyfrowanych kopii, archiwów, plików i nagrań. Poświadczenia/receipts powinny być audytowalne i przechowywane w odseparowanym, ograniczonym retencją dzienniku, bez danych logowania.
- W przypadku braku dowodów lub niepewności koordynator zwraca `paused`, a nie „usunięto”. Nie uruchamia ponownie kasowania Steel w pętli.

Na gałęzi `erasure-verified-receipts-20261009` przeprowadzono **71 testów syntetycznych**, w tym 13 negatywnych scenariuszy: obce potwierdzenie MFA, brak niezależnego dowodu, przywrócony natywny profil, ponownie dostępna kopia, zawieszone lub błędne API. [GitHub Actions PASS](https://github.com/napieraj2018-arch/Watcher-15/actions/runs/37962639911).

**Istotne ograniczenie:** nowe metody backendu są wyłącznie protokołem. Bez rzeczywistego API usuwania u dostawcy Steel, audytowanego magazynu dowodów, sesji klienta i trwałych dzierżaw nadal NIE wolno uznać funkcji za dostępną produkcyjnie ani oznaczać warunku `profile_deletion` jako zaliczonego.

## Warunki integracji, których brakuje

- **Backend z tenant auth + step-up** oraz bazą trwałych, transakcyjnych dzierżaw i wstrzymań.
- Faktyczna, oficjalnie wspierana metoda usuwania natywnego profilu Steel + test nieistnienia po usunięciu.
- Produkcyjny dziennik postępu i idempotentny job, odporny na restart Rendera oraz kilku workerów. Obecny `asyncio.Lock` działa tylko w jednym procesie.
- Bezpieczne API do usuwania danych i wersji w Floot z pełnym testem autoryzacji + propagacja do plików/nagrań.
- Zgodny z regulaminem proces dokumentowania usunięcia danych oraz polityka retencji wynikająca z RODO i umów.
- Odporność na przypadkowe przywrócenie usuniętego profilu z historycznego backupu.
- Niezależny test usunięcia *wyłącznie sztucznego profilu* od początku do końca, a dopiero później pilot bez prawdziwych użytkowników.

## Testy

Uruchom:

    python -m unittest commercial.tests.test_profile_erasure -v

GitHub Actions: `.github/workflows/commercial-release-gate.yml`. Wszystkie testy używają fikcyjnych UUID i sztucznych odpowiedzi adaptera; nie wykonują jakichkolwiek żądań sieciowych.

**Ten moduł nie usuwa faktycznie danych. Nie oznaczać commercial release gate jako ukończonego na podstawie samych testów koordynatora.**
