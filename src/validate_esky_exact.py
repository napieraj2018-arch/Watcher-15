import json,re,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

URL="https://www.esky.pl/lot%2Bhotel/2-wakacje"

def compact(s): return " ".join((s or "").split())

def click_shortest(d, text, label):
    els=d.find_elements(By.XPATH,f"//*[self::button or self::div or self::span or self::label or @role='button'][contains(normalize-space(.),\"{text}\")]")
    els=[e for e in els if e.is_displayed()]
    els.sort(key=lambda e:len(compact(e.text)))
    for e in els[:12]:
        try:
            print("ESKY_CLICK_TRY",label,repr({"tag":e.tag_name,"text":compact(e.text)[:300],"aria":e.get_attribute("aria-label"),"class":e.get_attribute("class"),"html":(e.get_attribute("outerHTML") or "")[:1800]}))
            d.execute_script("arguments[0].click()",e);time.sleep(1);return True
        except Exception as ex: print("ESKY_CLICK_ERR",label,type(ex).__name__,str(ex)[:160])
    return False

def dump_family(d,label):
    print(label)
    for e in d.find_elements(By.XPATH,"//input|//select|//button|//*[@role='button']|//*[@role='spinbutton']|//*[@role='combobox']"):
        try:
            if not e.is_displayed():continue
            txt=compact(e.text)
            blob=" ".join(filter(None,[txt,e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("class"),e.get_attribute("aria-label"),e.get_attribute("placeholder"),e.get_attribute("value")]))
            if any(k in blob.lower() for k in ["doros","dzie","child","adult","wiek","age","osob","guest","room","pokój","pokoj"]) or txt in ["+","-","−"]:
                print("ESKY_FAMILY_CTRL",repr({"tag":e.tag_name,"text":txt[:250],"name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),"aria":e.get_attribute("aria-label"),"placeholder":e.get_attribute("placeholder"),"class":e.get_attribute("class"),"html":(e.get_attribute("outerHTML") or "")[:2200]}))
        except:pass

def counter_plus(d,label,times):
    nodes=[n for n in d.find_elements(By.XPATH,f"//*[contains(normalize-space(.),\"{label}\")]") if n.is_displayed()]
    nodes.sort(key=lambda n:len(compact(n.text)))
    for n in nodes[:20]:
        anc=n
        try:
            for level in range(1,7):
                anc=anc.find_element(By.XPATH,"..")
                bs=[b for b in anc.find_elements(By.TAG_NAME,"button") if b.is_displayed() and b.is_enabled()]
                if len(bs)>=2:
                    plus=[b for b in bs if compact(b.text) in ["+","＋"] or "plus" in ((b.get_attribute("aria-label") or "")+" "+(b.get_attribute("data-testid") or "")).lower()]
                    if not plus: plus=[bs[-1]]
                    print("ESKY_COUNTER",label,level,(anc.get_attribute("outerHTML") or "")[:5000])
                    for i in range(times):
                        d.execute_script("arguments[0].click()",plus[-1]);time.sleep(.8);print("ESKY_PLUS",label,i+1)
                    return True
        except:pass
    return False

def set_child_ages(d):
    candidates=[]
    for e in d.find_elements(By.XPATH,"//select|//input"):
        try:
            if not e.is_displayed():continue
            blob=" ".join(filter(None,[e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("aria-label"),e.get_attribute("placeholder"),e.get_attribute("class")])).lower()
            if "age" in blob or "wiek" in blob or "child" in blob or "dzie" in blob:
                candidates.append(e)
        except:pass
    print("ESKY_AGE_CANDIDATES",len(candidates))
    used=0
    for e in candidates:
        if used>=2:break
        try:
            if e.tag_name=="select":
                opts=[(o.get_attribute("value"),compact(o.text)) for o in e.find_elements(By.TAG_NAME,"option")]
                print("ESKY_AGE_OPTIONS",used,opts[:40])
                target="5" if used==0 else "7"
                ok=False
                for v,t in opts:
                    if v==target or compact(t)==target or target in compact(t).split():
                        try: Select(e).select_by_value(v);ok=True
                        except: pass
                        if ok:break
                if ok:
                    print("ESKY_AGE_SET",used,target,e.get_attribute("value"));used+=1;continue
            # Numeric/text age fields only when attributes clearly identify age.
            blob=" ".join(filter(None,[e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("aria-label"),e.get_attribute("placeholder")])).lower()
            if "age" in blob or "wiek" in blob:
                target="5" if used==0 else "7"
                d.execute_script("arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",e,target)
                print("ESKY_AGE_SET",used,target,e.get_attribute("value"));used+=1
        except Exception as ex:print("ESKY_AGE_ERR",type(ex).__name__,str(ex)[:160])
    return used

def main():
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3400");o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(7)
        print("ESKY_START",d.current_url,"TITLE",d.title)
        for t in ["Zaakceptuj wszystko","Akceptuję","Akceptuj wszystkie","OK"]:
            if click_shortest(d,t,"cookies"):break
        body=compact(d.find_element(By.TAG_NAME,"body").text)
        print("ESKY_BODY_LEN",len(body))
        for s in ["Ile osób","Pokój 1","Dorośli","Dzieci","Szukaj"]:
            print("ESKY_BODY_SIGNAL",s,s.lower() in body.lower())
        click_shortest(d,"Ile osób","party")
        time.sleep(1);dump_family(d,"ESKY_FAMILY_OPEN")
        adults_ok=True
        children_ok=counter_plus(d,"Dzieci",2)
        print("ESKY_CHILDREN_SET",children_ok)
        time.sleep(1);dump_family(d,"ESKY_FAMILY_AFTER_CHILDREN")
        ages=set_child_ages(d)
        print("ESKY_AGES_SET_COUNT",ages)
        for t in ["Gotowe","Zastosuj","Zatwierdź","Wybierz"]:
            if click_shortest(d,t,"apply_party"):break
        time.sleep(1)
        click_shortest(d,"Szukaj","search")
        time.sleep(9)
        print("ESKY_FINAL_URL",d.current_url)
        body2=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body2.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["doros","dzieci","5 lat","7 lat","all inclusive","zł","razem","łącznie","całkow"]):
                print("ESKY_SIGNAL",line[:1000])
        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if any(k in blob for k in ["search","package","hotel","offer","adult","child","guest","room","occup"]):
                    key=(u,post)
                    if key not in seen:
                        seen.add(key);print("ESKY_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except:pass
        print("ESKY_REQ_COUNT",len(seen))
        d.save_screenshot("esky-exact.png")
    finally:d.quit()

if __name__=="__main__":main()
