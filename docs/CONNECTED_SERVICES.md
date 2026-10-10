# Połączenia API zamiast ponownego logowania

Zasada: przy poleceniu publikowania Reels, posta, odczytu poczty,
WordPress lub opinii Google najpierw sprawdź dostępne, już podłączone
aplikacje ChatGPT. Wykonuj w nich autoryzowaną czynność BEZ uruchamiania
Steel, jeśli narzędzie obsługuje dokładnie żądany format i konto.

Stan kontroli 10.10.2026 (sprawdzać na żywo):
- Gmail: osobna aplikacja ChatGPT już działa. OAuth wyklucza potrzebę
  przechowywania hasła Gmaila w AI Browser. Użyj Gmail do odczytu,
  szkiców lub wysyłania, zależnie od zgody i zakresu narzędzi.
- Windsor.ai: konto Instagram @architekt.radom i Facebook Page Anity.
  Instagram action create_video_post publikuje Reels (wymaga podanego,
  dostępnego dla platformy URL MP4/MOV 3 s–15 min; można dołączyć
  cover_url JPEG albo thumb_offset). Nie zgaduj gotowego filmu;
  publikacja z podanym materiałem wymaga właściwej marki.
  Windsor facebook_organic ma posty i zdjęcia; obsługę Reels
  Facebook należy osobno zweryfikować, nie utożsamiać z Instagram API.
- WPVibe: WordPress https://architekt.radom.pl/poradnik i
  https://weterynarz.radom.pl mają potwierdzony odczyt, ale zapis,
  upload i publikację sprawdza się osobno na właściwej witrynie.
- Google Business: recenzje właściwej wizytówki Anity są dostępne
  przez Windsor google_my_business; archiwalne Stories/Highlights IG
  nie były zwrócone przez API i wymagają autoryzowanego odczytu
  wizualnego, którego nie należy udawać.
- Metricool: dotychczasowa kolejka Anity nie może być modyfikowana
  przez samą diagnostykę. Nie dotykaj profili weterynaryjnych.

Jeżeli aplikacja ChatGPT nie obsługuje danego kroku lub nie ma
prawidłowego uprawnienia, dopiero wtedy AI Browser z właściwym
trwałym profilem; odczytaj bieżący stan autoryzacji. Nazwa profilu
ani zapisany cookie nie są dowodem zalogowania. Nie próbuj
automatycznie omijać reCAPTCHA/2FA; zleć tylko potrzebną
weryfikację użytkownikowi i wróć do ostatniego bezpiecznego kroku.
Nie przenoś tokenów z połączonych aplikacji ChatGPT do publicznego
repozytorium, Render environment ani logów.

Zapisywanie haseł: preferowane są OAuth + szyfrowany vault z wąskim
uprawnieniem i pochodzeniem z bezpiecznego formularza, NIE hasła
wpisywane w czat ani w publiczny GitHub. Hasło master odzyskiwania
w razie wyzwania użytkownik przechowuje we własnym menedżerze haseł.


## Operacyjny wybór połączenia z poziomu AI Browser MCP

Narzędzie `aib_route_operation(service, operation, brand)` jest bezpiecznym
katalogiem opcji, np.:

- Instagram Reel Anity: `instagram`, `reel`, `anita` →
  ChatGPT Windsor.ai `instagram/create_video_post`; wymaga konkretnego
  dostępnego URL wideo i odczytu bieżących uprawnień / ID konta.
- Facebook post Anity: `facebook`, `post`, `anita` →
  Windsor `facebook_organic/create_post`; wpis na Facebooku nie oznacza,
  że opublikowano również Reel w Instagramie.
- Gmail: `gmail`, `email_read`, bez marki →
  podłączona aplikacja `Gmail/search_emails`, bez hasła browsera.
- WordPress: `wordpress`, `wordpress_publish`, `anita` →
  WPVibe `discover_abilities` i dopiero po weryfikacji właściwej
  witryny dostępna funkcja zapisu lub publikacji.
- GBP recenzje Anity: `google_business`, `business_reviews`, `anita` →
  Windsor `google_my_business/get_data` dla właściwego location.
- Archiwalne Highlights lub funkcja bez oficjalnego API →
  właściwy zapisany profil Steel dopiero po bieżącym potwierdzeniu
  tożsamości zalogowanego konta.

**Ważna różnica:** to katalog tras, NIE most do sekretów ani samodzielna
integracja OAuth. Funkcja zawsze zwraca `connector_connected=not_checked`
i `account_authenticated=not_checked`. Agent musi sprawdzić konkretne
połączenie bezpośrednim narzędziem aplikacji ChatGPT, potwierdzić identyfikator
konta i dostępność wymaganej operacji. Publikacja wymaga wskazanego
materiału i odpowiedniego upoważnienia. Nie wolno na podstawie katalogu
ogłaszać, że Reel się opublikował, ani zastępować Reels zdjęciem.

Sama poprawa routingu nie naprawia #111 — Steel może odtworzyć
niespójne cookies/localStorage. Wykonywanie CAPTCHA lub MFA bez udziału
użytkownika nie jest mechanizmem trwałej autoryzacji; pojawienie się
wyzwania zatrzymuje krok, ale nie całe pozostałe zadania z innych
kont/profili. Nie wpisywać rodzinnego hasła ani kodów w ChatGPT.
