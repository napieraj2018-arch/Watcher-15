import json,re,requests
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

API="https://www.katowice-travel.pl/api/search_offers.php"
BASE="https://www.katowice-travel.pl/"
TZ=ZoneInfo("Europe/Warsaw")
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept":"application/json,text/plain,*/*","Referer":BASE,"Content-Type":"application/json"}

def payload(family, child_ages="5,7"):
    today=datetime.now(TZ).date()
    return {
      "type":"tours","destinationId":11,"favoritesOnly":False,
      "dateFrom":(today+timedelta(days=1)).isoformat(),
      "dateTo":(today+timedelta(days=3)).isoformat(),
      "stars":"any","adults":2,"children":2 if family else 0,
      "childAges":child_ages if family else "",
      "meal":"","limit":500,"depCode":"WAW,WMI,RDO","nights":"5:8"
    }

def scalar(v):
    return isinstance(v,(str,int,float,bool)) or v is None

def signals(obj,path="",out=None,depth=0):
    if out is None:out=[]
    if depth>9 or len(out)>900:return out
    if isinstance(obj,dict):
        sig={}
        for k,v in obj.items():
            lk=k.lower()
            if scalar(v) and any(t in lk for t in ["price","total","adult","child","age","person","hotel","offer","room","meal","board","star","rating","review","opini","avail","depart","airport","date","night","duration","from","code","id"]):
                sig[k]=v
        if sig:out.append((path,sig,obj))
        for k,v in obj.items():signals(v,f"{path}.{k}" if path else k,out,depth+1)
    elif isinstance(obj,list):
        for i,v in enumerate(obj[:250]):signals(v,f"{path}[{i}]",out,depth+1)
    return out

def fetch(label,p):
    r=requests.post(API,json=p,headers=H,timeout=45)
    print("TANIEAPI_STATUS",label,r.status_code,len(r.content),r.headers.get("content-type"))
    print("TANIEAPI_PAYLOAD",label,json.dumps(p,ensure_ascii=False,sort_keys=True))
    print("TANIEAPI_HEAD",label,r.text[:6000].replace("\n"," "))
    r.raise_for_status()
    try:return r.json()
    except Exception as e:
        print("TANIEAPI_JSON_ERR",label,type(e).__name__,str(e)[:180]);return None

def key_from(rec):
    # Build a deliberately conservative package identity from common provider fields.
    def pick(*names):
        for n in names:
            if n in rec and rec[n] not in (None,""):return str(rec[n])
        return ""
    return (
      pick("hotelId","hotel_id","hotelCode","hotel_code","idHotel","hotelXCode","hotel_xcode"),
      pick("dateFrom","departureDate","startDate","date_from","start"),
      pick("nights","duration","stayLength","stay_length"),
      pick("roomId","room_id","roomCode","room_code"),
      pick("mealId","meal_id","mealCode","meal_code","boardCode","board_code"),
      pick("departureCode","depCode","airportCode","airport_code","departureAirport")
    )

def price_from(rec):
    vals=[]
    for k,v in rec.items():
        lk=k.lower()
        if any(t in lk for t in ["totalprice","total_price","price_total","finalprice","final_price","total","price"]):
            try:
                if isinstance(v,(int,float)):x=float(v)
                else:
                    s=re.sub(r"[^0-9,.]","",str(v)).replace(",",".")
                    x=float(s) if s else None
                if x and x>100:vals.append((k,x))
            except:pass
    # Prefer explicit total/final fields over generic price.
    vals.sort(key=lambda kv:(0 if any(t in kv[0].lower() for t in ["total","final"]) else 1,-kv[1]))
    return vals[0] if vals else (None,None)

def main():
    # First inspect the site's JS to determine canonical childAges serialization.
    try:
        js=requests.get(BASE+"js/search-panel.js?v=20260902-1",headers={"User-Agent":H["User-Agent"],"Referer":BASE},timeout=25).text
        for term in ["childAges","children","age"]:
            lo=js.lower();p=0;n=0
            while n<5:
                i=lo.find(term.lower(),p)
                if i<0:break
                sn=" ".join(js[max(0,i-900):i+1800].split())
                print("TANIEAPI_JS",term,sn[:4200])
                p=i+len(term);n+=1
    except Exception as e: print("TANIEAPI_JS_ERR",type(e).__name__,str(e)[:180])

    family_obj=None
    used=None
    for ages in ["5,7","5|7","5;7","[5,7]"]:
        obj=fetch("FAMILY_"+ages,payload(True,ages))
        sig=signals(obj) if obj is not None else []
        print("TANIEAPI_SIGNAL_COUNT","FAMILY_"+ages,len(sig))
        for path,s,rec in sig[:80]:
            print("TANIEAPI_SIGNAL","FAMILY_"+ages,path,json.dumps(s,ensure_ascii=False)[:2600])
        # Keep first response with non-empty offer-like signal set.
        if obj is not None and len(sig)>10 and family_obj is None:
            family_obj=obj;used=ages

    adults_obj=fetch("ADULTS",payload(False))
    for path,s,rec in signals(adults_obj)[:80]:
        print("TANIEAPI_SIGNAL","ADULTS",path,json.dumps(s,ensure_ascii=False)[:2600])

    if family_obj is None:
        print("TANIEAPI_EXACT_FAMILY_RESPONSE_FOUND",False)
        return

    famrecs=[]
    for path,s,rec in signals(family_obj):
        if isinstance(rec,dict):
            pk,pv=price_from(rec)
            if pv:
                famrecs.append((path,rec,pk,pv,key_from(rec)))
    adrecs=[]
    for path,s,rec in signals(adults_obj):
        if isinstance(rec,dict):
            pk,pv=price_from(rec)
            if pv:
                adrecs.append((path,rec,pk,pv,key_from(rec)))

    amap={}
    for path,rec,pk,pv,k in adrecs:
        if any(k):amap.setdefault(k,(path,rec,pk,pv))
    proofs=[]
    for path,rec,pk,pv,k in famrecs:
        if not any(k) or k not in amap:continue
        apath,arec,apk,apv=amap[k]
        if pv!=apv:
            proofs.append({"key":k,"family_total":pv,"adult_total":apv,"family_price_field":pk,"adult_price_field":apk,"family_path":path,"adult_path":apath})
    print("TANIEAPI_CANONICAL_CHILD_AGES",used)
    print("TANIEAPI_FAMILY_PRICE_RECORDS",len(famrecs))
    print("TANIEAPI_ADULT_PRICE_RECORDS",len(adrecs))
    print("TANIEAPI_PARTY_SENSITIVE",len(proofs))
    for p in proofs[:25]:print("TANIEAPI_PROOF",json.dumps(p,ensure_ascii=False))
    print("TANIEAPI_FAMILY_TOTAL_VERIFIED",bool(proofs))

if __name__=="__main__":main()
