import json,re,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit,parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

URL="https://fly.pl/szukaj-wycieczek/"
TZ=ZoneInfo("Europe/Warsaw")

def compact(s): return " ".join((s or "").split())

def dismiss(d):
    for t in ["Allow all","Zezwól na wszystkie","Zaakceptuj wszystko","Akceptuję","Akceptuj","OK"]:
        try:
            es=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
            if es and es[0].is_displayed():
                d.execute_script("arguments[0].click()",es[0]);time.sleep(.7);return
        except: pass

def dump_people(d,label):
    print(label)
    for el in d.find_elements(By.XPATH,"//input|//select|//button|//*[@data-module='dropdown']"):
        try:
            txt=compact(el.text)
            attrs=" ".join(filter(None,[
                txt,el.get_attribute("name"),el.get_attribute("id"),
                el.get_attribute("placeholder"),el.get_attribute("aria-label"),
                el.get_attribute("class"),el.get_attribute("data-itext"),
                el.get_attribute("data-name"),el.get_attribute("value")
            ]))
            lo=attrs.lower()
            if any(k in lo for k in ["doros","dziec","dzieci","child","adult","person","osob","osób","wiek","age","people","kto"]):
                print("FLY_PEOPLE",repr({
                    "tag":el.tag_name,"displayed":el.is_displayed(),"text":txt[:300],
                    "name":el.get_attribute("name"),"id":el.get_attribute("id"),
                    "value":el.get_attribute("value"),"placeholder":el.get_attribute("placeholder"),
                    "class":el.get_attribute("class"),"data_name":el.get_attribute("data-name"),
                    "html":(el.get_attribute("outerHTML") or "")[:2400]
                }))
        except: pass

def open_people(d):
    candidates=[]
    for el in d.find_elements(By.XPATH,"//*[@data-module='dropdown']|//*[contains(@class,'dropmenu-input')]|//*[contains(@class,'main_advance_filters_container')]"):
        try:
            blob=compact(el.text).lower()
            html=(el.get_attribute("outerHTML") or "").lower()
            if any(k in blob+" "+html for k in ["doros","dziec","kto","people","person"]):
                candidates.append(el)
        except: pass
    print("FLY_PEOPLE_OPEN_CANDIDATES",len(candidates))
    for el in candidates:
        try:
            print("FLY_OPEN_TRY",compact(el.text)[:500],(el.get_attribute("outerHTML") or "")[:1600])
            d.execute_script("arguments[0].click()",el);time.sleep(1)
            if d.find_elements(By.XPATH,"//input[contains(translate(@placeholder,'DOROSŁI','dorosłi'),'doros') or contains(translate(@placeholder,'DZIECI','dzieci'),'dzieci')]"):
                return True
        except Exception as e: print("FLY_OPEN_ERR",type(e).__name__,str(e)[:180])
    return False

def set_numeric(d,needle,target):
    els=d.find_elements(By.XPATH,f"//input[contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'{needle}')]")
    els += d.find_elements(By.XPATH,f"//input[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'{needle}')]")
    seen=[]
    for el in els:
        if el in seen: continue
        seen.append(el)
        try:
            print("FLY_NUMERIC_TARGET",needle,repr({"name":el.get_attribute("name"),"value":el.get_attribute("value"),"html":el.get_attribute("outerHTML")[:1400]}))
            d.execute_script("""
              const e=arguments[0],v=String(arguments[1]);
              const proto=Object.getPrototypeOf(e);
              const desc=Object.getOwnPropertyDescriptor(proto,'value');
              if(desc&&desc.set) desc.set.call(e,v); else e.value=v;
              e.dispatchEvent(new Event('input',{bubbles:true}));
              e.dispatchEvent(new Event('change',{bubbles:true}));
              e.dispatchEvent(new Event('blur',{bubbles:true}));
            """,el,target)
            time.sleep(.7)
            print("FLY_NUMERIC_AFTER",needle,el.get_attribute("value"))
            return True
        except Exception as e: print("FLY_NUMERIC_ERR",needle,type(e).__name__,str(e)[:180])
    return False

def main():
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--window-size=1440,3400");o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5);dismiss(d)
        print("FLY_START",d.current_url)
        dump_people(d,"FLY_PEOPLE_BEFORE")
        print("FLY_OPENED",open_people(d));dump_people(d,"FLY_PEOPLE_AFTER_OPEN")

        a=set_numeric(d,"doros",2)
        c=set_numeric(d,"dzieci",2)
        print("FLY_COUNTS_SET",a,c)
        time.sleep(1);dump_people(d,"FLY_AFTER_COUNTS")

        age_controls=[]
        for el in d.find_elements(By.XPATH,"//select|//input"):
            try:
                blob=" ".join(filter(None,[el.get_attribute("name"),el.get_attribute("id"),el.get_attribute("placeholder"),el.get_attribute("aria-label"),compact(el.text)])).lower()
                if "wiek" in blob or "age" in blob:
                    age_controls.append(el)
                    print("FLY_AGE_CONTROL",repr({"tag":el.tag_name,"name":el.get_attribute("name"),"id":el.get_attribute("id"),"value":el.get_attribute("value"),"html":el.get_attribute("outerHTML")[:2000]}))
            except: pass
        for idx,target in enumerate(["5","7"]):
            if idx>=len(age_controls): break
            el=age_controls[idx]
            try:
                if el.tag_name=="select": Select(el).select_by_value(target)
                else:
                    d.execute_script("arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",el,target)
                time.sleep(.4);print("FLY_AGE_SET",idx,target,el.get_attribute("value"))
            except Exception as e: print("FLY_AGE_SET_ERR",idx,type(e).__name__,str(e)[:200])

        # Dump all form fields after party editing, including hidden serialization.
        for i,f in enumerate(d.find_elements(By.TAG_NAME,"form")):
            try:
                html=f.get_attribute("outerHTML") or ""
                if any(k in html.lower() for k in ["doros","dziec","child","adult","filter[person","filter[age"]):
                    print("FLY_FORM",i,html[:30000])
            except: pass
        print("FLY_URL_BEFORE_SUBMIT",d.current_url)

        # Prefer a visible primary search/submit control.
        submits=d.find_elements(By.XPATH,"//button[contains(normalize-space(.),'Szukaj')]|//input[@type='submit']")
        clicked=False
        for b in submits:
            try:
                if b.is_displayed() and b.is_enabled():
                    print("FLY_SUBMIT",compact(b.text),(b.get_attribute("outerHTML") or "")[:1200])
                    d.execute_script("arguments[0].click()",b);clicked=True;break
            except: pass
        print("FLY_SUBMIT_CLICKED",clicked)
        time.sleep(8)
        print("FLY_FINAL_URL",d.current_url)
        print("FLY_FINAL_QUERY",json.dumps(parse_qs(urlsplit(d.current_url).query),ensure_ascii=False,sort_keys=True))
        body=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["doros","dzieci","5 lat","7 lat","za wszystkich","zł/os","all inclusive","warszawa - radom","warszawa - modlin","warszawa - okęcie"]):
                print("FLY_SIGNAL",line[:1000])
        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or ""; blob=(u+" "+post).lower()
                if any(k in blob for k in ["search","filter","adult","child","person","dziec","occup"]):
                    if (u,post) not in seen:
                        seen.add((u,post));print("FLY_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except: pass
        d.save_screenshot("fly-exact.png")
    finally:d.quit()

if __name__=="__main__":main()
