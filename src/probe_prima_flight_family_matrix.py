import json,requests,time
from datetime import datetime
from zoneinfo import ZoneInfo

GQL="https://app.primaholiday.pl/graphql"
TZ=ZoneInfo("Europe/Warsaw")
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}
QS="query R{bluevendoSearch}"
QO="query O($id:ID!){bluevendoOffer(id:$id)}"
QC="""query C($persons:[PersonsGroupInput!]!,$trips:[TripInput!]!){
 bluevendoFastCalculation(persons:$persons,trips:$trips){trips{price tripId lowestPrice persons{totalPrice}}}
}"""

def gql(q,v=None,op=None):
    last=None
    for attempt in range(3):
        try:
            r=requests.post(GQL,json={"operationName":op,"variables":v or {},"query":q},headers=H,timeout=45)
            print("PRIMAMATRIX_STATUS",op,attempt+1,r.status_code,len(r.content))
            r.raise_for_status()
            data=r.json()
            # BlueVendo occasionally returns a successful HTTP response with a
            # transient null/error GraphQL payload. Retry those on live rechecks.
            if data.get("errors"):
                print("PRIMAMATRIX_GQL_ERRORS",op,json.dumps(data.get("errors"),ensure_ascii=False)[:1200])
                last=RuntimeError("GraphQL errors")
            else:
                return data
        except Exception as exc:
            last=exc
            print("PRIMAMATRIX_RETRY",op,attempt+1,type(exc).__name__,str(exc)[:200])
        if attempt<2: time.sleep(1.5*(attempt+1))
    raise last or RuntimeError("GraphQL request failed")

def val(v):
    if isinstance(v,str):
        try:return json.loads(v)
        except:return v
    return v

def calc_batch(trips,ages,label):
    req=[]
    for t in trips:
        try:req.append({"tripid":int(t["id"]),"departureid":int(t["departureid"]),"arrivalid":int(t["arrivalid"])})
        except:pass
    if not req:return {}
    v={"persons":[{"person":[{"age":a} for a in ages]}],"trips":req}
    d=gql(QC,v,"C")
    rows=(((d.get("data") or {}).get("bluevendoFastCalculation") or {}).get("trips") or [])
    if isinstance(rows,dict):rows=[rows]
    out={str(x.get("tripId")):x for x in rows if isinstance(x,dict)}
    print("PRIMAMATRIX_CALC_ROWS",label,len(out))
    return out

def parts(row):
    try:
        ps=[float(x["totalPrice"]) for x in row.get("persons") or []]
        total=float(row["price"])
        return ps,total
    except:return [],None

def main():
    raw=val((gql(QS,op="R").get("data") or {}).get("bluevendoSearch")) or {}
    items=((raw.get("items") or {}).get("item") or []) if isinstance(raw,dict) else []
    if isinstance(items,dict):items=[items]
    bases={}
    for item in items:
        ats=(item.get("availabletransporttypes") or {}).get("availabletransporttype") or []
        if isinstance(ats,dict):ats=[ats]
        for a in ats:
            if str(a.get("transporttypeid"))=="1" and a.get("offerid"):
                bases[str(a["offerid"])]={"hotel":item.get("hotelname"),"hotelid":item.get("hotelid"),
                  "standard":item.get("standard"),"rateaverage":item.get("rateaverage")}
    print("PRIMAMATRIX_FLIGHT_OFFERS",len(bases))
    today=datetime.now(TZ).date()
    candidates=[]
    for oid,base in bases.items():
        ov=val((gql(QO,{"id":oid},"O").get("data") or {}).get("bluevendoOffer")) or {}
        ts=((ov.get("trips") or {}).get("trip") or []) if isinstance(ov,dict) else []
        if isinstance(ts,dict):ts=[ts]
        live=[]
        for t in ts:
            try:
                start=datetime.strptime(str(t.get("start")),"%Y-%m-%d").date()
                nights=int(t.get("length") or 0);mr=int(t.get("maxroom") or 0)
            except:continue
            if start<today or (start-today).days>90:continue
            if str(t.get("transporttypeid"))!="1" or str(t.get("onrequest")).lower() not in ("false","f","0") or mr<1:continue
            if not 5<=nights<=8:continue
            live.append(t)
        # sample multiple distinct room/meal/airport combinations, not merely mintrip
        uniq=[];seen=set()
        for t in live:
            k=(str(t.get("roomid")),str(t.get("maintenanceid")),str(t.get("departurecityname")))
            if k in seen:continue
            seen.add(k);uniq.append(t)
            if len(uniq)>=10:break
        if not uniq:continue
        fam=calc_batch(uniq,[18,18,5,7],"FAMILY")
        adults=calc_batch(uniq,[18,18],"ADULTS")
        for t in uniq:
            tid=str(t.get("id"));f=fam.get(tid);a=adults.get(tid)
            fp,ft=parts(f or {});ap,at=parts(a or {})
            rec={**base,"offerid":oid,"tripid":tid,"start":t.get("start"),"end":t.get("end"),
                 "nights":int(t.get("length") or 0),"airport":t.get("departurecityname"),
                 "airport_code":t.get("departuredeparturenodecode"),"meal":t.get("maintenancestandardname") or t.get("maintenancename"),
                 "roomid":t.get("roomid"),"maxroom":int(t.get("maxroom") or 0),
                 "family_people":fp,"family_total":ft,"adults_people":ap,"adults_total":at}
            print("PRIMAMATRIX_ROW",json.dumps(rec,ensure_ascii=False))
            if len(fp)==4 and len(ap)==2 and ft and at and abs(sum(fp)-ft)<.01 and abs(sum(ap)-at)<.01 and ft>at>0:
                candidates.append((rec,t))
                print("PRIMAMATRIX_PROOF",json.dumps(rec,ensure_ascii=False))
        if len(candidates)>=3:break

    verified=[]
    for rec,t in candidates[:3]:
        # independent second read + second family calculation
        ov={}
        for reattempt in range(3):
            ov=val((gql(QO,{"id":rec["offerid"]},"O2").get("data") or {}).get("bluevendoOffer")) or {}
            if isinstance(ov,dict) and ((ov.get("trips") or {}).get("trip") if isinstance(ov.get("trips"),dict) else None):
                break
            print("PRIMAMATRIX_OFFER_RECHECK_RETRY",rec["offerid"],reattempt+1,type(ov).__name__)
            if reattempt<2: time.sleep(2*(reattempt+1))
        ts=((ov.get("trips") or {}).get("trip") or []) if isinstance(ov,dict) else []
        if isinstance(ts,dict):ts=[ts]
        fresh=next((x for x in ts if str(x.get("id"))==rec["tripid"]),None)
        if not fresh:continue
        try:
            if str(fresh.get("onrequest")).lower() not in ("false","f","0") or int(fresh.get("maxroom") or 0)<1:continue
        except:continue
        ff=calc_batch([fresh],[18,18,5,7],"FAMILY_RECHECK").get(rec["tripid"])
        pp,tt=parts(ff or {})
        if len(pp)==4 and tt is not None and abs(tt-rec["family_total"])<.01:
            rec["recheck_total"]=tt;rec["recheck_people"]=pp;verified.append(rec)
            print("PRIMAMATRIX_RECHECK",json.dumps(rec,ensure_ascii=False))
    print("PRIMAMATRIX_EXACT_PARTY",json.dumps({"adults":2,"children":2,"ages":[5,7]}))
    print("PRIMAMATRIX_VERIFIED_COUNT",len(verified))
    print("PRIMAMATRIX_VERIFIED",bool(verified))
    if not verified: raise SystemExit("FAIL_CLOSED: no live exact-family flight package found")

if __name__=="__main__":main()
