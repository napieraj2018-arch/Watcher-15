import hashlib
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from watcher import create_alert

TZ=ZoneInfo("Europe/Warsaw")
GQL="https://app.primaholiday.pl/graphql"
HOME="https://www.primaholiday.pl/"
HEADERS={
    "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
    "Origin":HOME.rstrip("/"),"Referer":HOME,"Content-Type":"application/json",
}
Q_SEARCH="query R{bluevendoSearch}"
Q_OFFER="query O($id:ID!){bluevendoOffer(id:$id)}"
Q_CALC="""query C($persons:[PersonsGroupInput!]!,$trips:[TripInput!]!){
 bluevendoFastCalculation(persons:$persons,trips:$trips){
  trips{price tripId lowestPrice persons{totalPrice}}
 }
}"""

def _gql(q,variables=None,op=None):
    r=requests.post(GQL,json={"operationName":op,"variables":variables or {},"query":q},headers=HEADERS,timeout=45)
    print("PRIMA_PROD_STATUS",op,r.status_code,len(r.content))
    r.raise_for_status()
    data=r.json()
    if data.get("errors"):
        print("PRIMA_PROD_GRAPHQL_ERRORS",op,json.dumps(data["errors"],ensure_ascii=False)[:1600])
    return data

def _json_value(v):
    if isinstance(v,str):
        try:return json.loads(v)
        except:return v
    return v

def _raw_items():
    raw=_json_value((_gql(Q_SEARCH,op="R").get("data") or {}).get("bluevendoSearch")) or {}
    items=((raw.get("items") or {}).get("item") or []) if isinstance(raw,dict) else []
    if isinstance(items,dict):items=[items]
    rows=[x for x in items if isinstance(x,dict)]
    print("PRIMA_PROD_RAW_ITEMS",len(rows))
    return rows

def _flight_bases(items):
    out={}
    for item in items:
        ats=(item.get("availabletransporttypes") or {}).get("availabletransporttype") or []
        if isinstance(ats,dict):ats=[ats]
        for t in ats:
            if str(t.get("transporttypeid"))=="1" and t.get("offerid"):
                out[str(t["offerid"])]=item
    print("PRIMA_PROD_FLIGHT_OFFERS",len(out))
    return out

def _offer(oid):
    v=_json_value((_gql(Q_OFFER,{"id":oid},"O").get("data") or {}).get("bluevendoOffer")) or {}
    return v if isinstance(v,dict) else {}

def _trips(offer):
    rows=((offer.get("trips") or {}).get("trip") or []) if isinstance(offer,dict) else []
    if isinstance(rows,dict):rows=[rows]
    return [x for x in rows if isinstance(x,dict)]

def _num(v):
    try:return float(str(v).replace(",","."))
    except:return None

def _calc(t,ages,label):
    try:
        trip={"tripid":int(t["id"]),"departureid":int(t["departureid"]),"arrivalid":int(t["arrivalid"])}
    except:return None
    v={"persons":[{"person":[{"age":int(a)} for a in ages]}],"trips":[trip]}
    data=_gql(Q_CALC,v,"C")
    rows=(((data.get("data") or {}).get("bluevendoFastCalculation") or {}).get("trips") or [])
    if isinstance(rows,dict):rows=[rows]
    return next((x for x in rows if str(x.get("tripId"))==str(t.get("id"))),rows[0] if rows else None)

def _calc_proof(t):
    fam=_calc(t,[18,18,5,7],"FAMILY")
    adults=_calc(t,[18,18],"ADULTS")
    if not isinstance(fam,dict) or not isinstance(adults,dict):return None
    try:
        fp=[float(x["totalPrice"]) for x in fam.get("persons") or []]
        ap=[float(x["totalPrice"]) for x in adults.get("persons") or []]
        ft=float(fam["price"]);at=float(adults["price"])
    except:return None
    if len(fp)!=4 or len(ap)!=2:return None
    if abs(sum(fp)-ft)>.01 or abs(sum(ap)-at)>.01:return None
    if not ft>at>0:return None
    return {"family_total":ft,"adult_total":at,"family_people":fp,"adult_people":ap}

def _date(v):
    try:return datetime.strptime(str(v),"%Y-%m-%d").date()
    except:return None

def _stars(v):
    s=str(v or "")
    n=s.count("*")
    if n:return n
    try:return int(float(s))
    except:return None

def _quality(base):
    rating=_num(base.get("rateaverage"))
    if rating is not None and 0<rating<=5:rating*=2
    reviews=None
    for k,v in base.items():
        lo=str(k).lower()
        if "review" in lo or "opinion" in lo:
            if any(x in lo for x in ("count","number","amount","total")):
                n=_num(v)
                if n is not None:reviews=int(n);break
    return rating,reviews

def _airport(raw,configured):
    r=" ".join(str(raw or "").lower().replace("-"," ").split())
    aliases={"warszawa okęcie":"warszawa","warszawa chopin":"warszawa","warszawa":"warszawa",
             "warszawa modlin":"warszawa modlin","modlin":"warszawa modlin",
             "warszawa radom":"warszawa radom","radom":"warszawa radom"}
    rn=aliases.get(r,r)
    for wanted in configured:
        w=" ".join(str(wanted).lower().replace("-"," ").split())
        if aliases.get(w,w)==rn:return wanted
    return None

def _candidate(base,t,cfg,allowed):
    dep=_date(t.get("start"));ret=_date(t.get("end"))
    if dep not in allowed or not ret:return None
    try:nights=int(t.get("length") or 0);maxroom=int(t.get("maxroom") or 0)
    except:return None
    if not cfg["min_nights"]<=nights<=cfg["max_nights"]:return None
    if str(t.get("transporttypeid"))!="1":return None
    if str(t.get("onrequest")).lower() not in ("false","f","0") or maxroom<1:return None
    meal=str(t.get("maintenancestandardname") or t.get("maintenancename") or "")
    if cfg["meal_contains"].lower() not in meal.lower():return None
    airport=_airport(t.get("departurecityname"),cfg["airports"])
    if not airport:return None
    proof=_calc_proof(t)
    if not proof:return None
    ft=proof["family_total"]
    if ft<=0:return None
    hotel=str(base.get("hotelname") or "").strip()
    if not hotel:return None
    stars=_stars(base.get("standard"));rating,reviews=_quality(base)
    stable="|".join([str(t.get(k) or "") for k in ("id","offerid","hotelid","start","end","roomid","maintenanceid","departureid","arrivalid")])
    return {
      "key":hashlib.sha1(stable.encode()).hexdigest()[:16],"hotel":hotel,"href":HOME,"verified_href":HOME,
      "price":int(round(ft)),"departure":dep,"return":ret,"nights":nights,"airport":airport,"meal":meal,
      "operator":"Prima Holiday","rating":rating,"reviews":reviews,"stars":stars,
      "prima_offer_id":str(t.get("offerid") or ""),"prima_trip_id":str(t.get("id") or ""),
      "departureid":str(t.get("departureid") or ""),"arrivalid":str(t.get("arrivalid") or ""),
      "roomid":str(t.get("roomid") or ""),"maxroom":maxroom,
      "adult_only_total":int(round(proof["adult_total"])),"family_people":proof["family_people"],
      "family_price_proof":"BluevendoFastCalculation exact [18,18,5,7]; four participant totals sum to trip price; same trip [18,18] total is lower",
    }

def _fetch(cfg):
    today=datetime.now(TZ).date()
    ds=sorted(int(x) for x in cfg["depart_in_days"])
    allowed={today+timedelta(days=d) for d in ds}
    bases=_flight_bases(_raw_items())
    out=[]
    for oid,base in bases.items():
        offer=_offer(oid)
        for t in _trips(offer):
            c=_candidate(base,t,cfg,allowed)
            if c:
                out.append(c);print("PRIMA_PROD_EXACT_CARD",c)
    print("PRIMA_PROD_EXACT_LIVE",len(out))
    return out

def _quality_ok(x,cfg):
    return (
      x["price"]<=cfg["max_total_price_pln"]
      and x["stars"] is not None and x["stars"]>=cfg["min_stars"]
      and x["rating"] is not None and x["rating"]>=cfg["min_rating"]
      and x["reviews"] is not None and x["reviews"]>=cfg["min_reviews"]
    )

def _recheck(cand,cfg):
    offer=_offer(cand["prima_offer_id"])
    t=next((x for x in _trips(offer) if str(x.get("id"))==cand["prima_trip_id"]),None)
    if not t:return None
    try:
        if str(t.get("onrequest")).lower() not in ("false","f","0") or int(t.get("maxroom") or 0)<1:return None
    except:return None
    proof=_calc_proof(t)
    if not proof or int(round(proof["family_total"]))!=cand["price"]:return None
    fresh=dict(cand)
    fresh["maxroom"]=int(t.get("maxroom") or 0)
    fresh["adult_only_total"]=int(round(proof["adult_total"]))
    fresh["family_people"]=proof["family_people"]
    return fresh

def run_prima_watcher(cfg):
    if cfg.get("adults")!=2 or cfg.get("children_ages")!=[5,7]:
        raise RuntimeError("Prima production adapter is locked to exact 2+2 ages 5/7")
    first=_fetch(cfg)
    qualified=[x for x in first if _quality_ok(x,cfg)]
    print("PRIMA_PROD_QUALIFIED",len(qualified))
    if first and not qualified:print("PRIMA_PROD_QUALITY_FAIL_CLOSED")
    token=os.getenv("GITHUB_TOKEN","");repo=os.getenv("GITHUB_REPOSITORY","")
    for cand in qualified[:10]:
        confirmed=_recheck(cand,cfg)
        if not confirmed or not _quality_ok(confirmed,cfg):
            print("PRIMA_PROD_RECHECK_REJECT",cand["key"]);continue
        print("PRIMA_PROD_RECHECK_VERIFIED",confirmed["hotel"],confirmed["price"])
        if token and repo:
            create_alert(token,repo,cfg,confirmed,"Prima exact 2+2 ages 5/7 + live flight trip + party-sensitive final GraphQL total + second live recheck")
        else:print("PRIMA_PROD_DRY_ALERT",confirmed)
