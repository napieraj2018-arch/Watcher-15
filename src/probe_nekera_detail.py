import re,requests
from urllib.parse import urljoin,urlsplit,parse_qsl,urlencode,urlunsplit
from bs4 import BeautifulSoup

BASE="https://www.nekera.pl/hotels/"
FAMILY=[("adults","2"),("child","2021-01-01"),("child","2019-01-01"),("product","F")]
ADULTS=[("adults","2"),("product","F")]
HEAD={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL"}

def compact(s): return " ".join((s or "").split())

def with_party(url,party):
    p=urlsplit(urljoin(BASE,url));q=parse_qsl(p.query,keep_blank_values=True)
    q=[(k,v) for k,v in q if k not in {"adults","child","product","pricetype"}]
    q+=party
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q,doseq=True),p.fragment))

def explicit_totals(text):
    pats=[
      r"(?:cena\s*(?:całkowita|razem|łączna|końcowa)|do\s*zapłaty|razem|za\s*wszystkich)\D{0,100}(\d[\d .]{2,})\s*zł",
      r"(\d[\d .]{2,})\s*zł\D{0,80}(?:razem|łącznie|za\s*wszystkich|do\s*zapłaty)",
    ]
    out=[]
    for pat in pats:
        for m in re.findall(pat,text,re.I):
            n=re.sub(r"\D","",m)
            if n:
                v=int(n)
                if v not in out:out.append(v)
    return out

def exact_family_state(url,text):
    q=parse_qsl(urlsplit(url).query,keep_blank_values=True)
    children=[v for k,v in q if k=="child"]
    return (("adults","2") in q and sorted(children)==["2019-01-01","2021-01-01"]) or (
        "2021-01-01" in text and "2019-01-01" in text
    )

def inspect(url,label):
    r=requests.get(url,headers=HEAD,timeout=35,allow_redirects=True)
    print("NEKERA_OFFER_FETCH",label,r.status_code,r.url,len(r.content))
    if r.status_code!=200:return None
    s=BeautifulSoup(r.text,"html.parser");text=compact(s.get_text(" ",strip=True))
    totals=explicit_totals(text)
    print("NEKERA_OFFER_EXACT_STATE",label,exact_family_state(r.url,text))
    print("NEKERA_OFFER_TOTALS",label,totals[:20])
    for needle in ["2 doros","2 dzieci","2021-01-01","2019-01-01","za wszystkich","razem","do zapłaty","dostępn","rezerw","all inclusive"]:
        i=text.lower().find(needle.lower())
        if i>=0:print("NEKERA_OFFER_SIGNAL",label,needle,text[max(0,i-260):i+900])
    for form in s.find_all("form"):
        html=compact(str(form))
        if any(k in html.lower() for k in ["rezerw","booking","adult","child","price","offer"]):
            print("NEKERA_OFFER_FORM",label,html[:9000])
    for a in s.find_all("a",href=True):
        blob=(compact(a.get_text(" ",strip=True))+" "+a.get("href","")).lower()
        if any(k in blob for k in ["rezerw","book","sprawdź cen","sprawdz cen","wybierz ofert"]):
            print("NEKERA_OFFER_ACTION",label,urljoin(r.url,a.get("href","")),compact(a.get_text(" ",strip=True))[:500])
    return {"url":r.url,"totals":totals,"text":text}

r=requests.get(BASE,params=FAMILY,headers=HEAD,timeout=35)
print("NEKERA_LIST_STATUS",r.status_code,r.url,len(r.content));r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
anchors=[]
for a in soup.find_all("a",href=True):
    txt=compact(a.get_text(" ",strip=True));u=urljoin(r.url,a.get("href", ""));p=urlsplit(u)
    if "szczegó" not in txt.lower():continue
    if p.netloc not in {"www.nekera.pl","nekera.pl"}:continue
    if not p.path.startswith("/offers/"):continue
    if u not in [x[0] for x in anchors]:anchors.append((u,txt))
print("NEKERA_REAL_OFFER_ANCHORS",len(anchors))
for i,(u,txt) in enumerate(anchors[:8]):print("NEKERA_REAL_OFFER",i,u,txt)

party_sensitive=0;compared=0;family_total_rows=0
for i,(native,txt) in enumerate(anchors[:6]):
    family_url=with_party(native,FAMILY);adult_url=with_party(native,ADULTS)
    fam=inspect(family_url,f"FAMILY-{i}")
    ad=inspect(adult_url,f"ADULTS-{i}")
    if not fam or not ad:continue
    if fam["totals"]:family_total_rows+=1
    if fam["totals"] and ad["totals"]:
        compared+=1
        different=fam["totals"]!=ad["totals"]
        party_sensitive+=int(different)
        print("NEKERA_OFFER_COMPARE",i,{"family":fam["totals"],"adults":ad["totals"],"different":different,"native":native})
print("NEKERA_OFFER_FAMILY_TOTAL_ROWS",family_total_rows)
print("NEKERA_OFFER_COMPARE_COUNT",compared)
print("NEKERA_OFFER_PARTY_SENSITIVE_COUNT",party_sensitive)
print("NEKERA_OFFER_FAMILY_TOTAL_VERIFIED",party_sensitive>0)
