import json,re,time
from datetime import datetime,timedelta
from urllib.parse import urlsplit,parse_qs
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait,Select

URL="https://www.traveligo.pl/"
TZ=ZoneInfo("Europe/Warsaw")

def compact(s): return " ".join((s or "").split())

def click_text(d,text,label):
    els=d.find_elements(By.XPATH,f"//*[self::button or self::a or self::span or self::label or self::div][contains(normalize-space(.),\"{text}\")]")
    els=[e for e in els if e.is_displayed()]
    els.sort(key=lambda e:len(compact(e.text)))
    for e in els[:20]:
        try:
            print("TRAVELIGO_CLICK",label,repr({"tag":e.tag_name,"text":compact(e.text)[:260],"id":e.get_attribute("id"),"class":e.get_attribute("class"),"html":(e.get_attribute("outerHTML") or "")[:1800]}))
            d.execute_script("arguments[0].click()",e);time.sleep(.8);return True
        except Exception as ex: print("TRAVELIGO_CLICK_ERR",label,type(ex).__name__,str(ex)[:160])
    return False

def field_dump(d,label):
    print(label)
    for e in d.find_elements(By.XPATH,"//input|//select|//button"):
        try:
            if not e.is_displayed(): continue
            txt=compact(e.text)
            blob=" ".join(filter(None,[txt,e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("class"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),e.get_attribute("value")]))
            if any(k in blob.lower() for k in ["doros","dzie","wiek","child","adult","person","osob","price","cena","wylot","wyjazd","airport","date","from","to","duration","dni","all"]):
                print("TRAVELIGO_FIELD",repr({"tag":e.tag_name,"text":txt[:240],"name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),"class":e.get_attribute("class"),"placeholder":e.get_attribute("placeholder"),"html":(e.get_attribute("outerHTML") or "")[:2600]}))
        except: pass

def nearest_select(d,label):
    nodes=[n for n in d.find_elements(By.XPATH,f"//*[contains(normalize-space(.),\"{label}\")]") if n.is_displayed()]
    nodes.sort(key=lambda n:len(compact(n.text)))
    for n in nodes[:30]:
        anc=n
        try:
            for _ in range(5):
                anc=anc.find_element(By.XPATH,"..")
                sels=[s for s in anc.find_elements(By.TAG_NAME,"select") if s.is_displayed()]
                if sels:
                    print("TRAVELIGO_SELECT_NEAR",label,(anc.get_attribute("outerHTML") or "")[:3500])
                    return sels[0]
        except: pass
    return None

def select_value(e,target,label):
    try:
        opts=[(o.get_attribute("value"),compact(o.text)) for o in e.find_elements(By.TAG_NAME,"option")]
        print("TRAVELIGO_OPTIONS",label,opts[:80])
        for v,t in opts:
            if str(v)==str(target) or compact(t)==str(target) or re.search(rf"(^|\D){re.escape(str(target))}(\D|$)",t):
                Select(e).select_by_value(v);time.sleep(.5);print("TRAVELIGO_SELECTED",label,target,e.get_attribute("value"));return True
    except Exception as ex: print("TRAVELIGO_SELECT_ERR",label,type(ex).__name__,str(ex)[:180])
    return False

def main():
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3600");o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(6)
        print("TRAVELIGO_START",d.current_url,"TITLE",d.title)
        for t in ["Akceptuję","Akceptuj","Zgadzam się","OK","Zaakceptuj wszystko"]:
            if click_text(d,t,"cookies"):break
        body=compact(d.find_element(By.TAG_NAME,"body").text)
        for s in ["Dorośli","Dzieci","Wiek dzieci","Cena całkowita","All Inclusive","Radom","Warszawa - Modlin"]:
            print("TRAVELIGO_BODY_SIGNAL",s,s.lower() in body.lower())
        field_dump(d,"TRAVELIGO_FIELDS_BEFORE")

        adults=nearest_select(d,"Dorośli")
        children=nearest_select(d,"Dzieci")
        ok_a=select_value(adults,"2","adults") if adults else False
        ok_c=select_value(children,"2","children") if children else False
        time.sleep(1)
        field_dump(d,"TRAVELIGO_FIELDS_AFTER_CHILDREN")

        # Identify age selectors by labels/nearby DOM after children=2.
        age_sels=[]
        for n in [x for x in d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Wiek dzieci') or contains(normalize-space(.),'Wiek dziecka')]") if x.is_displayed()]:
            anc=n
            try:
                for _ in range(6):
                    anc=anc.find_element(By.XPATH,"..")
                    for s in anc.find_elements(By.TAG_NAME,"select"):
                        if s.is_displayed() and s not in age_sels: age_sels.append(s)
                    if len(age_sels)>=2: break
            except: pass
        # Fallback: visible selects with options containing child ages.
        if len(age_sels)<2:
            for s in d.find_elements(By.TAG_NAME,"select"):
                try:
                    if not s.is_displayed() or s in (adults,children) or s in age_sels: continue
                    texts=[compact(o.text) for o in s.find_elements(By.TAG_NAME,"option")]
                    if any(re.search(r"\b5\b",x) for x in texts) and any(re.search(r"\b7\b",x) for x in texts):
                        age_sels.append(s)
                except: pass
        print("TRAVELIGO_AGE_SELECT_COUNT",len(age_sels))
        ok5=select_value(age_sels[0],"5","age1") if len(age_sels)>0 else False
        ok7=select_value(age_sels[1],"7","age2") if len(age_sels)>1 else False

        # Use real All Inclusive checkbox and target airports if exposed.
        for label in ["All Inclusive","Radom","Warszawa","Warszawa - Modlin"]:
            els=[e for e in d.find_elements(By.XPATH,f"//label[contains(normalize-space(.),\"{label}\")]") if e.is_displayed()]
            for e in els[:3]:
                try:
                    target=e.get_attribute("for")
                    inp=d.find_element(By.ID,target) if target else None
                    if inp is not None and inp.get_attribute("type") in ["checkbox","radio"] and not inp.is_selected():
                        d.execute_script("arguments[0].click()",e);time.sleep(.3);print("TRAVELIGO_FILTER_CLICK",label,target)
                        break
                except: pass

        print("TRAVELIGO_PARTY_SET",{"adults":ok_a,"children":ok_c,"age5":ok5,"age7":ok7})
        field_dump(d,"TRAVELIGO_FIELDS_FINAL")
        click_text(d,"Szukaj","search");time.sleep(10)
        print("TRAVELIGO_FINAL_URL",d.current_url)
        print("TRAVELIGO_FINAL_QUERY",json.dumps(parse_qs(urlsplit(d.current_url).query),ensure_ascii=False,sort_keys=True))
        body2=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body2.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["doro","dzieci","5 lat","7 lat","all inclusive","cena / os","cena całkow","cena za","dostępność","radom","warszawa","zł"]):
                print("TRAVELIGO_SIGNAL",line[:1200])

        # Switch listing to all-person price only if the UI has an explicit control.
        total_clicked=False
        for phrase in ["wszystkich","Cena całkowita","Cena za wszystkich"]:
            if click_text(d,phrase,"total_price"):
                total_clicked=True;time.sleep(5);break
        print("TRAVELIGO_TOTAL_CLICKED",total_clicked)
        body3=d.find_element(By.TAG_NAME,"body").text
        totals=[]
        for m in re.findall(r"(?:Cena\s*(?:całkowita|za wszystkich)|Razem)\D{0,25}([0-9][0-9 .]*)\s*zł",body3,re.I):
            n=re.sub(r"\D","",m)
            if n:totals.append(int(n))
        print("TRAVELIGO_EXPLICIT_TOTALS",totals[:40])

        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if "traveligo.pl" in u and any(k in blob for k in ["search","offer","adult","child","age","osob","price","cena","occup"]):
                    key=(u,post)
                    if key not in seen:
                        seen.add(key);print("TRAVELIGO_REQ",req.get("method"),u[:6000],"POST",post[:6000])
            except: pass
        print("TRAVELIGO_REQ_COUNT",len(seen))
        d.save_screenshot("traveligo-exact.png")
    finally:d.quit()

if __name__=="__main__":main()
