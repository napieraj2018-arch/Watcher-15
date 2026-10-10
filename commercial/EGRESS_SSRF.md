# AI Browser — kontrola wyjść sieciowych (SSRF), etap testowy

**Stan: biblioteka polityki i testy, NIE WDROŻONO do prawdziwej przeglądarki.**

Przed sprzedażą agenta przeglądającego internet trzeba zabezpieczyć nie tylko adres wpisany w pasku, lecz również przekierowania, DNS, właściwe połączenie TCP/TLS, zasoby ładowane przez stronę oraz subrequesty. Sama walidacja URL po stronie ChatGPT lub backendu nie blokuje requestów wykonywanych przez Steel/Chromium.

## Co zostało przygotowane

Moduł egress_policy.py określa, które **dokładne domeny HTTPS** może odwiedzać dany tenant. Wstrzykiwany resolver DNS jest walidowany fail-closed: pojedynczy prywatny adres w zestawie powoduje odmowę. Adresy IP link-local, loopback, prywatne, multicast i metadane chmury są blokowane.

Moduł wydaje krótkotrwałe uprawnienie do **przypiętego zestawu publicznych adresów IP**, powiązane z tenant_id, nazwą hosta i certyfikatem HTTPS. Przekierowania między hostami wymagają osobnej zgody i nowej kontroli DNS, nawet jeśli oba hosty należą do allowlisty. Wynik nie zawiera ścieżki ani query URL, tokenów i sekretów.

### Ważny warunek bezpieczeństwa

**To nie jest jeszcze egzekwowanie bezpieczeństwa sieciowego.** Aby realnie chronić przed SSRF i DNS rebinding, transport musi połączyć się wyłącznie z IP z permit, zweryfikować rzeczywisty peer_address, certyfikat HTTPS i SNI, a politykę zastosować do każdej nawigacji, redirectu, fetch, websocketu, załączników i subresource. Jeżeli zdalny dostawca przeglądarki nie umożliwia tego w sposób udokumentowany, konieczny będzie restrykcyjny egress proxy/firewall albo inny provider.

Nie podłączać naiwnie do publicznego nawigowania dowolnych stron: lista dokładnych hostów jest użyteczna dla zadań o znanym zakresie, ale ogólna przeglądarka wymaga kontrolowanego modelu uprawnień i egress dostawcy.

### Testy

Wszystkie testy używają fikcyjnego resolvera bez DNS, HTTP, cookies ani poświadczeń. Sprawdzają: odmowę public+private DNS, IP metadanych 169.254.169.254, IPv4/IPv6, TLS mismatch, cross tenant, wygaśnięcia, złośliwych URL, pustego username, przekierowań i brak sekretów w logach.

    python -m unittest discover -s commercial/tests -p 'test_egress_policy.py' -v

**Nie scalać w celu oznaczania blokera SSRF jako zamkniętego.** Dopiero po integracji na poziomie prawdziwego zdalnego egress i teście penetracyjnym można zmienić stan tego warunku.

## Punkty odniesienia

- OWASP SSRF Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
- OWASP API Security Top 10 API7: https://owasp.org/API-Security/editions/2023/en/0xa7-server-side-request-forgery/
- Steel dokumentacja sesji: https://docs.steel.dev/overview/sessions-api/configuration
