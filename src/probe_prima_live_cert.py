import json,requests
from datetime import datetime
from zoneinfo import ZoneInfo

GQL="https://app.primaholiday.pl/graphql"
TZ=ZoneInfo("Europe/Warsaw")
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}

def gql(q,v=None,op=None):
    r=requests.post(GQL,json={"operationName":op,"variables":v or {},"query":q},headers=H,timeout=40)
    print("PRIMACERT_STATUS",op,r.status_code,len(r.content))
    r.raise_for_status(); return r.json()

def val(v):
    if isinstance(v,str):
        try:return json.loads(v)
        except:return v
    return v

CALC="""query C($persons:[PersonsGroupInput!]!,$trips:[TripInput!]!){
 bluevendoFastCalculation(persons:$persons,trips:$trips){
  trips{price tripId lowestPrice persons{totalPrice}}
 }
}"""

def calc(t,ages,label):
    v={"persons":[{"person":[{"age":a} for a in ages]}],
       "trips":[{"tripid":int(t["id"]),"departureid":int(t["departureid"]),"arrivalid":int(t["arrivalid"])}]}
    d=gql(CALC,v,"C")
    rows=(((d.get("data") or {}).get("bluevendoFastCalculation") or {}).get("trips") or [])
    if not isinstance(rows,list):rows=[rows] if rows else []
    return next((x for x in rows if str(x.get("tripId"))==str(t["id"])),rows[0] if rows else None)

def parts(row):
    try:
        ps=[float(x["totalPrice"]) for x in row.get("persons") or []]
        total=float(row["price"])
        return ps,total
    except:return [],None

def main():
    raw=val((gql("query R{bluevendoSearch}",op="R").get("data") or {}).get("bluevendoSearch")) or {}
    items=((raw.get("items") or {}).get("item") or []) if isinstance(raw,dict) else []
    if isinstance(items,dict):items=[items]
    bases={}
    for item in items:
        ats=(item.get("availabletransporttypes") or {}).get("availabletransporttype") or []
        if isinstance(ats,dict):ats=[ats]
        for a in ats:
            if str(a.get("transporttypeid"))=="1" and a.get("offerid"):
                bases[str(a["offerid"])]={"hotel":item.get("hotelname"),"standard":item.get("standard"),
                  "rateaverage":item.get("rateaverage"),"hotelid":item.get("hotelid")}
    proofs=[]
    today=datetime.now(TZ).date()
    for oid,base in bases.items():
        d=gql("query O($id:ID!){bluevendoOffer(id:$id)}",{"id":oid},"O")
        ov=val((d.get("data") or {}).get("bluevendoOffer")) or {}
        trips=((ov.get("trips") or {}).get("trip") or []) if isinstance(ov,dict) else []
        if isinstance(trips,dict):trips=[trips]
        for t in trips:
            try:
                start=datetime.strptime(str(t.get("start")),"%Y-%m-%d").date()
                nights=int(t.get("length") or 0); maxroom=int(t.get("maxroom") or 0)
            except:continue
            airport=str(t.get("departurecityname") or "")
            if start < today or (start-today).days>45:continue
            if not 5<=nights<=8:continue
            if not any(k in airport.lower() for k in ["warsz","radom","modlin"]):continue
            if str(t.get("transporttypeid"))!="1" or str(t.get("onrequest")).lower() not in ("false","f","0") or maxroom<1:continue
            fam=calc(t,[18,18,5,7],"FAMILY")
            ad=calc(t,[18,18],"ADULTS")
            fp,ft=parts(fam or {}); ap,at=parts(ad or {})
            if len(fp)!=4 or len(ap)!=2 or ft is None or at is None:continue
            if abs(sum(fp)-ft)>.01 or abs(sum(ap)-at)>.01 or not ft>at>0:continue
            # second independent live offer re-read
            d2=gql("query O($id:ID!){bluevendoOffer(id:$id)}",{"id":oid},"O2")
            ov2=val((d2.get("data") or {}).get("bluevendoOffer")) or {}
            ts2=((ov2.get("trips") or {}).get("trip") or []) if isinstance(ov2,dict) else []
            if isinstance(ts2,dict):ts2=[ts2]
            live2=next((x for x in ts2 if str(x.get("id"))==str(t.get("id"))
              and str(x.get("onrequest")).lower() in ("false","f","0")
              and int(x.get("maxroom") or 0)>0),None)
            if not live2:continue
            re=calc(live2,[18,18,5,7],"FAMILY_RECHECK"); rp,rt=parts(re or {})
            if len(rp)!=4 or rt is None or abs(rt-ft)>.01:continue
            p={**base,"offerid":oid,"tripid":str(t.get("id")),"start":str(t.get("start")),
              "end":str(t.get("end")),"nights":nights,"airport":airport,
              "departureid":str(t.get("departureid")),"arrivalid":str(t.get("arrivalid")),
              "roomid":str(t.get("roomid")),"meal":t.get("maintenancestandardname") or t.get("maintenancename"),
              "maxroom":maxroom,"onrequest":t.get("onrequest"),"family_people":fp,
              "family_total":ft,"adults_total":at,"delta":ft-at,"recheck_total":rt}
            proofs.append(p);print("PRIMACERT_PROOF",json.dumps(p,ensure_ascii=False))
            if len(proofs)>=5:break
        if len(proofs)>=5:break
    print("PRIMACERT_EXACT_PARTY",json.dumps({"adults":2,"children":2,"ages":[5,7]}))
    print("PRIMACERT_LIVE_PROOF_COUNT",len(proofs))
    print("PRIMACERT_VERIFIED",bool(proofs))
    if not proofs: raise SystemExit("FAIL_CLOSED: no live party-sensitive family proof")
if __name__=="__main__":main()
