import json,time,requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

HOME="https://www.primaholiday.pl/"
GQL="https://app.primaholiday.pl/graphql"

def post(sess,headers,query,variables,label):
    r=sess.post(GQL,json={"operationName":label,"query":query,"variables":variables},headers=headers,timeout=40)
    print("PRIMALIVE_STATUS",label,r.status_code,len(r.content))
    print("PRIMALIVE_BODY",label,r.text[:30000].replace("\n"," "))
    try:return r.json()
    except:return {}

def walk(obj,path="",depth=0,out=None):
    if out is None: out=[]
    if depth>10 or len(out)>500:return out
    if isinstance(obj,dict):
        sig={}
        for k,v in obj.items():
            kl=k.lower()
            if any(x in kl for x in ["offer","trip","price","total","date","airport","departure","arrival","hotel","property","room","meal","maintenance","adult","child","age","avail","rating","review","period"]):
                sig[k]=v
        if sig:out.append((path,sig))
        for k,v in obj.items():walk(v,f"{path}.{k}" if path else k,depth+1,out)
    elif isinstance(obj,list):
        for i,v in enumerate(obj[:120]):walk(v,f"{path}[{i}]",depth+1,out)
    return out

def collect_trips(driver):
    out=[];seen=set()
    for row in driver.get_log("performance"):
        try:
            msg=json.loads(row["message"])["message"]
            if msg.get("method")!="Network.requestWillBeSent":continue
            req=msg["params"]["request"]
            if req.get("url")!=GQL:continue
            raw=req.get("postData") or ""
            if "BluevendoFastCalculation" not in raw:continue
            p=json.loads(raw)
            for t in (p.get("variables") or {}).get("trips") or []:
                tid=t.get("tripid")
                if tid is None or str(tid) in seen:continue
                seen.add(str(tid));out.append(t)
        except:pass
    return out

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3000","--lang=pl-PL"]:o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(HOME);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(9)
        trips=collect_trips(d)
        print("PRIMALIVE_TRIP_COUNT",len(trips))
        print("PRIMALIVE_TRIPS",json.dumps(trips[:30],ensure_ascii=False))
        sess=requests.Session()
        for c in d.get_cookies():sess.cookies.set(c["name"],c["value"])
        headers={"User-Agent":d.execute_script("return navigator.userAgent"),"Origin":HOME.rstrip("/"),"Referer":HOME,"Content-Type":"application/json"}

        search_q="query BluevendoSearchProbe { bluevendoSearch }"
        search=post(sess,headers,search_q,{},"BluevendoSearchProbe")
        for p,v in walk(search)[:250]:
            print("PRIMALIVE_SEARCH_SIGNAL",p,json.dumps(v,ensure_ascii=False)[:3600])

        offer_q="query BluevendoOfferProbe($id: ID!) { bluevendoOffer(id:$id) }"
        for t in trips[:8]:
            tid=str(t.get("tripid"))
            data=post(sess,headers,offer_q,{"id":tid},"BluevendoOfferProbe")
            for p,v in walk(data)[:120]:
                print("PRIMALIVE_OFFER_SIGNAL",tid,p,json.dumps(v,ensure_ascii=False)[:3600])

        schema_q='''query PrimaTypes {
          room: __type(name:"RoomConfiguration") { inputFields { name type { kind name ofType { kind name ofType { kind name } } } } }
          trip: __type(name:"TripCalculation") { fields { name type { kind name ofType { kind name ofType { kind name } } } } }
          persons: __type(name:"PersonsGroupInput") { inputFields { name type { kind name ofType { kind name ofType { kind name } } } } }
        }'''
        types=post(sess,headers,schema_q,{},"PrimaTypes")
        print("PRIMALIVE_TYPES",json.dumps(types,ensure_ascii=False)[:30000])
    finally:d.quit()
if __name__=="__main__":main()
