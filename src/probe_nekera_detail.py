import re,requests,json
from urllib.parse import urljoin,urlsplit,parse_qsl,urlencode,urlunsplit
from bs4 import BeautifulSoup

BASE="https://www.nekera.pl/hotels/"
PARTY=[("adults","2"),("child","2021-01-01"),("child","2019-01-01"),("product","F")]
HEAD={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL"}

def compact(s): return " ".join((s or "").split())

def exactify(url):
    p=urlsplit(urljoin(BASE,url)); q=parse_qsl(p.query,keep_blank_values=True)
    # Preserve native offer params; replace party keys with exact party.
    q=[(k,v) for k,v in q if k not in {"adults","child","product"}]
    q+=PARTY
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q,doseq=True),p.fragment))

def signals(text,label):
    pats=[
      r"(?:cena\s*(?:całkowita|razem|łączna|końcowa)|do\s*zapłaty|razem)[^\n<]{0,100}\d[\d .]{2,}\s*zł",
      r"\d[\d .]{2,}\s*zł[^\n<]{0,80}(?:razem|łącznie|za\s*wszystkich)",
      r"2\s*doros",r"2\s*dzie",r"2021-01-01",r"2019-01-01",
      r"dostępn",r"rezerw",r"all\s*inclusive"
    ]
    low=text.lower()
    for pat in pats:
      for m in list(re.finditer(pat,text,re.I))[:12]:
        s=compact(text[max(0,m.start()-260):min(len(text),m.end()+500)])
        print("NEKERA_DETAIL_SIGNAL",label,pat,s[:1400])

r=requests.get(BASE,params=PARTY,headers=HEAD,timeout=35)
print("NEKERA_LIST_STATUS",r.status_code,r.url,len(r.content))
r.raise_for_status(); soup=BeautifulSoup(r.text,"html.parser")
candidates=[]
for a in soup.find_all("a",href=True):
    href=a.get("href",""); txt=compact(a.get_text(" ",strip=True))
    parent=a
    block=""
    for _ in range(6):
        parent=parent.parent if parent else None
        if not parent:break
        block=compact(parent.get_text(" ",strip=True))
        if "zł" in block and ("/os" in block.lower() or "szczeg" in block.lower()):
            break
    blob=(txt+" "+href+" "+block).lower()
    if ("szczeg" in blob or "/hotel" in href or "/offer" in href or "rezerw" in href) and "zł" in block:
        rec=(exactify(href),txt,block[:2200])
        if rec not in candidates:candidates.append(rec)
# Inspect the offer CTA itself before following links. Nekera currently
# uses the same /offers/ route for many cards, so the per-offer identifier may
# live in data-* attributes, a surrounding form, or hidden inputs.
detail_anchors=[]
for a in soup.find_all("a",href=True):
    txt=compact(a.get_text(" ",strip=True))
    if "szczegó" not in txt.lower():
        continue
    detail_anchors.append(a)
print("NEKERA_EXACT_DETAIL_ANCHOR_COUNT",len(detail_anchors))
for i,a in enumerate(detail_anchors[:12]):
    print("NEKERA_EXACT_DETAIL_ANCHOR",i,compact(str(a))[:5000])
    node=a
    for level in range(1,5):
        node=node.parent if node else None
        if not node: break
        html=compact(str(node))
        if level<=3:
            print("NEKERA_EXACT_DETAIL_PARENT",i,level,html[:9000])
    form=a.find_parent("form")
    if form is not None:
        print("NEKERA_EXACT_DETAIL_FORM",i,compact(str(form))[:12000])
    hidden=[]
    root=a
    for _ in range(5):
        root=root.parent if root else None
        if root is None: break
        hs=root.find_all(["input","button"],limit=80)
        for h in hs:
            nm=h.get("name");val=h.get("value");did=h.get("data-id") or h.get("data-offer-id")
            if nm or val or did:
                rec=(h.name,nm,val,did,h.get("type"),h.get("class"))
                if rec not in hidden:hidden.append(rec)
        if hidden: break
    print("NEKERA_EXACT_DETAIL_FIELDS",i,hidden[:40])

print("NEKERA_DETAIL_CANDIDATES",len(candidates))
for i,(u,t,b) in enumerate(candidates[:20]):
    print("NEKERA_DETAIL_LINK",i,u,"TEXT",t[:300],"BLOCK",b[:1700])

for i,(u,t,b) in enumerate(candidates[:6]):
    try:
        rr=requests.get(u,headers=HEAD,timeout=35,allow_redirects=True)
        print("NEKERA_DETAIL_FETCH",i,rr.status_code,rr.url,len(rr.content))
        ss=BeautifulSoup(rr.text,"html.parser")
        text=compact(ss.get_text(" ",strip=True))
        signals(text,f"detail-{i}")
        # expose booking/calculation links/forms without assuming their meaning
        for a in ss.find_all("a",href=True):
            at=compact(a.get_text(" ",strip=True)); ah=a.get("href","")
            if any(k in (at+" "+ah).lower() for k in ["rezerw","kalkul","book","wybierz","sprawdź cen","sprawdz cen"]):
                print("NEKERA_BOOK_LINK",i,exactify(ah),at[:500])
        for form in ss.find_all("form"):
            html=str(form)
            if any(k in html.lower() for k in ["rezerw","price","adult","child","offer","booking"]):
                print("NEKERA_DETAIL_FORM",i,compact(html)[:7000])
    except Exception as e:
        print("NEKERA_DETAIL_ERR",i,type(e).__name__,str(e)[:240])
