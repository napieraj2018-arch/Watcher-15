import json,re,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit,parse_qs,urlencode

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

TZ=ZoneInfo("Europe/Warsaw")
BASE="https://search.anextour.com.pl/search_tour"

def compact(s): return " ".join((s or "").split())

def label_context(e):
    parts=[]
    try:
        if e.get_attribute("id"):
            labs=e.find_elements(By.XPATH,f"//label[@for='{e.get_attribute('id')}']")
            parts += [compact(x.text) for x in labs]
    except: pass
    try:
        p=e.find_element(By.XPATH,"..")
        parts.append(compact(p.text)[:220])
    except: pass
    return " | ".join(x for x in parts if x)

def dump_selects(d,label):
    print(label)
    for i,e in enumerate(d.find_elements(By.TAG_NAME,"select")):
        try:
            opts=[(o.get_attribute("value"),compact(o.text)) for o in e.find_elements(By.TAG_NAME,"option")]
            rec={
              "i":i,"name":e.get_attribute("name"),"id":e.get_attribute("id"),
              "value":e.get_attribute("value"),"displayed":e.is_displayed(),
              "context":label_context(e),"options":opts[:35]
            }
            blob=json.dumps(rec,ensure_ascii=False).lower()
            if any(k in blob for k in ["adult","child","dzieci","wiek","age","townfrom","wylot","nights","noc","meal","wyżyw","currency","cena"]):
                print("ANEX_SELECT",json.dumps(rec,ensure_ascii=False))
        except Exception as ex: print("ANEX_SELECT_ERR",i,type(ex).__name__)

def main():
    today=datetime.now(TZ).date()
    q=[
      ("ADULT","2"),("CHILD","2"),("AGE1","5"),("AGE2","7"),("LANG","pol"),
      ("CHECKIN_BEG",(today+timedelta(days=1)).strftime("%Y%m%d")),
      ("CHECKIN_END",(today+timedelta(days=3)).strftime("%Y%m%d")),
      ("NIGHTS_FROM","5"),("NIGHTS_TILL","8")
    ]
    url=BASE+"?"+urlencode(q)
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]: o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(url);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(6)
        print("ANEX_START",d.current_url,"TITLE",d.title)
        qnow=parse_qs(urlsplit(d.current_url).query)
        print("ANEX_QUERY",json.dumps(qnow,ensure_ascii=False,sort_keys=True))
        print("ANEX_EXACT_PARTY_QUERY",qnow.get("ADULT")==["2"] and qnow.get("CHILD")==["2"] and qnow.get("AGE1")==["5"] and qnow.get("AGE2")==["7"])
        dump_selects(d,"ANEX_SELECTS_BEFORE")
        body=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["dorośli","dzieci/wiek","5 lat","7 lat","all inclusive","dostępne","cena","razem","zł","warszawa","radom"]):
                print("ANEX_SIGNAL",line[:900])

        # Child-age selects are immediately downstream of the CHILD control in
        # SAMO-Soft forms. Never guess their names: identify by DOM order and
        # option domain, then set exact ages 5 and 7.
        sels=d.find_elements(By.TAG_NAME,"select")
        child_idx=None
        for i,e in enumerate(sels):
            n=(e.get_attribute("name") or "").upper()
            if n=="CHILD": child_idx=i;break
        ages=[]
        if child_idx is not None:
            for e in sels[child_idx+1:child_idx+5]:
                try:
                    opts=[(o.get_attribute("value"),compact(o.text)) for o in e.find_elements(By.TAG_NAME,"option")]
                    vals={str(v) for v,t in opts}
                    texts={t for v,t in opts}
                    if ("5" in vals or any(re.search(r"(^|\\D)5(\\D|$)",t) for t in texts)) and ("7" in vals or any(re.search(r"(^|\\D)7(\\D|$)",t) for t in texts)):
                        ages.append(e)
                except: pass
        print("ANEX_AGE_SELECT_COUNT",len(ages))
        for idx,target in enumerate(["5","7"]):
            if idx>=len(ages):break
            e=ages[idx]
            # SAMO renders the canonical selects hidden behind its own widget.
            # Direct query parameters are the source of truth; mirror them into
            # DOM with native change events only for serialization diagnostics.
            d.execute_script("""
              const e=arguments[0],v=arguments[1];
              e.value=v;
              e.dispatchEvent(new Event('change',{bubbles:true}));
            """,e,target)
            time.sleep(.3)
            print("ANEX_AGE_SET",idx+1,{"name":e.get_attribute("name"),"id":e.get_attribute("id"),"target":target,"value":e.get_attribute("value")})

        # Inspect exact form serialization after age changes.
        forms=d.find_elements(By.TAG_NAME,"form")
        for i,f in enumerate(forms[:8]):
            try:
                action=f.get_attribute("action") or ""
                fields={}
                for e in f.find_elements(By.XPATH,".//input|.//select"):
                    n=e.get_attribute("name")
                    if n and any(k in n.upper() for k in ["ADULT","CHILD","AGE","CHECKIN","NIGHTS","TOWNFROM","MEAL"]):
                        fields.setdefault(n,[]).append(e.get_attribute("value"))
                if fields: print("ANEX_FORM",i,action,json.dumps(fields,ensure_ascii=False))
            except: pass

        # Click the real search submit if available.
        clicked=False
        for b in d.find_elements(By.XPATH,"//button|//input[@type='submit']"):
            try:
                txt=compact(b.text)+" "+(b.get_attribute("value") or "")
                if b.is_displayed() and "szukaj" in txt.lower():
                    d.execute_script("arguments[0].click()",b);clicked=True;break
            except: pass
        print("ANEX_SEARCH_CLICKED",clicked);time.sleep(10)
        print("ANEX_FINAL",d.current_url)
        print("ANEX_FINAL_QUERY",json.dumps(parse_qs(urlsplit(d.current_url).query),ensure_ascii=False,sort_keys=True))
        body2=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body2.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["dorośli","dzieci","all inclusive","dostępne","ostatnie","cena","razem","zł","warszawa","radom"]):
                print("ANEX_RESULT",line[:1000])
        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or ""; blob=(u+" "+post).lower()
                if "anextour.com.pl" in u and any(k in blob for k in ["adult","child","age","search","price","tour"]):
                    key=(u,post)
                    if key not in seen:
                        seen.add(key);print("ANEX_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except: pass
        print("ANEX_REQ_COUNT",len(seen))
    finally:d.quit()
if __name__=="__main__":main()
