# AI Browser — bramka przed sprzedażą (stan 09.10.2026)

**Wynik bieżący: NO-GO.** Projekt może służyć do dalszych, prywatnych testów właściciela, ale nie powinien jeszcze obsługiwać niezależnych płacących klientów.

To nie jest deklaracja, że system jest niebezpieczny; oznacza, że nie ma wystarczających dowodów na spełnienie wymagań sprzedaży usługi, której powierzamy zalogowane konta.

## Zrealizowana kontrola

Program \`release_gate.py\` waliduje 20 punktów bezpieczeństwa, prywatności, niezawodności, obsługi płatności i dostępności. Każdy ma status i miejsce na aktualne dowody. Nie pozwala przypadkowo uznać nieznanego punktu za zaliczony i nie przyjmuje nieaktualnych deklaracji. **Zielony test programu nie oznacza zgody na sprzedaż.** Raport nigdy nie ogłasza automatycznie formalnego zatwierdzenia.

Uruchomienie lokalne:
\`python commercial/release_gate.py commercial/release_evidence.json\`

Kod wyjścia 1 oznacza poprawny manifest z blokadami, 2 błędny manifest, 0 kompletny manifest do N I E Z A L E Ż N E G O odbioru. Do formalnej akceptacji potrzebne są jeszcze testy penetracyjne i weryfikacja prawna.

## Zaobserwowany stan prywatnego prototypu

- Render: działająca pojedyncza instancja, weryfikowane deploye z osobną gałęzią i testami.
- Floot: opublikowana aplikacja w planie bezpłatnym, aktualnie z widocznością publiczną. Sama dostępność frontendu nie jest równoznaczna z nieautoryzowanym dostępem do API: autoryzacja endpointów wymaga oddzielnego testu. **Nie wdrażać przy sprzedaży publicznego interfejsu administratora.**
- Zapisane profile: dane w chmurze, lecz nadal globalny katalog nazw; brak izolacji płacących klientów.
- Działa dostęp do wybranych kont właściciela, ale test znacznika cookie/localStorage dla profilu technicznego wykazał niezgodność po ponownym otwarciu.
- Nowa kontrola właściciela sesji jest w trybie diagnostycznym, nie w egzekwowaniu.
- Serwer ma limit jednej sesji; brak trwałej kolejki i izolacji limitów dla wielu klientów.
- Poprawki UX powstają w osobnej gałęzi, nie są obecnym panelem produkcyjnym.
- Nie ma jeszcze zakończonego mechanizmu usunięcia wszystkich kopii i natywnych profili u dostawcy.
- Steel opisuje limit 300 MB profilu oraz usunięcie nieużywanych profili po 30 dniach. W komercyjnej usłudze nie można zakładać bezterminowej trwałości dostawcy.

## Priorytety produktu

**P0 — przed pierwszym płatnym klientem.** Autoryzacja własnego użytkownika, tenant_id w każdej trasie i profilu, izolacja na poziomie bazowych reguł RLS i Steel namespaces, niezawodne blokady sesji, bezpieczna obsługa MFA, sekretów, danych i logów, pełne usuwanie profili oraz spójne odtwarzanie.

**P1 — przed regularną sprzedażą.** Kolejka i limity kosztów, płatne zasoby serwera, 24/7 monitoring i alerty, raportowanie incydentów, rachunki/faktury i webhooki płatności, kopie i ćwiczenia odtworzenia, testy obciążenia i regresje mobilne.

**P2 — wyróżniki produktu.** Zwykłe okno zamiast zarządzania sesją, widok „agent pracuje”, karty i zakładki, zapisywanie zadań, historia działań, wznawianie, podgląd ręczny tylko podczas MFA, wersja desktop i iPhone, import profili z innych przeglądarek (tylko za zgodą).

## Konkurencja i kierunek UI

| Rozwiązanie | Pomysł, który warto przenieść (bez kopiowania interfejsu) |
|---|---|
| Safari iPhone | Dolny pasek adresu, prosty przełącznik kart, standardowe przyciski. |
| Arc Search | Szybki start, łatwy dostęp kciukiem i minimum niewykorzystanych kontrolek. |
| Browserbase | Widok pracy agenta i kontrolowane przejęcie przez człowieka oraz nagrania diagnostyczne. |
| Steel | Rozdzielenie trwałego profilu od chwilowego procesu sesji; gotowe interaktywne podglądy i profile. |

W nowym projekcie mobile polecam schować wszystkie pojęcia: „MCP”, „CDP”, „sesja Live”, „Steel”, „Render”. Użytkownik wybiera przestrzeń i kartę, a orkiestrator sam sprawdza/uruchamia backend. Gdy instancja zajęta, wyświetla „Inne zadanie jest w toku” wraz z kolejką zamiast błędu technicznego. Przycisk przejęcia kontroli powinien być widoczny **tylko gdy faktycznie potrzebna jest interwencja**, nie jako obowiązkowy krok.

Zgodnie z Apple HIG podstawowym minimalnym obszarem dotykowym jest około 44 × 44 pt. Nie należy kopiować układu 1:1 z Arc, Safari ani innymi produktami.

## Metryki odbioru (cele, nie osiągnięte wyniki)

- 100% odmów próby dostępu do zasobu obcego tenant_id w testach izolacji.
- 100% odmów równoległej nieautoryzowanej modyfikacji sesji w testach wielu klientów.
- 0 sekretów lub cookies w standardowych logach, nagraniach i błędach.
- Co najmniej 99.5% poprawnie wznowionych, uprzednio zalogowanych profili w kontrolowanym 30-dniowym teście.
- Powtarzalne usuwanie danych ze wszystkich kopii i dostawców.
- Uptime docelowo >= 99.9% na płatnym hostingu, z opisanym RTO/RPO.
- Test mobilny na 320, 390 i 430 px oraz na desktopie, z rzeczywistym potwierdzeniem obsługi gestów i klawiatury.

## Dalsze pliki

- \`release_gate.py\`: narzędzie no-go.
- \`release_evidence.json\`: aktualne blokady bez danych wrażliwych.
- \`THREAT_MODEL.md\`: model zagrożeń i plan separacji klientów.
- \`tests/\`: testy jednostkowe i testy negatywnych przypadków.

## Referencje

- Steel: https://docs.steel.dev/overview/profiles-api/overview
- Steel sesje: https://docs.steel.dev/overview/sessions-api/configuration
- Browserbase: https://www.browserbase.com/blog/what-is-a-browserbase-browser
- Safari na iPhone: https://support.apple.com/en-euro/guide/iphone/ipha9ffea1a3/ios
- Apple przyciski: https://developer.apple.com/design/human-interface-guidelines/buttons
- W3C WCAG: https://www.w3.org/WAI/WCAG21/Understanding/target-size
- RODO: https://eur-lex.europa.eu/eli/reg/2016/679/oj

Użytkownik udzielił zgody na rozwój narzędzia; nie stanowi to dowodu spełnienia wymagań danych osób trzecich, dokumentacji handlowej lub audytu bezpieczeństwa.
