# Watcher-15

Stały system monitoringu uruchamiany przez GitHub Actions co 15 minut.

## Aktywny watcher

**Wakacje last minute 2+2**

- 2 dorosłych + dzieci w wieku 5 i 7 lat
- maks. 7000 zł łącznie
- All Inclusive
- wyjazd w ciągu 1–3 dni
- około 6–8 nocy
- Warszawa-Radom ma pierwszeństwo, potem Warszawa
- hotel minimum 8.0/10 i co najmniej 50 opinii
- przed alarmem wykonywana jest druga kontrola ceny i konfiguracji rodziny

## Alarmy

Po znalezieniu zweryfikowanej oferty system tworzy GitHub Issue i oznacza konto właściciela repozytorium. Powtórny alert dla tej samej oferty pojawia się dopiero przy istotnym spadku ceny.

## Dodawanie kolejnych watcherów

Reguły są przechowywane w `config/watchers.json`. Dzięki temu ten sam mechanizm może później monitorować inne wyszukiwania i limity bez budowania systemu od początku.
