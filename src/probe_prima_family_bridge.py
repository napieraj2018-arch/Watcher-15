import json,requests
from datetime import datetime,timedelta,date
from zoneinfo import ZoneInfo

GQL="https://app.primaholiday.pl/graphql"
TZ=ZoneInfo("Europe/Warsaw")
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}

def gql(query,variables=None,op=None):
    r=requests.post(GQL,json={"operationName":op,"variables":variables or {},"query":query},headers=H,timeout=40)
    print("PRIMABRIDGE_STATUS",op,r.status_code,len(r.content))
    r.raise_for_status()
    return r.json()

def raw_search():
    d=gql("query Raw { bluevendoSearch }",op="Raw")
    v=(d.get("data") or {}).get("bluevendoSearch") or {}
    if isinstance(v,str):
        try:v=json.loads(v)
        except:return {}
    return v

def offer(offerid):
    d=gql("query OfferRaw($id: ID!){ bluevendoOffer(id:$id) }",{"id":str(offerid)},"OfferRaw")
    v=(d.get("data") or {}).get("bluevendoOffer")
    if isinstance(v,str):
        try:v=json.loads(v)
        except:pass
    return v

CALC="""query Calc($persons:[PersonsGroupInput!]!,$trips:[TripInput!]!){
 bluevendoFastCalculation(persons:$persons,trips:$trips){
  trips{price tripId lowestPrice persons{totalPrice}}
 }
}"""

def calc(trip,ages,label):
    variables={"persons":[{"person":[{"age":a} for a in ages]}],"trips":[{
      "tripid":int(trip["id"]),"departureid":int(trip.get("departure") or 0),"arrivalid":int(trip.get("arrival") or 0)
    }]}
    d=gql(CALC,variables,label)
    rows=(((d.get("data") or {}).get("bluevendoFastCalculation") or {}).get("trips") or [])
    for x in rows:print("PRIMABRIDGE_CALC",label,json.dumps(x,ensure_ascii=False))
    return rows[0] if rows else None

def parts(row):
    try:
        vals=[float(x["totalPrice"]) for x in row.get("persons") or []]
        price=float(row["price"])
        return vals,price
    except:return [],None

def item_list(raw):
    items=(((raw.get("items") or {}).get("item")) if isinstance(raw,dict) else None) or []
    return items if isinstance(items,list) else [items]

def transport_rows(item):
    out=[]
    if str(item.get("transporttypeid"))=="1":
        out.append(("direct",str(item.get("offerid")),item))
    at=(item.get("availabletransporttypes") or {}).get("availabletransporttype") or []
    if isinstance(at,dict):at=[at]
    for x in at:
        if str(x.get("transporttypeid"))=="1" and x.get("offerid"):
            out.append(("alternate",str(x["offerid"]),None))
    return out

def find_trip(obj):
    if isinstance(obj,dict):
        if isinstance(obj.get("mintrip"),dict):return obj["mintrip"],obj
        for v in obj.values():
            hit=find_trip(v)
            if hit:return hit
    elif isinstance(obj,list):
        for v in obj:
            hit=find_trip(v)
            if hit:return hit
    return None

def main():
    today=datetime.now(TZ).date()
    raw=raw_search()
    items=item_list(raw)
    print("PRIMABRIDGE_RAW_ITEMS",len(items))
    candidates=[]
    seen=set()
    for base in items:
        for mode,oid,direct in transport_rows(base):
            if oid in seen:continue
            seen.add(oid)
            obj=direct if direct is not None else offer(oid)
            hit=find_trip(obj)
            if not hit:
                print("PRIMABRIDGE_NO_TRIP",mode,oid);continue
            trip,owner=hit
            try:start=date.fromisoformat(str(trip.get("startdate")))
            except:continue
            try:nights=int(trip.get("staylength") or 0)
            except:nights=0
            meal=str(owner.get("maintenancestandardname") or owner.get("maintenancename") or trip.get("maintenancestandardname") or trip.get("maintenancename") or "")
            airport=str(trip.get("departurecityname") or trip.get("departurecode") or "")
            hotel=str(owner.get("hotelname") or base.get("hotelname") or "")
            standard=str(owner.get("standard") or base.get("standard") or "")
            rec={"mode":mode,"offerid":oid,"trip":trip,"hotel":hotel,"standard":standard,"meal":meal,"airport":airport,"start":start.isoformat(),"nights":nights,"onrequest":trip.get("onrequest")}
            print("PRIMABRIDGE_CANDIDATE",json.dumps(rec,ensure_ascii=False,default=str)[:7000])
            if start < today or start > today+timedelta(days=30):continue
            if not (5<=nights<=8):continue
            if "all inclusive" not in meal.lower():continue
            candidates.append((trip,rec))
    print("PRIMABRIDGE_CANDIDATE_COUNT",len(candidates))
    proofs=[]
    for trip,meta in candidates[:12]:
        fam=calc(trip,[18,18,5,7],"FAMILY")
        ad=calc(trip,[18,18],"ADULTS")
        if not fam or not ad:continue
        fp,fprice=parts(fam);ap,aprice=parts(ad)
        if len(fp)!=4 or len(ap)!=2 or fprice is None or aprice is None:continue
        if abs(sum(fp)-fprice)>.01 or abs(sum(ap)-aprice)>.01:continue
        if not fprice>aprice>0:continue
        fresh=calc(trip,[18,18,5,7],"FAMILY_RECHECK")
        rp,rprice=parts(fresh or {})
        if len(rp)!=4 or rprice!=fprice:continue
        proof=dict(meta);proof.update({"family_total":fprice,"adults_total":aprice,"delta":fprice-aprice,"family_person_totals":fp,"recheck_total":rprice})
        proofs.append(proof)
        print("PRIMABRIDGE_PROOF",json.dumps(proof,ensure_ascii=False,default=str)[:10000])
    print("PRIMABRIDGE_EXACT_PARTY",[18,18,5,7])
    print("PRIMABRIDGE_LIVE_FAMILY_PROOF_COUNT",len(proofs))
    print("PRIMABRIDGE_VERIFIED",bool(proofs))

    schema='''query Types {
      trip: __type(name:"TripCalculation"){fields{name type{kind name ofType{kind name}}}}
      room: __type(name:"RoomConfiguration"){inputFields{name type{kind name ofType{kind name}}}}
      person: __type(name:"PersonConfiguration"){inputFields{name type{kind name ofType{kind name}}}}
    }'''
    print("PRIMABRIDGE_TYPES",json.dumps(gql(schema,op="Types"),ensure_ascii=False)[:30000])

if __name__=="__main__":main()
