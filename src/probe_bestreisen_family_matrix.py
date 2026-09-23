import json,requests
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

API="https://bestreisengroup.pl/api/bv"
BASE="https://bestreisengroup.pl/"
TZ=ZoneInfo("Europe/Warsaw")
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
   "Accept":"application/json,text/plain,*/*","Content-Type":"application/json","Referer":BASE}

def post(params,label):
    r=requests.post(API,json={"method":"search-search","params":params},headers=H,timeout=55)
    print("BESTMATRIX_STATUS",label,r.status_code,len(r.content))
    print("BESTMATRIX_HEAD",label,r.text[:4000].replace("\n"," "))
    r.raise_for_status()
    return r.json()

def rows(data):
    try:
        x=data["data"]["response"]["items"]["item"]
    except:return []
    if isinstance(x,dict):x=[x]
    return [v for v in x if isinstance(v,dict)] if isinstance(x,list) else []

def trip(x):
    return x.get("mintrip") if isinstance(x.get("mintrip"),dict) else {}

def pick(x,*ks):
    for k in ks:
        if x.get(k) not in (None,""):return x.get(k)
    return None

def num(v):
    try:return float(str(v).replace(",","."))
    except:return None

def stable(x):
    t=trip(x)
    return (
      str(pick(x,"hotelid","hotelId") or ""),
      str(pick(t,"roomid","roomId") or pick(x,"roomid","roomId") or ""),
      str(pick(t,"startdate","startDate") or ""),
      str(pick(t,"enddate","endDate") or ""),
      str(pick(x,"maintenanceid","maintenanceId") or pick(t,"maintenance","maintenanceid") or ""),
      str(pick(t,"departurecityid","departureCityId") or pick(t,"departurecode","departureCode") or ""),
      str(pick(x,"transporttypeid","transportTypeId") or ((x.get("availabletransporttypes") or {}).get("availabletransporttype") or {}).get("transporttypeid") if isinstance((x.get("availabletransporttypes") or {}).get("availabletransporttype"),dict) else "1"),
    )

def live(x):
    t=trip(x)
    if str(t.get("onrequest","")).lower() not in ("f","false","0"):return False
    av=x.get("availabletransporttypes")
    return bool(av)

def main():
    today=datetime.now(TZ).date()
    base={
      "startdate":(today+timedelta(days=1)).isoformat(),
      "enddate":(today+timedelta(days=90)).isoformat(),
      "transporttypeid":1,"length":"5-8","pricestart":100,"priceend":25000000,
      "page":1,"numOnPage":100,"ordername":"price","orderdirection":"asc","hoteltypeid":""
    }
    variants=[
      ("FLAT_FAMILY",{**base,"adults":2,"infants":"5,7"}),
      ("NESTED_FAMILY",{**base,"searchrooms":[{"adults":2,"infants":2,"childage":[5,7]}]}),
      ("ADULTS",{**base,"adults":2})
    ]
    sets={}
    for label,p in variants:
        data=post(p,label)
        rr=rows(data);sets[label]=rr
        print("BESTMATRIX_ROWS",label,len(rr))
        for x in rr[:8]:
            t=trip(x)
            print("BESTMATRIX_ROW",label,json.dumps({
              "hotelid":x.get("hotelid"),"hotel":x.get("hotelname"),"offerid":x.get("offerid"),
              "total":pick(x,"customertotalprice","totalprice","totalPrice"),
              "base":pick(x,"customerbaseprice","customerprice","minbaseprice"),
              "currency":pick(x,"totalPriceCurrency","customercurrency"),
              "maintenance":pick(x,"maintenancestandardname","maintenancename"),
              "standard":x.get("standard"),"rateaverage":x.get("rateaverage"),
              "mintrip":t
            },ensure_ascii=False)[:10000])

    adults={stable(x):x for x in sets.get("ADULTS",[])}
    proofs=[]
    for family_label in ("FLAT_FAMILY","NESTED_FAMILY"):
        for f in sets.get(family_label,[]):
            a=adults.get(stable(f))
            if not a or not live(f):continue
            ft=num(pick(f,"customertotalprice","totalprice","totalPrice"))
            at=num(pick(a,"customertotalprice","totalprice","totalPrice"))
            if ft is None or at is None or not ft>at>0:continue
            t=trip(f)
            rec={"schema":family_label,"key":stable(f),"hotel":f.get("hotelname"),"offerid":f.get("offerid"),
                 "family_total":ft,"adults_total":at,"delta":ft-at,
                 "start":t.get("startdate"),"end":t.get("enddate"),"roomid":t.get("roomid"),
                 "airport":t.get("departurecityname"),"airport_code":t.get("departurecode"),
                 "meal":pick(f,"maintenancestandardname","maintenancename"),"onrequest":t.get("onrequest")}
            proofs.append(rec)
            print("BESTMATRIX_PROOF",json.dumps(rec,ensure_ascii=False))
            if len(proofs)>=8:break
        if proofs:break
    print("BESTMATRIX_EXACT_REQUEST",json.dumps({"adults":2,"children":2,"ages":[5,7]}))
    print("BESTMATRIX_PARTY_SENSITIVE",len(proofs))
    print("BESTMATRIX_VERIFIED",bool(proofs))
    if not proofs: raise SystemExit("FAIL_CLOSED: no party-sensitive live Best Reisen family total")

if __name__=="__main__":main()
