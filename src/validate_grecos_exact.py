import json
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode, urlsplit, parse_qs
from zoneinfo import ZoneInfo

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

TZ=ZoneInfo("Europe/Warsaw")
BASE="https://www.grecos.pl"
SEARCH=BASE+"/wakacje"
API=BASE+"/api/sitecore/OffersList/LoadMoreOffers"

def compact(s):
    return " ".join((s or "").split())

def age_on(dob, on):
    return on.year-dob.year-((on.month,on.day)<(dob.month,dob.day))

def family_params():
    today=datetime.now(TZ).date()
    dep=today+timedelta(days=1)
    end=today+timedelta(days=60)
    dob5=date(dep.year-5,1,1)
    dob7=date(dep.year-7,1,1)
    assert age_on(dob5,dep)==5 and age_on(dob7,dep)==7
    p={
        "Adults":"2",
        "Children":"2",
        "DurationInterval":"6:9",
        "Child1":dob5.strftime("%Y%m%d"),
        "Child2":dob7.strftime("%Y%m%d"),
        "DateOfDeparture":dep.strftime("%Y%m%d"),
        "DateOfReturn":end.strftime("%Y%m%d"),
        "PriceFrom":"0",
        "PriceTo":"50000",
        "PriceType":"man",
        "OfferType":"L,S",
        "ObjectType":"H,R,AP",
    }
    return dep,dob5,dob7,p

def exact_query(url,p):
    q={k:v[-1] for k,v in parse_qs(urlsplit(url).query,keep_blank_values=True).items()}
    keys=["Adults","Children","Child1","Child2"]
    return all(q.get(k)==p[k] for k in keys)

def print_json_signals(obj,path="",depth=0,count=[0]):
    if depth>6 or count[0]>=160:
        return
    if isinstance(obj,dict):
        for k,v in obj.items():
            kl=k.lower()
            pp=f"{path}.{k}" if path else k
            if any(x in kl for x in ["price","total","adult","child","age","url","offer","hotel","avail","room","meal","board","rating","review"]):
                print("GRECOS_API_FIELD",pp,repr(v)[:2200])
                count[0]+=1
                if count[0]>=160:return
            print_json_signals(v,pp,depth+1,count)
    elif isinstance(obj,list):
        for i,v in enumerate(obj[:15]):
            print_json_signals(v,f"{path}[{i}]",depth+1,count)

def main():
    dep,dob5,dob7,p=family_params()
    print("GRECOS_EXACT_TARGET",{
        "departure":dep.isoformat(),
        "dob5":dob5.isoformat(),"age5":age_on(dob5,dep),
        "dob7":dob7.isoformat(),"age7":age_on(dob7,dep),
        "party":"2+2"
    })

    s=requests.Session()
    s.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*","Referer":SEARCH})
    api_params=p|{"pageFrom":"0","setFilters":"true"}
    r=s.get(API,params=api_params,timeout=35)
    print("GRECOS_API_REQUEST",r.url)
    print("GRECOS_API_STATUS",r.status_code,r.headers.get("content-type"),len(r.content))
    try:
        data=r.json()
        print("GRECOS_API_JSON_TYPE",type(data).__name__)
        print_json_signals(data,count=[0])
        raw=json.dumps(data,ensure_ascii=False)
    except Exception:
        raw=r.text
        print("GRECOS_API_TEXT",compact(raw)[:12000])
    for key in ["Cena całkowita","Łącznie","Razem","Price","TotalPrice","Child1","Child2"]:
        hits=[]
        low=raw.lower(); target=key.lower();pos=0
        while len(hits)<10:
            i=low.find(target,pos)
            if i<0:break
            hits.append(compact(raw[max(0,i-350):min(len(raw),i+1000)]))
            pos=i+len(target)
        for x in hits:print("GRECOS_API_SNIP",key,x[:1600])

    o=Options()
    o.add_argument("--headless=new");o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3200");o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        url=SEARCH+"?"+urlencode(p)
        d.get(url)
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(7)
        print("GRECOS_BROWSER_FINAL",d.current_url)
        print("GRECOS_BROWSER_EXACT_QUERY",exact_query(d.current_url,p))
        body=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["dorośli 2","dzieci 2","5 lat","7 lat","cena","łącznie","razem","zł","all inclusive"]):
                print("GRECOS_LINE",line[:900])

        candidates=[]
        for a in d.find_elements(By.CSS_SELECTOR,"a[href]"):
            try:
                href=a.get_attribute("href") or ""
                txt=compact(a.text)
                if not href.startswith(BASE):continue
                anc=d.execute_script("""
                  let e=arguments[0];
                  for(let i=0;i<9 && e;i++,e=e.parentElement){
                    let t=(e.innerText||'').replace(/\\s+/g,' ').trim();
                    if(t.length>80 && t.length<5500 && /zł/i.test(t)) return e;
                  }
                  return null;
                """,a)
                if anc is None:continue
                t=compact(anc.text)
                key=(href,t)
                if key not in candidates:candidates.append(key)
            except Exception:
                pass
        print("GRECOS_CARD_COUNT",len(candidates))
        for href,t in candidates[:20]:
            print("GRECOS_CARD",repr({"href":href[:1400],"text":t[:2000]}))

        totals=[]
        for pat in [
            r"Cena\s*(?:całkowita|łącznie|razem)\s*[: ]*([0-9][0-9 .]*)\s*zł",
            r"(?:Łącznie|Razem)\s*[: ]*([0-9][0-9 .]*)\s*zł",
        ]:
            for m in re.findall(pat,body,re.I):
                n=re.sub(r"\D","",m)
                if n:totals.append(int(n))
        print("GRECOS_EXPLICIT_FAMILY_TOTALS",totals[:40])
        print("GRECOS_EXACT_FAMILY_TOTAL_VERIFIED",bool(totals) and exact_query(d.current_url,p))
    finally:
        d.quit()

if __name__=="__main__":
    main()
