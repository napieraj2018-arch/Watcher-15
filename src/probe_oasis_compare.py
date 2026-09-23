import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

API="https://oasis.pl/api-bv/search-search"
TZ=ZoneInfo("Europe/Warsaw")
HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*","Content-Type":"application/json","Referer":"https://oasis.pl/"}

def payload(family):
    today=datetime.now(TZ).date()
    p={
      "transporttypeid":"1","adults":"2","length":"0","priceend":"25000000",
      "ordername":"price","hoteltypeid":"","startdate":today.isoformat(),
      "enddate":(today+timedelta(days=90)).isoformat(),"page":1,"numOnPage":"100",
      "pricestart":"100","orderdirection":"asc"
    }
    if family:p["infants"]="5,7"
    return p

def items(data):
    if not isinstance(data,dict):return []
    d=data.get("data")
    if not isinstance(d,dict):return []
    x=d.get("items")
    return x if isinstance(x,list) else []

def num(v):
    try:return float(v)
    except:return None

def stable(x):
    trip=x.get("mintrip") or {}
    return (
      str(x.get("hotelid") or ""),
      str(trip.get("roomid") or ""),
      str(trip.get("startdate") or ""),
      str(trip.get("enddate") or ""),
      str(x.get("maintenanceid") or ""),
      str(x.get("transporttypeid") or ""),
    )

def compact(x):
    trip=x.get("mintrip") or {}
    return {
      "offerid":x.get("offerid"),"hotelid":x.get("hotelid"),"hotel":x.get("hotelname"),
      "roomid":trip.get("roomid"),"room":x.get("roomname"),
      "start":trip.get("startdate"),"end":trip.get("enddate"),"staylength":trip.get("staylength"),
      "meal":x.get("maintenancename") or x.get("maintenancestandardname"),
      "transport":x.get("transporttypename"),"offercode":trip.get("offercode"),
      "totalprice":num(x.get("totalprice")),"customertotalprice":num(x.get("customertotalprice")),
      "customerbaseprice":num(x.get("customerbaseprice")),
      "currency":x.get("totalPriceCurrency") or x.get("customercurrency"),
    }

def get(label,family):
    r=requests.post(API,json=payload(family),headers=HEADERS,timeout=40)
    print("OASISCMP_STATUS",label,r.status_code,len(r.content))
    print("OASISCMP_SENT",label,json.dumps(payload(family),ensure_ascii=False,sort_keys=True))
    r.raise_for_status()
    data=r.json()
    arr=items(data)
    print("OASISCMP_COUNT",label,len(arr))
    for x in arr[:6]:print("OASISCMP_ROW",label,json.dumps(compact(x),ensure_ascii=False))
    return arr

def main():
    fam=get("FAMILY",True)
    ad=get("ADULTS",False)
    by_offer={str(x.get("offerid")):x for x in ad if x.get("offerid") is not None}
    by_key={stable(x):x for x in ad}
    proofs=[]
    same=0
    for f in fam:
        a=by_offer.get(str(f.get("offerid"))) or by_key.get(stable(f))
        if not a:continue
        same+=1
        fc=compact(f); ac=compact(a)
        ft=fc["customertotalprice"] if fc["customertotalprice"] is not None else fc["totalprice"]
        at=ac["customertotalprice"] if ac["customertotalprice"] is not None else ac["totalprice"]
        if ft is None or at is None:continue
        rec={"key":stable(f),"family":fc,"adults":ac,"family_total":ft,"adults_total":at,"delta":ft-at}
        print("OASISCMP_MATCH",json.dumps(rec,ensure_ascii=False))
        if ft!=at and ft>at:
            proofs.append(rec)
    print("OASISCMP_COMMON",same)
    print("OASISCMP_PARTY_SENSITIVE",len(proofs))
    for p in proofs[:12]:print("OASISCMP_PROOF",json.dumps(p,ensure_ascii=False))
    print("OASISCMP_FAMILY_TOTAL_VERIFIED",bool(proofs))

if __name__=="__main__":main()
