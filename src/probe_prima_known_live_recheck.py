import json,time,requests

GQL="https://app.primaholiday.pl/graphql"
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
   "Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}
OFFER_ID="290579"
TRIP_ID="389352759"
QO="query O($id:ID!){bluevendoOffer(id:$id)}"
QC="""query C($persons:[PersonsGroupInput!]!,$trips:[TripInput!]!){
 bluevendoFastCalculation(persons:$persons,trips:$trips){trips{price tripId lowestPrice persons{totalPrice}}}
}"""

def gql(q,v,op):
    last=None
    for a in range(4):
        try:
            r=requests.post(GQL,json={"operationName":op,"variables":v,"query":q},headers=H,timeout=45)
            print("PRIMAKNOWN_STATUS",op,a+1,r.status_code,len(r.content))
            r.raise_for_status();d=r.json()
            if d.get("errors"):
                print("PRIMAKNOWN_ERRORS",op,json.dumps(d["errors"],ensure_ascii=False)[:1200]);last=RuntimeError("graphql")
            else:return d
        except Exception as e:
            last=e;print("PRIMAKNOWN_RETRY",op,a+1,type(e).__name__,str(e)[:200])
        if a<3:time.sleep(2*(a+1))
    raise last or RuntimeError("request failed")

def val(v):
    if isinstance(v,str):
        try:return json.loads(v)
        except:return v
    return v

def get_trip(op):
    d=gql(QO,{"id":OFFER_ID},op)
    ov=val((d.get("data") or {}).get("bluevendoOffer")) or {}
    ts=((ov.get("trips") or {}).get("trip") or []) if isinstance(ov,dict) else []
    if isinstance(ts,dict):ts=[ts]
    t=next((x for x in ts if str(x.get("id"))==TRIP_ID),None)
    print("PRIMAKNOWN_TRIP",op,json.dumps(t,ensure_ascii=False)[:7000] if t else "null")
    return t

def calc(t,ages,op):
    v={"persons":[{"person":[{"age":a} for a in ages]}],
       "trips":[{"tripid":int(t["id"]),"departureid":int(t["departureid"]),"arrivalid":int(t["arrivalid"])}]}
    d=gql(QC,v,op)
    rows=(((d.get("data") or {}).get("bluevendoFastCalculation") or {}).get("trips") or [])
    if isinstance(rows,dict):rows=[rows]
    row=next((x for x in rows if str(x.get("tripId"))==TRIP_ID),None)
    print("PRIMAKNOWN_CALC",op,json.dumps(row,ensure_ascii=False))
    return row

def proof(row,n):
    try:
        people=[float(x["totalPrice"]) for x in row.get("persons") or []]
        total=float(row["price"])
    except:return None
    if len(people)!=n or abs(sum(people)-total)>.01:return None
    return people,total

def live(t):
    try:return str(t.get("onrequest")).lower() in ("false","f","0") and int(t.get("maxroom") or 0)>0
    except:return False

def main():
    t1=get_trip("O1")
    if not t1 or not live(t1):raise SystemExit("FAIL_CLOSED: first offer read not live")
    f1=proof(calc(t1,[18,18,5,7],"F1") or {},4)
    a1=proof(calc(t1,[18,18],"A1") or {},2)
    if not f1 or not a1 or not f1[1]>a1[1]>0:raise SystemExit("FAIL_CLOSED: party-sensitive family total missing")
    time.sleep(4)
    t2=get_trip("O2")
    if not t2 or not live(t2):raise SystemExit("FAIL_CLOSED: second offer read not live")
    # immutable package identity must still match
    keys=["id","offerid","hotelid","start","end","roomid","maintenanceid","departureid","arrivalid","departurecityname"]
    if any(str(t1.get(k))!=str(t2.get(k)) for k in keys):raise SystemExit("FAIL_CLOSED: package identity drift")
    f2=proof(calc(t2,[18,18,5,7],"F2") or {},4)
    if not f2 or abs(f2[1]-f1[1])>.01:raise SystemExit("FAIL_CLOSED: family price changed on recheck")
    out={"offerid":OFFER_ID,"tripid":TRIP_ID,"exact_party":{"adults":2,"children":2,"ages":[5,7]},
         "family_people":f1[0],"family_total":f1[1],"adults_people":a1[0],"adults_total":a1[1],
         "recheck_family_people":f2[0],"recheck_total":f2[1],
         "live_first":{"onrequest":t1.get("onrequest"),"maxroom":t1.get("maxroom")},
         "live_second":{"onrequest":t2.get("onrequest"),"maxroom":t2.get("maxroom")},
         "start":t1.get("start"),"end":t1.get("end"),"airport":t1.get("departurecityname"),
         "meal":t1.get("maintenancestandardname") or t1.get("maintenancename"),"roomid":t1.get("roomid")}
    print("PRIMAKNOWN_PROOF",json.dumps(out,ensure_ascii=False))
    print("PRIMAKNOWN_VERIFIED",True)

if __name__=="__main__":main()
