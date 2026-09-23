import json,time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys

URL="https://oasis.pl/"
API="https://oasis.pl/api-bv/search-search"

def compact(s): return " ".join((s or "").split())

def exact_family_session():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3000","--lang=pl-PL"]:
        o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(4)
    for b in d.find_elements(By.TAG_NAME,"button"):
        try:
            if b.is_displayed() and "Zaakceptuj" in compact(b.text):
                d.execute_script("arguments[0].click()",b);time.sleep(.4);break
        except: pass
    root=[x for x in d.find_elements(By.CSS_SELECTOR,".participants") if x.is_displayed()][0]
    d.execute_script("arguments[0].click()",root.find_element(By.CSS_SELECTOR,".mainInput"));time.sleep(.8)
    root=[x for x in d.find_elements(By.CSS_SELECTOR,".participants") if x.is_displayed()][0]
    child=None
    for row in root.find_elements(By.CSS_SELECTOR,".inputWrapper"):
        try:
            if compact(row.find_element(By.CSS_SELECTOR,".title").text)=="Dzieci": child=row;break
        except: pass
    if child is None: raise RuntimeError("Oasis child row missing")
    plus=child.find_elements(By.CSS_SELECTOR,"button.inputButton")[-1]
    for _ in range(2): d.execute_script("arguments[0].click()",plus);time.sleep(.6)
    inputs=[x for x in root.find_elements(By.CSS_SELECTOR,"input.ageInput") if x.is_displayed()]
    if len(inputs)!=2: raise RuntimeError("Oasis exact two child DOB fields missing")
    for e,raw,want in zip(inputs,["01012021","01012019"],["01.01.2021","01.01.2019"]):
        e.click();e.send_keys(Keys.CONTROL,"a");e.send_keys(Keys.BACKSPACE);e.send_keys(raw);e.send_keys(Keys.TAB);time.sleep(.5)
        if e.get_attribute("value")!=want: raise RuntimeError("Oasis DOB did not stick")
    root=[x for x in d.find_elements(By.CSS_SELECTOR,".participants") if x.is_displayed()][0]
    confirm=root.find_element(By.CSS_SELECTOR,"button.confirmButton")
    if confirm.get_attribute("disabled") is not None: raise RuntimeError("Oasis party confirm disabled")
    d.execute_script("arguments[0].click()",confirm);time.sleep(1)
    label=compact(d.find_element(By.CSS_SELECTOR,".participants .mainInput").text)
    print("OASISCMP_PARTY_LABEL",label)
    if "2 dorosłych" not in label or "2 dzieci" not in label: raise RuntimeError("Oasis UI party not exact 2+2")
    d.get_log("performance")
    btn=[x for x in d.find_elements(By.CSS_SELECTOR,"button.searchButton") if x.is_displayed()]
    if not btn: raise RuntimeError("Oasis search button missing")
    d.execute_script("arguments[0].click()",btn[0]);time.sleep(8)
    family_payload=None
    for row in d.get_log("performance"):
        try:
            m=json.loads(row["message"])["message"]
            if m.get("method")!="Network.requestWillBeSent": continue
            req=m["params"]["request"]
            if "/api-bv/search-search" not in req.get("url",""): continue
            p=json.loads(req.get("postData") or "{}")
            if str(p.get("adults"))=="2" and str(p.get("infants"))=="5,7":
                family_payload=p;break
        except: pass
    if not family_payload: raise RuntimeError("Oasis exact family API payload not captured")
    print("OASISCMP_CAPTURED",json.dumps(family_payload,ensure_ascii=False,sort_keys=True))
    s=requests.Session()
    for cookie in d.get_cookies(): s.cookies.set(cookie["name"],cookie["value"])
    headers={"User-Agent":d.execute_script("return navigator.userAgent"),"Accept":"application/json,text/plain,*/*","Content-Type":"application/json","Referer":URL}
    return d,s,headers,family_payload

def arr(data):
    if isinstance(data,dict):
        x=data.get("data")
        if isinstance(x,dict):
            for k in ("items","offers","results"):
                if isinstance(x.get(k),list): return x[k]
        for k in ("items","offers","results"):
            if isinstance(data.get(k),list): return data[k]
    if isinstance(data,list): return data
    return []

def n(v):
    try:return float(str(v).replace(",","."))
    except:return None

def pick(x,*names):
    for name in names:
        if name in x and x.get(name) not in (None,""): return x.get(name)
    return None

def trip(x):
    for k in ("mintrip","trip","offer","minTrip"):
        if isinstance(x.get(k),dict): return x[k]
    return {}

def stable(x):
    t=trip(x)
    return (
      str(pick(x,"hotelid","hotelId","hotel_id") or ""),
      str(pick(t,"roomid","roomId","room_id") or pick(x,"roomid","roomId") or ""),
      str(pick(t,"startdate","startDate","datefrom") or pick(x,"startdate","startDate") or ""),
      str(pick(t,"enddate","endDate","dateto") or pick(x,"enddate","endDate") or ""),
      str(pick(x,"maintenanceid","maintenanceId","mealid","mealId") or ""),
      str(pick(x,"transporttypeid","transportTypeId") or "")
    )

def summary(x):
    t=trip(x)
    return {
      "offerid":pick(x,"offerid","offerId","id"),"hotelid":pick(x,"hotelid","hotelId"),
      "hotel":pick(x,"hotelname","hotelName","name"),
      "roomid":pick(t,"roomid","roomId") or pick(x,"roomid","roomId"),
      "start":pick(t,"startdate","startDate") or pick(x,"startdate","startDate"),
      "end":pick(t,"enddate","endDate") or pick(x,"enddate","endDate"),
      "meal":pick(x,"maintenancename","maintenanceName","mealname","mealName"),
      "totalprice":n(pick(x,"totalprice","totalPrice")),
      "customertotalprice":n(pick(x,"customertotalprice","customerTotalPrice")),
      "customerbaseprice":n(pick(x,"customerbaseprice","customerBasePrice"))
    }

def fetch(s,headers,label,p):
    r=s.post(API,json=p,headers=headers,timeout=40)
    print("OASISCMP_STATUS",label,r.status_code,r.headers.get("content-type"),len(r.content))
    print("OASISCMP_BODY",label,compact(r.text)[:2500])
    if r.status_code!=200:return []
    try:data=r.json()
    except:return []
    rows=arr(data)
    print("OASISCMP_COUNT",label,len(rows))
    for x in rows[:6]:
        if isinstance(x,dict): print("OASISCMP_ROW",label,json.dumps(summary(x),ensure_ascii=False))
    return [x for x in rows if isinstance(x,dict)]

def main():
    d=None
    try:
        d,s,h,p=exact_family_session()
        fam=fetch(s,h,"FAMILY",dict(p))
        adultp={k:v for k,v in p.items() if k!="infants"}
        adultp["adults"]=2
        ad=fetch(s,h,"ADULTS",adultp)
        byid={str(pick(x,"offerid","offerId","id")):x for x in ad if pick(x,"offerid","offerId","id") is not None}
        bykey={stable(x):x for x in ad}
        proofs=[];common=0
        for f in fam:
            a=byid.get(str(pick(f,"offerid","offerId","id"))) or bykey.get(stable(f))
            if not a: continue
            common+=1
            fs,as_=summary(f),summary(a)
            ft=fs["customertotalprice"] if fs["customertotalprice"] is not None else fs["totalprice"]
            at=as_["customertotalprice"] if as_["customertotalprice"] is not None else as_["totalprice"]
            if ft is None or at is None: continue
            rec={"key":stable(f),"family":fs,"adults":as_,"family_total":ft,"adults_total":at,"delta":ft-at}
            print("OASISCMP_MATCH",json.dumps(rec,ensure_ascii=False))
            if ft>at: proofs.append(rec)
        print("OASISCMP_COMMON",common)
        print("OASISCMP_PARTY_SENSITIVE",len(proofs))
        for x in proofs[:12]: print("OASISCMP_PROOF",json.dumps(x,ensure_ascii=False))
        print("OASISCMP_FAMILY_TOTAL_VERIFIED",bool(proofs))
    finally:
        if d is not None:d.quit()

if __name__=="__main__":main()
