import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = "https://www.travelplanet.pl/wakacje/super-last-minute/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
}
KEYWORDS = [
    "nl_occupancy",
    "searchPreferencesOccupancy",
    "occupancy_children",
    "occupancy_child",
    "childAges",
    "child_ages",
    "childrenAges",
    "children",
    "child-1",
    "passengers",
]

def snippets(text, needle, radius=500, limit=12):
    out=[]
    low=text.lower(); target=needle.lower(); pos=0
    while len(out)<limit:
        i=low.find(target,pos)
        if i<0: break
        a=max(0,i-radius); b=min(len(text),i+len(needle)+radius)
        out.append(re.sub(r"\s+"," ",text[a:b]))
        pos=i+len(needle)
    return out

def main():
    s=requests.Session(); s.headers.update(HEADERS)
    r=s.get(URL,timeout=30)
    print("TP_JS_PAGE",r.status_code,len(r.content),r.url)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    scripts=[urljoin(r.url,x.get("src")) for x in soup.find_all("script") if x.get("src")]
    picked=[u for u in scripts if any(k in u.lower() for k in ["search","invia2020/js/app","invia2020/js/helpers"])]
    print("TP_JS_SCRIPT_COUNT",len(scripts),"PICKED",len(picked))
    print("TP_JS_SCRIPTS")
    for u in picked[:80]: print(u)

    found=0
    for u in picked[:40]:
        try:
            rr=s.get(u,timeout=30)
            text=rr.text if rr.status_code==200 else ""
            hits=[k for k in KEYWORDS if k.lower() in text.lower()]
            if not hits: continue
            found+=1
            print("TP_JS_HIT_FILE",u,"STATUS",rr.status_code,"LEN",len(text),"KEYS",hits)
            for k in hits:
                for n,snip in enumerate(snippets(text,k,limit=8)):
                    print("TP_JS_SNIP",k,n,snip[:1800])
        except Exception as e:
            print("TP_JS_FETCH_ERR",u,type(e).__name__,str(e)[:200])
    print("TP_JS_MATCHING_FILES",found)

if __name__=="__main__":
    main()
