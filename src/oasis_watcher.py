import hashlib
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from watcher import create_alert, configured_departure_dates

TZ=ZoneInfo("Europe/Warsaw")
BASE="https://oasis.pl/"
API=BASE+"api-bv/search-search"
HEADERS={
    "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
    "Accept":"application/json,text/plain,*/*",
    "Content-Type":"application/json",
    "Referer":BASE,
}

def _num(v):
    try:return float(str(v).replace(",","."))
    except:return None

def _pick(x,*names):
    for n in names:
        if n in x and x.get(n) not in (None,""):return x.get(n)
    return None

def _trip(x):
    for k in ("mintrip","trip","minTrip"):
        if isinstance(x.get(k),dict):return x[k]
    return {}

def _rows(data):
    if not isinstance(data,dict):return []
    d=data.get("data")
    if isinstance(d,dict):
        for k in ("items","offers","results"):
            if isinstance(d.get(k),list):return [x for x in d[k] if isinstance(x,dict)]
    return []

def _payload(cfg,family=True):
    dates=configured_departure_dates(cfg)
    p={
      "transporttypeid":"1",
      "adults":"2",
      "length":f"{int(cfg['min_nights'])}-{int(cfg['max_nights'])}",
      "priceend":str(max(25000000,int(cfg["max_total_price_pln"])*100)),
      "ordername":"price",
      "hoteltypeid":"",
      "startdate":dates[0].isoformat(),
      "enddate":dates[-1].isoformat(),
      "page":1,
      "numOnPage":"100",
      "pricestart":"100",
      "orderdirection":"asc",
    }
    if family:p["infants"]="5,7"
    return p,set(dates)

def _get(session,p,label):
    r=session.post(API,json=p,headers=HEADERS,timeout=55)
    print("OASIS_PROD_STATUS",label,r.status_code,len(r.content))
    r.raise_for_status()
    data=r.json()
    rows=_rows(data)
    print("OASIS_PROD_ROWS",label,len(rows))
    return rows

def _stable(x):
    t=_trip(x)
    return (
      str(_pick(x,"hotelid","hotelId") or ""),
      str(_pick(t,"roomid","roomId") or _pick(x,"roomid","roomId") or ""),
      str(_pick(t,"startdate","startDate") or ""),
      str(_pick(t,"enddate","endDate") or ""),
      str(_pick(x,"maintenanceid","maintenanceId") or ""),
      str(_pick(x,"transporttypeid","transportTypeId") or ""),
    )

def _date(v):
    try:return datetime.strptime(str(v),"%Y-%m-%d").date()
    except:return None

def _stars(v):
    s=str(v or "")
    n=s.count("*")
    if n:return n
    try:return int(float(s))
    except:return None

def _quality(x):
    rating=None;reviews=None
    for k,v in x.items():
        lo=str(k).lower()
        if rating is None and any(z in lo for z in ("rating","rate","score")) and "price" not in lo:
            n=_num(v)
            if n is not None:
                rating=n*2 if 0<n<=5 else n
        if reviews is None and any(z in lo for z in ("review","opinion")) and any(z in lo for z in ("count","number","amount","total")):
            n=_num(v)
            if n is not None:reviews=int(n)
    return rating,reviews

def _airport(name,configured):
    raw=" ".join(str(name or "").lower().replace("-"," ").split())
    if not raw:return None
    aliases={
      "warszawa":"warszawa","warszawa chopin":"warszawa","warszawa okęcie":"warszawa",
      "warszawa modlin":"warszawa modlin","modlin":"warszawa modlin",
      "warszawa radom":"warszawa radom","radom":"warszawa radom",
    }
    norm=aliases.get(raw,raw)
    for wanted in configured:
        w=" ".join(str(wanted).lower().replace("-"," ").split())
        wn=aliases.get(w,w)
        if norm==wn:return wanted
    return None

def _family_candidates(family,adults,cfg,allowed):
    adult_by_key={_stable(x):x for x in adults}
    out=[]
    for f in family:
        key=_stable(f)
        a=adult_by_key.get(key)
        if not a:continue
        t=_trip(f);at=_trip(a)
        # Exact live result: the same package must exist now for both controls.
        if str(t.get("onrequest","")).lower() not in ("f","false","0"):
            continue
        av=f.get("availabletransporttypes")
        if not av:continue
        dep=_date(_pick(t,"departuredate","startdate"))
        ret=_date(_pick(t,"arrivaldeparturedate","enddate"))
        if dep not in allowed or not ret or ret<=dep:continue
        nights=(ret-dep).days
        if not(cfg["min_nights"]<=nights<=cfg["max_nights"]):continue
        meal=str(_pick(f,"maintenancestandardname","maintenancename") or "")
        if cfg["meal_contains"].lower() not in meal.lower():continue
        airport_raw=str(_pick(t,"departurecityname") or "")
        airport=_airport(airport_raw,cfg["airports"])
        if not airport:continue
        ft=_num(_pick(f,"customertotalprice","totalprice","totalPrice"))
        atot=_num(_pick(a,"customertotalprice","totalprice","totalPrice"))
        if ft is None or atot is None or ft<=atot:continue
        currency=str(_pick(f,"totalPriceCurrency","customercurrency") or "PLN").upper()
        if currency!="PLN":continue
        # Never substitute customerbaseprice or any per-person field for total.
        total=int(round(ft))
        stars=_stars(_pick(f,"standard"))
        rating,reviews=_quality(f)
        hotel=str(_pick(f,"hotelname","hotelName") or "").strip()
        if not hotel:continue
        offerid=str(_pick(f,"offerid","offerId") or "")
        stable="|".join(key)
        oid=hashlib.sha1(stable.encode()).hexdigest()[:16]
        rec={
          "key":oid,"hotel":hotel,"href":BASE,"verified_href":BASE,"price":total,
          "departure":dep,"return":ret,"nights":nights,"airport":airport,"meal":meal,
          "operator":"Oasis Tours","rating":rating,"reviews":reviews,"stars":stars,
          "oasis_offer_id":offerid,"adult_only_total":int(round(atot)),
          "family_price_proof":"exact adults=2 + infants=5,7; same hotel/room/dates/meal/transport 2+0 control differs; customertotalprice",
        }
        out.append(rec);print("OASIS_PROD_EXACT_CARD",rec)
    print("OASIS_PROD_PARTY_SENSITIVE",len(out))
    return out

def _quality_ok(x,cfg):
    return (
      x["price"]<=cfg["max_total_price_pln"]
      and x["stars"] is not None and x["stars"]>=cfg["min_stars"]
      and x["rating"] is not None and x["rating"]>=cfg["min_rating"]
      and x["reviews"] is not None and x["reviews"]>=cfg["min_reviews"]
    )

def _fetch(cfg):
    family_p,allowed=_payload(cfg,True)
    adult_p,_=_payload(cfg,False)
    s=requests.Session()
    family=_get(s,family_p,"FAMILY")
    adults=_get(s,adult_p,"ADULTS")
    return _family_candidates(family,adults,cfg,allowed)

def run_oasis_watcher(cfg):
    if cfg.get("adults")!=2 or cfg.get("children_ages")!=[5,7]:
        raise RuntimeError("Oasis production adapter is locked to exact 2+2 ages 5/7")
    first=_fetch(cfg)
    qualified=[x for x in first if _quality_ok(x,cfg)]
    print("OASIS_PROD_EXACT_LIVE",len(first))
    print("OASIS_PROD_QUALIFIED",len(qualified))
    if first and not qualified:print("OASIS_PROD_QUALITY_FAIL_CLOSED")
    token=os.getenv("GITHUB_TOKEN","");repo=os.getenv("GITHUB_REPOSITORY","")
    for cand in qualified[:10]:
        fresh=_fetch(cfg)
        confirmed=next((x for x in fresh if x["key"]==cand["key"] and x["price"]==cand["price"] and _quality_ok(x,cfg)),None)
        if not confirmed:
            print("OASIS_PROD_RECHECK_REJECT",cand["key"]);continue
        print("OASIS_PROD_RECHECK_VERIFIED",confirmed["hotel"],confirmed["price"])
        if token and repo:
            create_alert(token,repo,cfg,confirmed,"Oasis exact 2+2 ages 5/7 + live BlueVendo availability + party-sensitive customertotalprice; second API recheck")
        else:print("OASIS_PROD_DRY_ALERT",confirmed)
