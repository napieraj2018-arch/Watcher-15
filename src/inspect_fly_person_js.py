import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

URL="https://fly.pl/szukaj-wycieczek/"
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL"}
TERMS=["childAge","childage","data-childage","data-birthdate","filter[childAge]","data-dob","birthdate","datepicker","data-counter"]

def snips(text, term, radius=900, limit=8):
    low=text.lower(); t=term.lower(); p=0; out=[]
    while len(out)<limit:
        i=low.find(t,p)
        if i<0: break
        s=re.sub(r"\s+"," ",text[max(0,i-radius):min(len(text),i+len(term)+radius)])
        if s not in out: out.append(s)
        p=i+len(term)
    return out

r=requests.get(URL,headers=UA,timeout=30); r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
scripts=[]
for s in soup.find_all("script"):
    src=s.get("src")
    if src:
        u=urljoin(r.url,src)
        if u not in scripts: scripts.append(u)
print("FLY_PERSON_JS_ROOTS",len(scripts))
for u in scripts:
    try:
        rr=requests.get(u,headers=UA,timeout=25)
        if rr.status_code!=200 or len(rr.content)>3000000: continue
        txt=rr.text
        hits=[t for t in TERMS if t.lower() in txt.lower()]
        if not hits: continue
        print("FLY_PERSON_JS_FILE",u,"LEN",len(txt),"HITS",hits)
        for t in hits:
            for s in snips(txt,t):
                print("FLY_PERSON_JS_SNIP",t,s[:3200])
    except Exception as e:
        print("FLY_PERSON_JS_ERR",u,type(e).__name__,str(e)[:200])
