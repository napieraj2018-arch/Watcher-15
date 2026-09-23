# Monitoring channels

Watcher-15 contains 15 isolated source channels.

## Production

1. Wakacje.pl
2. TUI Poland
3. ITAKA
4. Rainbow
5. EXIM tours
6. Travelplanet
7. Grecos
8. Sun & Fun

Production adapters are fail-closed. An alert requires exact 2 adults + children aged 5 and 7, live availability, a verified final family total, and all active trip/quality filters. Per-person prices and two-adult totals are never accepted as family totals. Each production source has an independent workflow; offer monitoring is staggered on a 15-minute cadence.

## Diagnostic

9. Fly.pl — request can carry children, but rendered offer state currently falls back to 2+0; family total is not trusted.
10. Nekera — exact 2+2 serialization is known; listing totals and the first detail controls still price like 2 adults. Detail passenger repricing is under test.
11. Oasis Tours — participant picker can set 2 children; exact DOB serialization and BlueVendo family-price payload are under test.

## Blocked / alternate route required

12. Coral Travel — headless browser surface does not expose a usable booking flow.
13. Join UP! Polska — Cloudflare challenge.
14. eSky Wakacje — access denied in the current automation environment.
15. TraveliGo — Cloudflare challenge.

A blocked or diagnostic channel cannot create offer alerts.
