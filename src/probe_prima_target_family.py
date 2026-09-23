import json,requests
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

GQL="https://app.primaholiday.pl/graphql"
TZ=ZoneInfo("Europe/Warsaw")
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}

def gql(q,v=None,op=None):
    r=requests.post(GQL,json={"operationName":op,"variables":v or {},"query":q},headers=H,timeout=40)
    print("PRIMATARGET_STATUS",op,r.status_code,len(r.content))
    r.raise_for_status()
    return r.json()

def val(v):
    if isinstance(v,str):
        try:return json.loads(v)
        except:return v
    return v

def raw_items():
    d=gql("query R{bluevendoSearch}",op="R")
    raw=val((d.get("data") or {}).get("bluevendoSearch")) or {}
    x=((raw.get("items") or {}).get("item") or []) if isinstance(raw,dict) else []
    return x if isinstance(x,list) else [x]

def offer(oid):
    d=gql("query O($id:ID!){bluevendoOffer(id:$id)}",{"id":str(oid)},"O")
    return val((d.get("data") or {}).get("bluevendoOffer")) or {}

CALC="""query Calc($persons:[PersonsGroupInput!]!,$trips:[TripInput!]!){
 bluevendoFastCalculation(persons:$persons,trips:$trips){
  trips{price tripId lowestPrice persons{totalPrice}}
 }
}"""

def calc(t,ages,label):
    v={"persons":[{"person":[{"age":a} for a in ages]}],
       "trips":[{"tripid":int(t["id"]),"departureid":int(t["departureid"]),"arrivalid":int(t["arrivalid"])}]}
    d=gql(CALC,v,label)
    rows=(((d.get("data") or {}).get("bluevendoFastCalculation") or {}).get("trips") or [])
    if not isinstance(rows,list):rows=[rows] if rows else []
    match=next((x for x in rows if str(x.get("tripId"))==str(t["id"])), rows[0] if rows else None)
    print("PRIMATARGET_CALC",label,json.dumps(match,ensure_ascii=False) if match else "null")
    return match

def price_parts(row):
    try:
        people=[float(x["totalPrice"]) for x in row.get("persons") or []]
        total=float(row["price"])
        return people,total
    except:return [],None

def main():
    today=datetime.now(TZ).date()
    allowed={(today+timedelta(days=i)).isoformat() for i in (1,2,3)}
    items=raw_items()
    print("PRIMATARGET_RAW_ITEMS",len(items))
    flight_offers={}
    for item in items:
        ats=(item.get("availabletransporttypes") or {}).get("availabletransporttype") or []
        if isinstance(ats,dict):ats=[ats]
        for a in ats:
            if str(a.get("transporttypeid"))=="1" and a.get("offerid"):
                flight_offers[str(a["offerid"])]={
                  "hotel":item.get("hotelname"),"standard":item.get("standard"),
                  "rateaverage":item.get("rateaverage")
                }
    print("PRIMATARGET_FLIGHT_OFFERS",len(flight_offers))
    candidates=[]
    for oid,base in flight_offers.items():
        data=offer(oid)
        trips=((data.get("trips") or {}).get("trip") or []) if isinstance(data,dict) else []
        if isinstance(trips,dict):trips=[trips]
        for t in trips:
            if str(t.get("start")) not in allowed:continue
            try:n=int(t.get("length") or 0)
            except:n=0
            if not 5<=n<=8:continue
            airport=str(t.get("departurecityname") or "")
            if not any(k in airport.lower() for k in ["warsz","radom","modlin"]):continue
            if str(t.get("transporttypeid"))!="1":continue
            try:maxroom=int(t.get("maxroom") or 0)
            except:maxroom=0
            if maxroom<1:continue
            if str(t.get("onrequest")).lower() not in ("false","f","0"):continue
            rec={**base,**t}
            candidates.append(rec)
            print("PRIMATARGET_LIVE_CANDIDATE",json.dumps(rec,ensure_ascii=False)[:9000])
    print("PRIMATARGET_LIVE_CANDIDATE_COUNT",len(candidates))
    proofs=[]
    for t in candidates[:15]:
        f=calc(t,[18,18,5,7],"FAMILY")
        a=calc(t,[18,18],"ADULTS")
        fp,ft=price_parts(f or {}); ap,at=price_parts(a or {})
        if len(fp)!=4 or len(ap)!=2 or ft is None or at is None:continue
        if abs(sum(fp)-ft)>.01 or abs(sum(ap)-at)>.01:continue
        if not ft>at>0:continue
        fr=calc(t,[18,18,5,7],"FAMILY_RECHECK")
        rp,rt=price_parts(fr or {})
        if len(rp)!=4 or rt!=ft:continue
        p={"tripid":t["id"],"offerid":t.get("offerid"),"hotel":t.get("hotel"),
           "standard":t.get("standard"),"start":t.get("start"),"nights":t.get("length"),
           "airport":t.get("departurecityname"),"onrequest":t.get("onrequest"),"maxroom":t.get("maxroom"),
           "meal":t.get("maintenancestandardname") or t.get("maintenancename"),
           "family_total":ft,"adults_total":at,"family_people":fp,"recheck":rt}
        proofs.append(p);print("PRIMATARGET_PROOF",json.dumps(p,ensure_ascii=False))
    print("PRIMATARGET_EXACT_PARTY",json.dumps({"adults":2,"children":2,"ages":[5,7]}))
    print("PRIMATARGET_VERIFIED_COUNT",len(proofs))
    print("PRIMATARGET_VERIFIED",bool(proofs))
if __name__=="__main__":main()
