import requests

URL = "https://fly.pl/szukaj-wycieczek/"
r = requests.get(URL, headers={"User-Agent":"Mozilla/5.0","Accept-Language":"pl-PL"}, timeout=30)
print("STATUS", r.status_code, len(r.content))
text = r.text
for needle in ["filter[person]", "Dorośli", "Dzieci"]:
    start = 0
    for n in range(8):
        i = text.lower().find(needle.lower(), start)
        if i < 0:
            break
        snippet = " ".join(text[max(0,i-1000):i+3000].split())
        print("FLY_PARTY_SNIP", needle, n, snippet[:5000])
        start = i + len(needle)
