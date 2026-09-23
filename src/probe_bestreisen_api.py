import json, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

API="https://bestreisengroup.pl/api/bv"
TZ=ZoneInfo("Europe/Warsaw")
H={"User-Agent":"Mozilla/5.0","Accept":"application/json","Content-Type":"application/json","Referer":"https://bestreisengroup.pl/wyniki-wyszukiwania"}

def post(method,params,label):
    r=requests.post(API,json={"method":method,"params":params},headers=H,timeout=40)
    print("BESTAPI_STATUS",label,method,r.status_code,len(r.content))
    print("BESTAPI_HEAD",label,r.text[:12000].replace("\n"," "))
    r.raise_for_status()
    try:return r.json()
    except:return None

def walk(x,path="",depth=0,out=None):
    if out is None: out=[]
    if depth>8 or len(out)>250:return out
    if isinstance(x,dict):
        interesting={}
        for k,v in x.items():
            kl=k.lower()
            if any(t in kl for t in ["trip","price","total","adult","child","infant","age","avail","departure","arrival","room","meal","maintenance","hotel","start","end"]):
                interesting[k]=v
        if interesting:
            out.append((path,interesting))
        for k,v in x.items():walk(v,f"{path}.{k}" if path else k,depth+1,out)
    elif isinstance(x,list):
        for i,v in enumerate(x[:80]):walk(v,f"{path}[{i}]",depth+1,out)
    return out

def main():
    today=datetime.now(TZ).date()
    base={
      "startdate":(today+timedelta(days=1)).isoformat(),
      "enddate":(today+timedelta(days=3)).isoformat(),
      "transporttypeid":1,"length":"5-8","pricestart":0,"priceend":50000,
      "numOnPage":30
    }
    family=dict(base);family["searchrooms"]=[{"adults":2,"infants":2,"childage":[5,7]}]
    adults=dict(base);adults["searchrooms"]=[{"adults":2,"infants":0,"childage":[]}]
    f=post("search-search",family,"FAMILY")
    a=post("search-search",adults,"ADULTS")
    for label,obj in [("FAMILY",f),("ADULTS",a)]:
        rows=walk(obj)
        print("BESTAPI_SIGNAL_COUNT",label,len(rows))
        for p,v in rows[:120]:print("BESTAPI_SIGNAL",label,p,json.dumps(v,ensure_ascii=False)[:2800])
    # Known live trip from current Best Reisen detail page; use only as price-semantics proof.
    trip={"tripid":"789655192","departureid":"2039328","arrivalid":"2039305"}
    for label,ages in [("FAMILY",[20,20,5,7]),("ADULTS",[20,20])]:
        conf={"room":[{"roomid":"990207","person":[{"age":str(age),"birthdate":""} for age in ages]}]}
        obj=post("trip-calculation",{**trip,"configuration":conf},label+"_CALC")
        for p,v in walk(obj)[:120]:print("BESTAPI_CALC_SIGNAL",label,p,json.dumps(v,ensure_ascii=False)[:2800])
    print("BESTAPI_EXACT_PARTY",{"adults":2,"children":2,"ages":[5,7]})
if __name__=="__main__":main()
