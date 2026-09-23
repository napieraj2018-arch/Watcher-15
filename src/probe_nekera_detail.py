import re
from urllib.parse import urljoin,urlsplit,urlunsplit,parse_qsl,urlencode
import requests
from bs4 import BeautifulSoup

SEARCH="https://www.nekera.pl/hotels/?adults=2&child=2021-01-01&child=2019-01-01&product=F"
HEAD={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL"}

r=requests.get(SEARCH,headers=HEAD,timeout=30);r.raise_for_status()
s=BeautifulSoup(r.text,"html.parser")
print("NEKERA_DETAIL_SEARCH",r.status_code,r.url,len(r.content))
links=[]
for a in s.find_all("a",href=True):
    txt=" ".join(a.get_text(" ",strip=True).split())
    href=urljoin(r.url,a["href"])
    if "Szczegóły" in txt or "/hotel" in href.lower() or "/offer" in href.lower():
        if href not in links:links.append(href)
print("NEKERA_DETAIL_LINK_COUNT",len(links))
for raw in links[:12]:
    p=urlsplit(raw); q=parse_qsl(p.query,keep_blank_values=True)
    # Preserve the offer's own identifiers, but force the exact party on detail.
    q=[(k,v) for k,v in q if k not in ("adults","child")]
    q += [("adults","2"),("child","2021-01-01"),("child","2019-01-01")]
    exact=urlunsplit((p.scheme,p.netloc,p.path,urlencode(q,doseq=True),p.fragment))
    try:
        d=requests.get(exact,headers=HEAD,timeout=30)
        text=" ".join(BeautifulSoup(d.text,"html.parser").get_text(" ",strip=True).split())
        print("NEKERA_DETAIL_URL",d.status_code,d.url,len(d.content))
        print("NEKERA_DETAIL_EXACT_PARTY",("adults=2" in d.url and d.url.count("child=")>=2))
        sig=[]
        for pat in [
            r".{0,140}(?:2 doros|2 dzieci|01\.01\.2021|01\.01\.2019).{0,260}",
            r".{0,140}(?:cena całkowita|cena razem|razem|do zapłaty).{0,260}",
            r".{0,140}\b[0-9][0-9 ]{2,8}\s*zł.{0,220}",
            r".{0,140}(?:dostępn|rezerwuj|rezerwacja).{0,260}",
        ]:
            for m in re.finditer(pat,text,re.I):
                x=" ".join(m.group(0).split())
                if x not in sig:sig.append(x)
                if len(sig)>=18:break
        for x in sig:print("NEKERA_DETAIL_SIGNAL",x[:900])
        if sig: break
    except Exception as e:
        print("NEKERA_DETAIL_ERR",type(e).__name__,str(e)[:180])
