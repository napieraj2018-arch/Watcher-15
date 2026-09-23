import json,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

URL="https://www.primaholiday.pl/"

def compact(s): return " ".join((s or "").split())

def click_candidates(d, terms, label):
    nodes=d.find_elements(By.XPATH,"//button|//*[@role='button']|//input|//div|//span")
    cand=[]
    for e in nodes:
        try:
            if not e.is_displayed(): continue
            txt=compact(e.text)
            blob=" ".join(filter(None,[txt,e.get_attribute("aria-label"),e.get_attribute("placeholder"),e.get_attribute("class"),e.get_attribute("id")]))
            if any(t.lower() in blob.lower() for t in terms):
                cand.append((len(txt),e,blob))
        except: pass
    cand.sort(key=lambda x:x[0])
    for _,e,blob in cand[:20]:
        try:
            print("PRIMA_CLICK_TRY",label,compact(blob)[:500])
            d.execute_script("arguments[0].click()",e);time.sleep(.8);return True
        except: pass
    return False

def dump_controls(d,label):
    print(label)
    for e in d.find_elements(By.XPATH,"//input|//select|//button|//*[@role='button']|//*[@role='combobox']"):
        try:
            if not e.is_displayed(): continue
            txt=compact(e.text)
            blob=" ".join(filter(None,[txt,e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),e.get_attribute("class"),e.get_attribute("value")]))
            if any(k in blob.lower() for k in ["doros","dziec","dzieci","wiek","urodz","adult","child","age","guest","osob","osób","uczest"]):
                print("PRIMA_CTRL",json.dumps({
                    "tag":e.tag_name,"text":txt[:350],"name":e.get_attribute("name"),"id":e.get_attribute("id"),
                    "value":e.get_attribute("value"),"placeholder":e.get_attribute("placeholder"),
                    "aria":e.get_attribute("aria-label"),"class":e.get_attribute("class"),
                    "html":compact(e.get_attribute("outerHTML"))[:2800]
                },ensure_ascii=False))
        except: pass

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]:
        o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5)
        # Cookie handling must not use substring "OK" (it matched "Dokąd?").
        for b in d.find_elements(By.TAG_NAME,"button"):
            try:
                txt=compact(b.text).strip().lower()
                if b.is_displayed() and txt in ["zaakceptuj wszystko","akceptuję","akceptuj","zgadzam się","ok"]:
                    print("PRIMA_COOKIE_CLICK",txt)
                    d.execute_script("arguments[0].click()",b);time.sleep(.6);break
            except: pass
        print("PRIMA_START",d.current_url,"TITLE",d.title)
        body=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["doros","dzieci","osób","goście","all inclusive","last minute","cena","zł","warszawa","radom"]):
                print("PRIMA_SIGNAL",line[:900])
        dump_controls(d,"PRIMA_CONTROLS_BEFORE")
        opened=click_candidates(d,["osób","goście","doros"],"party")
        print("PRIMA_PARTY_OPENED",opened);time.sleep(1)
        dump_controls(d,"PRIMA_CONTROLS_OPEN")

        # Try real child counter buttons first.
        plus=[]
        for e in d.find_elements(By.XPATH,"//button"):
            try:
                if not e.is_displayed():continue
                aria=(e.get_attribute("aria-label") or "").lower()
                txt=compact(e.text)
                if ("dzie" in aria and ("zwiększ" in aria or "dodaj" in aria or "plus" in aria)) or (txt=="+" and "dzie" in compact(e.find_element(By.XPATH,"..").text).lower()):
                    plus.append(e)
            except:pass
        print("PRIMA_CHILD_PLUS_COUNT",len(plus))
        for i in range(min(2,len(plus))):
            d.execute_script("arguments[0].click()",plus[0]);time.sleep(.6);print("PRIMA_CHILD_PLUS",i+1)
        dump_controls(d,"PRIMA_CONTROLS_AFTER_CHILDREN")

        # Set two age selectors only when their option domain clearly contains 5 and 7.
        age_selects=[]
        for e in d.find_elements(By.TAG_NAME,"select"):
            try:
                opts=[(x.get_attribute("value"),compact(x.text)) for x in e.find_elements(By.TAG_NAME,"option")]
                vals={str(v) for v,t in opts}
                texts=" ".join(t for v,t in opts)
                if ("5" in vals or " 5 " in (" "+texts+" ")) and ("7" in vals or " 7 " in (" "+texts+" ")):
                    age_selects.append(e);print("PRIMA_AGE_SELECT",json.dumps({"name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),"options":opts[:40]},ensure_ascii=False))
            except:pass
        print("PRIMA_AGE_SELECT_COUNT",len(age_selects))
        for idx,target in enumerate(["5","7"]):
            if idx>=len(age_selects):break
            try:Select(age_selects[idx]).select_by_value(target)
            except:
                try:Select(age_selects[idx]).select_by_visible_text(target)
                except:continue
            time.sleep(.4);print("PRIMA_AGE_SET",idx+1,target,age_selects[idx].get_attribute("value"))

        # Apply/save participant picker if present.
        applied=click_candidates(d,["Zapisz","Wybierz","Gotowe","Zastosuj","Pokaż oferty","Szukaj"],"apply")
        print("PRIMA_APPLIED",applied);time.sleep(7)
        print("PRIMA_FINAL_URL",d.current_url)
        body2=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body2.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["2 doros","2 dzieci","5 lat","7 lat","all inclusive","cena","za wszystkich","zł","dostęp"]):
                print("PRIMA_FINAL_SIGNAL",line[:1000])

        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if "primaholiday.pl" in u and any(k in blob for k in ["search","offer","filter","adult","child","age","guest","participant","room","booking"]):
                    if (u,post) not in seen:
                        seen.add((u,post));print("PRIMA_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except:pass
        print("PRIMA_REQ_COUNT",len(seen))
    finally:
        d.quit()

if __name__=="__main__":main()
