import json,re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import requests

API="https://oasis.pl/api-bv/search-search"
TZ=ZoneInfo("Europe/Warsaw")
HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*","Content-Type":"application/json","Referer":"https://oasis.pl/"}

def payload(family=True):
    today=datetime.now(TZ).date()
    p={
      "transporttypeid":"1","adults":"2","length":"0","priceend":"25000000",
      "ordername":"price","hoteltypeid":"","startdate":today.isoformat(),
      "enddate":(today+timedelta(days=90)).isoformat(),"page":1,"numOnPage":"30",
      "pricestart":"100","orderdirection":"asc"
    }
    if family:p["infants"]="5,7"
    return p

def compact(v):
    return re.sub(r"\s+"," ",str(v or "")).strip()

def scan(obj,label,path="",depth=0,state=None):
    if state is None:state={"n":0}
    if depth>7 or state["n"]>=220:return
    if isinstance(obj,dict):
        keys=list(obj.keys())
        if depth<=3:print("OASIS_API_KEYS",label,path,keys[:80])
        for k,v in obj.items():
            kl=str(k).lower()
            pp=f"{path}.{k}" if path else str(k)
            if any(x in kl for x in ["price","cost","total","hotel","offer","avail","meal","board","adult","infant","child","age","date","start","end","length","night","airport","flight","transport","room","rating","review"]):
                if isinstance(v,(str,int,float,bool)) or v is None:
                    print("OASIS_API_FIELD",label,pp,repr(v)[:900]);state["n"]+=1
            scan(v,label,pp,depth+1,state)
    elif isinstance(obj,list):
        if depth<=3:print("OASIS_API_LIST",label,path,len(obj))
        for i,v in enumerate(obj[:8]):scan(v,label,f"{path}[{i}]",depth+1,state)

def request(label,p):
    r=requests.post(API,json=p,headers=HEADERS,timeout=40)
    print("OASIS_API_STATUS",label,r.status_code,r.headers.get("content-type"),len(r.content))
    print("OASIS_API_SENT",label,json.dumps(p,ensure_ascii=False,sort_keys=True))
    r.raise_for_status()
    try:
        data=r.json()
        print("OASIS_API_TYPE",label,type(data).__name__)
        scan(data,label,state={"n":0})
        return data
    except Exception:
        print("OASIS_API_TEXT",label,compact(r.text)[:10000])
        return None

def main():
    fam=request("FAMILY",payload(True))
    ad=request("ADULTS",payload(False))
    # Preserve a compact top-level sample for the next parser iteration.
    for label,data in [("FAMILY",fam),("ADULTS",ad)]:
        if isinstance(data,list):
            print("OASIS_API_SAMPLE",label,json.dumps(data[:2],ensure_ascii=False)[:16000])
        elif isinstance(data,dict):
            print("OASIS_API_SAMPLE",label,json.dumps(data,ensure_ascii=False)[:16000])

if __name__=="__main__":main()
