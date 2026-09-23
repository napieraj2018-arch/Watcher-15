import json,re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import requests

URL="https://www.grecos.pl/api/sitecore/OffersList/LoadMoreOffers"
TZ=ZoneInfo("Europe/Warsaw")
HEADERS={
    "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
    "Accept":"application/json,text/plain,*/*",
    "Accept-Language":"pl-PL,pl;q=0.9,en;q=0.7",
    "Referer":"https://www.grecos.pl/last-minute",
}

def snippets(text,pattern,radius=220,limit=30):
    out=[]
    for m in re.finditer(pattern,text,re.I):
        a=max(0,m.start()-radius); b=min(len(text),m.end()+radius)
        s=re.sub(r"\\s+"," ",text[a:b])
        if s not in out: out.append(s)
        if len(out)>=limit: break
    return out

def main():
    today=datetime.now(TZ).date()
    dep_from=today+timedelta(days=1)
    # latest allowed return: latest departure (today+3) + 8 nights
    ret_to=today+timedelta(days=11)
    # Fixed birthdays safely preserve ages 5 and 7 throughout the current travel window.
    child1=f"{today.year-5}0101"
    child2=f"{today.year-7}0101"
    params={
        "Adults":"2","Children":"2",
        "DurationInterval":"5:8",
        "Child1":child1,"Child2":child2,
        "DateOfDeparture":dep_from.strftime("%Y%m%d"),
        "DateOfReturn":ret_to.strftime("%Y%m%d"),
        "PriceFrom":"0","PriceTo":"50000",
        "PriceType":"man","OfferType":"L,S","ObjectType":"H,R,AP",
        "pageFrom":"0","setFilters":"true",
    }
    r=requests.get(URL,params=params,headers=HEADERS,timeout=35)
    print("GRECOS_STATUS",r.status_code)
    print("GRECOS_URL",r.url)
    print("GRECOS_CONTENT_TYPE",r.headers.get("content-type"))
    print("GRECOS_LEN",len(r.content))
    print("GRECOS_EXACT_PARTY",{"Adults":2,"Children":2,"ages":[5,7],"Child1":child1,"Child2":child2})
    text=r.text
    try:
        data=r.json()
        print("GRECOS_JSON_TYPE",type(data).__name__)
        if isinstance(data,dict):
            print("GRECOS_JSON_KEYS",list(data)[:80])
            for k,v in data.items():
                if isinstance(v,(str,int,float,bool)) or v is None:
                    print("GRECOS_TOP",k,repr(v)[:600])
                elif isinstance(v,list):
                    print("GRECOS_TOP_LIST",k,len(v))
                elif isinstance(v,dict):
                    print("GRECOS_TOP_DICT",k,list(v)[:40])
        text=json.dumps(data,ensure_ascii=False)
    except Exception as e:
        print("GRECOS_JSON_ERROR",type(e).__name__,str(e)[:200])

    for pat,label in [
        (r"total.{0,40}price|price.{0,40}total","TOTAL_PRICE"),
        (r"cena.{0,40}(?:całkow|razem|łącz)|(?:całkow|razem|łącz).{0,40}cena","TOTAL_LABEL"),
        (r"price","PRICE"),
        (r"Child1|Child2|Children|Adults","PARTY"),
        (r"available|availability|dostępn","AVAIL"),
        (r"all.?inclusive","AI"),
        (r"rating|ocen|opini","QUALITY"),
    ]:
        ss=snippets(text,pat)
        print("GRECOS_SNIPPETS",label,len(ss))
        for s in ss[:12]: print(label,s[:1800])

    # Explicitly reject any attempt to call a bare per-person value a family total.
    nums=[]
    for m in re.finditer(r'(?:totalPrice|total_price|priceTotal|Cena\\s*(?:całkowita|razem|łącznie))[^0-9]{0,80}([0-9][0-9 .]{2,})',text,re.I):
        raw=m.group(1); val=re.sub(r"\\D","",raw)
        if val: nums.append(int(val))
    print("GRECOS_EXPLICIT_TOTAL_CANDIDATES",nums[:50])

if __name__=="__main__":
    main()
