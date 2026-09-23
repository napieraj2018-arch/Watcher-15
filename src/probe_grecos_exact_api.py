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

def num(v):
    s=re.sub(r"\D","",str(v or ""))
    return int(s) if s else None

def fetch(params,label):
    r=requests.get(URL,params=params,headers=HEADERS,timeout=35)
    print(label+"_STATUS",r.status_code)
    print(label+"_URL",r.url)
    print(label+"_LEN",len(r.content))
    r.raise_for_status()
    data=r.json()
    print(label+"_JSON_TYPE",type(data).__name__,"COUNT",len(data) if isinstance(data,list) else None)
    return data

def key(x):
    return (
        x.get("Merlin_HotelCode"),
        x.get("Merlin_ParsedStartDate"),
        x.get("Merlin_Duration"),
        x.get("Merlin_BoardStandardDesc"),
        x.get("Merlin_FlightFrom"),
    )

def main():
    today=datetime.now(TZ).date()
    dep_from=today+timedelta(days=1)
    ret_to=today+timedelta(days=11)
    child1=f"{today.year-5}0101"
    child2=f"{today.year-7}0101"
    common={
        "DurationInterval":"5:8",
        "DateOfDeparture":dep_from.strftime("%Y%m%d"),
        "DateOfReturn":ret_to.strftime("%Y%m%d"),
        "PriceFrom":"0","PriceTo":"50000",
        "PriceType":"man","OfferType":"L,S","ObjectType":"H,R,AP",
        "pageFrom":"0","setFilters":"true",
    }
    family=common|{
        "Adults":"2","Children":"2","Child1":child1,"Child2":child2,
    }
    adults=common|{"Adults":"2","Children":"0"}

    fam=fetch(family,"GRECOS_FAMILY")
    print("GRECOS_EXACT_PARTY",{"Adults":2,"Children":2,"ages":[5,7],"Child1":child1,"Child2":child2})
    ad=fetch(adults,"GRECOS_ADULTS_ONLY")

    fam_rows=[x for x in fam if isinstance(x,dict)] if isinstance(fam,list) else []
    ad_rows=[x for x in ad if isinstance(x,dict)] if isinstance(ad,list) else []
    amap={key(x):x for x in ad_rows if x.get("Merlin_HotelCode")}
    matches=[]
    for x in fam_rows:
        k=key(x); y=amap.get(k)
        if not y: continue
        fp=num(x.get("Merlin_FullPriceParsed")); ap=num(y.get("Merlin_FullPriceParsed"))
        if fp is None or ap is None: continue
        rec={
            "key":k,
            "family_full":fp,
            "adults_full":ap,
            "family_adult_unit":num(x.get("Merlin_AdultPrice")),
            "family_query":x.get("Query_AdultsChildenQueryString"),
            "adult_query":y.get("Query_AdultsChildenQueryString"),
            "board":x.get("Merlin_BoardStandardDesc"),
            "stars":x.get("Hotel_Standard_Stars_Css"),
            "hotel_url":x.get("Hotel_Url") or x.get("Hotel_Link") or x.get("Hotel_FriendlyUrl"),
        }
        matches.append(rec)

    print("GRECOS_SAME_OFFER_COMPARISONS",len(matches))
    changed=[x for x in matches if x["family_full"]!=x["adults_full"]]
    for x in matches[:20]:
        print("GRECOS_COMPARE",repr(x))
    print("GRECOS_PARTY_SENSITIVE_FULL_PRICE_COUNT",len(changed))
    if changed:
        print("GRECOS_PARTY_SENSITIVE_PROOF",repr(changed[0]))

    exact_rows=[]
    expected=f"&Adults=2&Children=2&Child1={child1}&Child2={child2}"
    for x in fam_rows:
        q=x.get("Query_AdultsChildenQueryString") or ""
        full=num(x.get("Merlin_FullPriceParsed"))
        if expected==q and full:
            exact_rows.append(x)
    print("GRECOS_EXACT_LIVE_ROWS_WITH_FULL_PRICE",len(exact_rows))
    if exact_rows:\n        sample=exact_rows[0]\n        qfields={k:v for k,v in sample.items() if any(t in k.lower() for t in ["rating","review","opini","score","star","standard","flight","price","full","url","name"])}\n        print("GRECOS_QUALITY_FIELDS",repr(qfields))\n    for x in exact_rows[:15]:
        print("GRECOS_LIVE_FULL",repr({
            "hotel":x.get("Hotel_Name") or x.get("Merlin_HotelName") or x.get("Merlin_HotelCode"),
            "start":x.get("Merlin_ParsedStartDate"),
            "duration":x.get("Merlin_Duration"),
            "flight_from":x.get("Merlin_FlightFrom"),
            "board":x.get("Merlin_BoardStandardDesc"),
            "adult_unit":x.get("Merlin_AdultPrice"),
            "family_full":x.get("Merlin_FullPriceParsed"),
            "stars":x.get("Hotel_Standard_Stars_Css"),
            "query":x.get("Query_AdultsChildenQueryString"),
        }))

    verified=bool(exact_rows) and bool(changed)
    print("GRECOS_FULL_PRICE_IS_PARTY_SENSITIVE",bool(changed))
    print("GRECOS_EXACT_FAMILY_TOTAL_VERIFIED",verified)

if __name__=="__main__":
    main()
