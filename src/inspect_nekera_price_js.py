import re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

URL="https://www.nekera.pl/hotels/?adults=2&child=2021-01-01&child=2019-01-01&product=F"
HEAD={"User-Agent":"Mozilla/5.0","Accept-Language":"pl-PL"}
TERMS=["priceView","pricetype","price_type","za wszystkich","za osob","/os.","offer-price","totalPrice","total_price"]

r=requests.get(URL,headers=HEAD,timeout=30);r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
scripts=[]
for s in soup.find_all("script"):
    src=s.get("src")
    if src:
        u=urljoin(r.url,src)
        if u not in scripts:scripts.append(u)
priority=sorted(scripts,key=lambda u:0 if any(x in u.lower() for x in ["offerc","listing","searchbar","price"]) else 1)
print("NEKERA_PRICE_JS_COUNT",len(priority))
for u in priority:
    try:
        rr=requests.get(u,headers=HEAD,timeout=25)
        if rr.status_code!=200 or len(rr.content)>2500000:continue
        txt=rr.text;low=txt.lower()
        hits=[t for t in TERMS if t.lower() in low]
        if not hits:continue
        print("NEKERA_PRICE_JS_FILE",u,"LEN",len(txt),"HITS",hits)
        for term in hits:
            p=0
            for _ in range(8):
                i=low.find(term.lower(),p)
                if i<0:break
                sn=re.sub(r"\s+"," ",txt[max(0,i-1000):min(len(txt),i+1800)])
                print("NEKERA_PRICE_JS_SNIP",term,sn[:3600])
                p=i+len(term)
    except Exception as e:
        print("NEKERA_PRICE_JS_ERR",u,type(e).__name__,str(e)[:180])
