import re, json, requests
from bs4 import BeautifulSoup
from urllib.parse import urlencode

URL="https://fly.pl/szukaj-wycieczek/"
HEAD={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL"}

COMMON=[
 ("filter[from]",""),("filter[dest]",""),("filter[hotelids]",""),("filter[cityids]",""),
 ("filter[fp]","1"),("filter[whenFrom]","24-09-2026"),("filter[whenTo]","22-03-2027"),
 ("filter[duration]","7:15"),("durationFrom","7"),("durationTo","15"),
 ("filter[addCatering]",""),("filter[price]","0"),("fromPrice","0"),("toPrice",""),
 ("filter[tourOperator]",""),("filter[addMisc]",""),("filter[addCategory]","0"),
 ("filter[addTransport]","F"),("filter[addObjType]",""),("ajaxRequest","true")
]
FAMILY=COMMON+[("filter[person]","2"),("filter[child]","2"),
 ("filter[childAge][1]","5"),("filter[childAge][2]","7")]
ADULTS=COMMON+[("filter[person]","2"),("filter[child]","0")]

def fetch(label,params):
    r=requests.get(URL,params=params,headers=HEAD,timeout=35)
    print("FLY_AJAX_STATUS",label,r.status_code,r.url,len(r.content),r.headers.get("content-type"))
    r.raise_for_status()
    text=r.text
    print("FLY_AJAX_SIGNALS",label,{
      "child2": "filter%5Bchild%5D=2" in r.url or "filter[child]=2" in r.url,
      "age1": ("childAge%5D%5B1%5D=5" in r.url or "filter%5BchildAge%5D%5B1%5D=5" in r.url or "filter[childAge][1]=5" in r.url), "age2":("childAge%5D%5B2%5D=7" in r.url or "filter%5BchildAge%5D%5B2%5D=7" in r.url or "filter[childAge][2]=7" in r.url),
      "za_wszystkich":"za wszystkich" in text.lower(),
      "number_of_kids": "number_of_kids" in text.lower(),
      "priceView":"priceview" in text.lower()
    })
    for term in ["number_of_kids","number_of_adults","priceView","za wszystkich","/os.","total","price"]:
        low=text.lower(); p=0
        for _ in range(4):
            i=low.find(term.lower(),p)
            if i<0:break
            sn=re.sub(r"\s+"," ",text[max(0,i-500):min(len(text),i+1300)])
            print("FLY_AJAX_SNIP",label,term,sn[:2200])
            p=i+len(term)
    return text

def cards(text):
    soup=BeautifulSoup(text,"html.parser")
    out=[]
    for node in soup.find_all(True):
        attrs=" ".join(f"{k}={v}" for k,v in node.attrs.items())
        blob=(attrs+" "+node.get_text(" ",strip=True)).lower()
        if "zł" not in blob: continue
        # prefer compact offer/card blocks carrying a hotel/offer id
        if not any(k in blob for k in ["offer","hotel","price","trip"]): continue
        txt=" ".join(node.get_text(" ",strip=True).split())
        if not (40 <= len(txt) <= 1800): continue
        ident=node.get("data-id") or node.get("data-offer-id") or node.get("id") or ""
        prices=[int(re.sub(r"\D","",x)) for x in re.findall(r"\b\d[\d ]{1,8}\s*zł",txt) if re.sub(r"\D","",x)]
        if prices:
            rec={"id":str(ident),"text":txt[:900],"prices":prices[:8],"attrs":attrs[:700]}
            if rec not in out:out.append(rec)
    return out[:80]

fam=fetch("FAMILY",FAMILY)
adu=fetch("ADULTS",ADULTS)
fc=cards(fam); ac=cards(adu)
print("FLY_AJAX_CARD_COUNT",len(fc),len(ac))
for x in fc[:12]: print("FLY_AJAX_FAMILY_CARD",repr(x))
for x in ac[:8]: print("FLY_AJAX_ADULT_CARD",repr(x))
