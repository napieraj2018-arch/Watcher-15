# Trwałe blokady Steel (kandydat, NIE w produkcji)

Data: 09.10.2026. Ten moduł obsługuje wyłącznie **fikcyjną bazę PostgreSQL 16**
w GitHub Actions. Nie łączy się z aktualną bazą Floot, żadnym profilem, MCP
ani dostawcą Steel. Nie migracji danych i nie ma wywołań dostawcy.

## Po co?

Dzisiejsze `browser_lease_claim` w starym prototypie Floot potrafi ponownie
przydzielić slot po `expires_at`. To jest ryzykowne: upływ czasu NIE oznacza,
że zdalna sesja Steel została zamknięta lub profil poprawnie zapisany.
Stan jednej instancji w RAM także zanika po restarcie kontrolera.

Nowy prototyp chroni jeden fizyczny slot `steel-main`:
- serializuje 16 niezależnych połączeń; dokładnie jeden zwycięzca może
  rozpocząć `POST /sessions`, a idempotentne powtórzenie NIE zaczyna sesji;
- przechowuje generację fencing `generation` wraz z tenantem, zadaniem i
  niezgadywalnym `lease_id`;
- odrzuca cudze, stare i wygasłe dzierżawy;
- po wygaszeniu przekłada slot do **kwarantanny, a nie do wolnych**;
- końcowe zwolnienie wymaga dwóch pozytywnych przesłanek, zapisanych przez
  odrębną rolę `aib_slot_verifier`: provider naprawdę zamknięty i profil
  zapisany; sama rola worker nie potrafi ich wytworzyć;
- nie przechowuje ani nie pokazuje tokenu Steel, cookies, ID natywnego profilu
  ani treści sesji.

## Granice: czego TEN KOD NIE robi

- Brak rzeczywistego BFF z loginem/rolami: `tenant_id` jest parametrem
  funkcji. BFF MUSI zweryfikować sesję użytkownika i sam go ustalić.
  Bez tego SQL nie jest izolacją tenantów.
- Rola `aib_slot_verifier` wymaga rzeczywistej niezależnej integracji z
  Steel i sejfem. Dzisiaj CI **symuluje** dowody. Nie podłączać formularza
  użytkownika, który sam wpisuje `provider_closed=true`.
- Gdy zewnętrzny dostawca nie odpowiada, NIE istnieje bezpieczne automatyczne
  odblokowanie. Kwarantannę może zwolnić jedynie potwierdzona odrębnym kanałem
  procedura; wdrożenie tej procedury jest nadal P0.
- Jeden globalny slot jest rozwiązaniem próbnym, a nie poziomym skalowaniem.
  Limity płatności, per-tenant quotas, egress SSRF, izolacja storage i GDPR
  wymagają osobnych prac.

## Odbiór

CI: `.github/workflows/durable-lease-slot.yml`.
PostgreSQL `trust` występuje **wyłącznie na tymczasowym runnerze**.
Żadne live tokeny ani prawdziwe profile nie biorą udziału.

Nie scalać z produkcyjnym uruchamianiem bez projektu BFF, silnego
uwierzytelniania, osobnych ról Postgres (bez roli superuser w połączeniach
klientów), skoordynowanej migracji i testu awarii dwóch procesów.
