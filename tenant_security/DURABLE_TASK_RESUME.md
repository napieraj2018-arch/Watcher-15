# Bezpieczne wznowienie pracy z innej rozmowy ChatGPT — kontrakt DB

Status 10.10.2026: **tylko odizolowany PostgreSQL 16 / PR DRAFT**, nie
wdrożony BFF ani nowe narzędzie produkcyjnego MCP. Dotyczy issue #125.

## Problem

Właściciel może dziś uruchomić 5 niezależnych przeglądarek przez MCP.
Jeśli rozmowa lub narzędzie utraci losowy uchwyt aib_..., nie wolno
odgadywać go z nazwy profilu ani wystawiać publicznego stop(profile).
Watchdog potrafi zakończyć sesję, ale nie wznowić utraconej pracy.

## Nowy protokół (migration 007)

1. BFF uwierzytelnia właściciela na podstawie istniejącej sesji HTTP
   i zweryfikowanego CSRF (nie w oparciu o podane klientem tenant_id).
   Rejestruje principal_id -> tenant_id + queued task_id.
2. Worker w tej samej bazie rezerwuje jeden z maksymalnie N slotów
   i BFF wiąże dokładne task/lease/generation/slot z właścicielem.
   Przed billable Steel create MUSI sprawdzić `can_create_provider`.
3. Po provider.start worker aktywuje slot i zadanie. Wyłącznie niezależny
   verifier może po rzeczywistym sprawdzeniu Steel odnotować, że
   dokładna sesja nadal istnieje i dotyczy właściwego profilu.
4. Nowy czat tego samego zalogowanego właściciela może pobrać
   `list_own_tasks`. Nie otrzyma tokenów ani ID sesji Steel.
   Dopiero po wskazaniu własnego task_id i świeżym provider readback
   wywołuje `reattach_own_task` z unikalnym attempt UUID.
5. SQL zwraca wyłącznie nowy monotoniczny `attachment_epoch` i
   `lease_generation`. BFF musi dodatkowo zweryfikować ACTIVE provider
   i wydać nowy podpisany, krótkotrwały per-task/per-owner bearer.
   `can_execute_epoch` MUSI być sprawdzane dla KAŻDEGO działania
   MCP oraz ścieżki mobilnej. Poprzednia epoka traci uprawnienia.
   Nie istnieje funkcja odczytania lub wykopania starego uchwytu.
6. `request_cancel_own` wymaga tego samego owner+CSRF i zapisuje
   trwałą intencję zakończenia (bez usuwania zdalnej sesji). Worker
   zatrzymuje ją, verifier potwierdza provider_closed + profile_saved,
   dopiero potem następuje zwolnienie slotu.
7. Niepotwierdzony provider, przeterminowany raport, przeterminowana
   dzierżawa, zły lease/epoch, unieważniona sesja lub inny tenant
   = odmowa zamiast nowego Steel create/release.
8. Funkcje `browser_bff_auth` widzą wyłącznie status i epoki własnego
   zadania. Nie mają SELECT do rejestru ani dostępu do funkcji verifier.
   Tenant worker nie może odczytać prywatnych rejestrów; tester
   sprawdza osobno prawa i próbę bezpośredniego wywołania.

W pamięci nie utrwalamy żadnych haseł, tokenów przeglądarki, cookies,
storage_state, źródłowych screenshotów ani provider sessionId. Wszelkie
provider IDs muszą być zaszyfrowane i przechowywane prywatnie
z powiązanym task+tenant AAD, nigdy w publicznym repo.

## Co jeszcze potrzebne, zanim prawdziwe czaty odzyskają pracę

- Zautoryzowany BFF z rzeczywistym loginem i CSRF, połączony z
  tenant DB; PR #102–#105 są na razie prototypami.
- Realna integracja worker MCP, która przed startem i każdym działaniem
  sprawdza bieżący slot+epoch; bez tego test SQL nie chroni live
  capability w lokalnej pamięci `MultiCapabilityGuard`.
- Private encrypted server-side reference do dokładnej sesji Steel,
  ponowne sprawdzenie sesji przez Steel przed podpisaniem nowego bearer,
  pełna rekonsyliacja po awarii procesu, połączenie z kosztami,
  idempotency, kwarantanną i retencją.
- Auth dla odrębnych użytkowników/tenantów, podpisana tożsamość
  rozmowy lub jawne upoważnienie do przekazania zadania innemu actor.
  **Ten protokół dopuszcza handoff między dwoma czatami tego samego
  principal po uwierzytelnieniu i wskazaniu task_id.** Nie twierdzimy,
  że samo połączenie ChatGPT dostarcza godne zaufania chat_id.
- Spójne cookies/localStorage po ponownym starcie (#111).

## Dowody

CI: `.github/workflows/durable-task-resume-ci.yml`: PostgreSQL 16,
dotychczasowe testy 3 i 5/10 slotów, 16 równoległych prób reattach
tego samego zadania, cross-tenant, inny principal w tym samym tenancie,
nieznana/wygaśnięta/wyłączona sesja, CSRF, zły lease i epoch,
nowy chat tego samego principal, operator cancel, odmowa wznowienia
po negatywnym provider receipt i po expiry/quarantine. Test nie
wywołuje prawdziwego Steel. Nie obiecywać trwałego restore loginów.
**Status komercyjny: NO-GO.**
