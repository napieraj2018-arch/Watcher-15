# AI Browser — wyłączność sesji (kandydat, NIE PRODUKCJA)

To osobna gałąź robocza. Profil Facebook Macieja i działający kontroler Render 0.5.2 pozostają bez zmian.

Problem 08.10.2026: jedna rozmowa rozpoczęła sesję w trybie odczytu, a inny klient zmienił tę samą sesję na tryb zapisu i nawigował po grupach. Samo sprawdzenie listy sesji przed poleceniem nie zapobiega wyścigowi.

Niezależny koordynator session_ownership.py w przygotowanej paczce stosuje pojedynczą aktywną sesję, losowy token właściciela, kontrolę sesji/profilu/trybu/domeny, szeregowanie poleceń odczytu i odmowę zwolnienia po niepewnym zapisie. Testy nie dotykają prawdziwych profili, cookies ani haseł.

UWAGA: To jeszcze nie zabezpiecza aktywnego serwera. Wszystkie starsze narzędzia MCP i mobilne trasy muszą przechodzić przez wspólną kontrolę własności, albo zostać zablokowane, kiedy działa dzierżawa. W przeciwnym razie obejście pozostaje możliwe. Wymagany jest test dwóch niezależnych klientów po integracji.

Baza Floot ma przygotowane funkcje dzierżaw, ale brak połączonego endpointu i kontrolera. Dzienny limit budowania Floot został wyczerpany. Nie obchodzimy odmów narzędzi i nie wdrażamy nieprzetestowanego kodu na żywo.

Źródła i 34 syntetyczne testy są w pobieralnym załączniku rozmowy AI-Browser-izolacja-sesji-testy-2026-10-08.zip. Załącznik nie jest tym samym co ukończone wdrożenie.
