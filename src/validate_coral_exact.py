import json,re,time
from urllib.parse import urlsplit,parse_qs
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

URL="https://www.coraltravel.pl/tours/warszawa/turcja/"

def compact(s): return " ".join((s or "").split())

def click_text(d,text,label):
    nodes=d.find_elements(By.XPATH,f"//*[self::button or self::div or self::span or self::label or @role='button'][contains(normalize-space(.),\"{text}\")]")
    nodes=[n for n in nodes if n.is_displayed()]
    nodes.sort(key=lambda n:len(compact(n.text)))
    for n in nodes[:16]:
        try:
            print("CORAL_CLICK_TRY",label,repr({"tag":n.tag_name,"text":compact(n.text)[:350],"aria":n.get_attribute("aria-label"),"class":n.get_attribute("class"),"html":(n.get_attribute("outerHTML") or "")[:2200]}))
            d.execute_script("arguments[0].click()",n);time.sleep(1);return True
        except Exception as e: print("CORAL_CLICK_ERR",label,type(e).__name__,str(e)[:160])
    return False

def dump_controls(d,label):
    print(label)
    for e in d.find_elements(By.XPATH,"//input|//select|//button|//*[@role='button']|//*[@role='combobox']|//*[@role='spinbutton']"):
        try:
            if not e.is_displayed(): continue
            txt=compact(e.text)
            blob=" ".join(filter(None,[txt,e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("class"),e.get_attribute("aria-label"),e.get_attribute("placeholder"),e.get_attribute("value"),e.get_attribute("data-testid")]))
            if any(k in blob.lower() for k in ["doros","dzie","adult","child","wiek","age","osob","uczest","guest","room","pokoj","pokój","price","cena"]) or txt in ["+","-","−","＋"]:
                print("CORAL_CTRL",repr({"tag":e.tag_name,"text":txt[:250],"name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),"aria":e.get_attribute("aria-label"),"placeholder":e.get_attribute("placeholder"),"class":e.get_attribute("class"),"testid":e.get_attribute("data-testid"),"html":(e.get_attribute("outerHTML") or "")[:2600]}))
        except: pass

def find_counter(d,label):
    nodes=[n for n in d.find_elements(By.XPATH,f"//*[contains(normalize-space(.),\"{label}\")]") if n.is_displayed()]
    nodes.sort(key=lambda n:len(compact(n.text)))
    for n in nodes[:30]:
        anc=n
        try:
            for lvl in range(1,8):
                anc=anc.find_element(By.XPATH,"..")
                bs=[b for b in anc.find_elements(By.TAG_NAME,"button") if b.is_displayed() and b.is_enabled()]
                if len(bs)>=2:
                    print("CORAL_COUNTER",label,lvl,(anc.get_attribute("outerHTML") or "")[:6000])
                    return anc,bs
        except: pass
    return None,[]

def set_children(d):
    anc,bs=find_counter(d,"Dzieci")
    if anc is None:
        anc,bs=find_counter(d,"dzieci")
    if anc is None:return False
    plus=[b for b in bs if compact(b.text) in ["+","＋"] or "plus" in ((b.get_attribute("aria-label") or "")+" "+(b.get_attribute("class") or "")).lower()]
    if not plus: plus=[bs[-1]]
    for i in range(2):
        d.execute_script("arguments[0].click()",plus[-1]);time.sleep(.8)
        print("CORAL_CHILD_PLUS",i+1)
    return True

def set_ages(d):
    candidates=[]
    for e in d.find_elements(By.XPATH,"//select|//input"):
        try:
            if not e.is_displayed():continue
            blob=" ".join(filter(None,[e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("aria-label"),e.get_attribute("placeholder"),e.get_attribute("class"),e.get_attribute("data-testid")])).lower()
            if any(k in blob for k in ["age","wiek","child","dzie"]):
                candidates.append(e)
        except:pass
    print("CORAL_AGE_CANDIDATES",len(candidates))
    used=0
    for e in candidates:
        if used>=2:break
        try:
            target="5" if used==0 else "7"
            if e.tag_name=="select":
                opts=[(o.get_attribute("value"),compact(o.text)) for o in e.find_elements(By.TAG_NAME,"option")]
                print("CORAL_AGE_OPTIONS",used,opts[:50])
                chosen=None
                for v,t in opts:
                    if v==target or t==target or target in t.split():
                        chosen=v;break
                if chosen is not None:
                    Select(e).select_by_value(chosen);time.sleep(.5);print("CORAL_AGE_SET",used,target,e.get_attribute("value"));used+=1;continue
            typ=(e.get_attribute("type") or "").lower()
            if typ in ["number","text","hidden"]:
                d.execute_script("arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",e,target)
                time.sleep(.4);print("CORAL_AGE_SET",used,target,e.get_attribute("value"));used+=1
        except Exception as ex: print("CORAL_AGE_ERR",type(ex).__name__,str(ex)[:160])
    return used

def main():
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3600");o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(7)
        print("CORAL_START",d.current_url,"TITLE",d.title)
        for t in ["Zaakceptuj wszystko","Akceptuję","Akceptuj wszystkie","Zgadzam się","OK"]:
            if click_text(d,t,"cookies"):break
        body=compact(d.find_element(By.TAG_NAME,"body").text)
        print("CORAL_BODY_LEN",len(body))
        for s in ["Doros","Dzieci","Pokaż cenę całkowitą","All Inclusive","Szukaj"]:
            print("CORAL_BODY_SIGNAL",s,s.lower() in body.lower())

        opened=False
        for t in ["2 Doros","Dorosłych","Dorośli"]:
            if click_text(d,t,"party"):opened=True;break
        print("CORAL_PARTY_OPENED",opened);time.sleep(1);dump_controls(d,"CORAL_CONTROLS_OPEN")
        children=set_children(d);print("CORAL_CHILDREN_SET",children);time.sleep(1)
        dump_controls(d,"CORAL_CONTROLS_AFTER_CHILDREN")
        ages=set_ages(d);print("CORAL_AGES_SET_COUNT",ages)
        for t in ["Zastosuj","Wybierz","Gotowe","Zatwierdź"]:
            if click_text(d,t,"apply_party"):break
        time.sleep(1)

        total_clicked=click_text(d,"Pokaż cenę całkowitą","total_price")
        print("CORAL_TOTAL_CLICKED",total_clicked)
        for t in ["Zastosuj filtry","Szukaj"]:
            if click_text(d,t,"search"):break
        time.sleep(9)
        print("CORAL_FINAL_URL",d.current_url)
        print("CORAL_FINAL_QUERY",json.dumps(parse_qs(urlsplit(d.current_url).query),ensure_ascii=False,sort_keys=True))
        body2=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body2.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["doros","dzieci","5 lat","7 lat","all inclusive","cena całkow","zł","razem"]):
                print("CORAL_SIGNAL",line[:1000])

        try:
            storage=d.execute_script("return {local:{...localStorage},session:{...sessionStorage}}")
            for kind,vals in storage.items():
                for k,v in vals.items():
                    blob=(k+" "+str(v)).lower()
                    if any(x in blob for x in ["adult","child","age","search","tour","price","participant"]):
                        print("CORAL_STORAGE",kind,k,str(v)[:5000])
        except Exception as e:print("CORAL_STORAGE_ERR",type(e).__name__,str(e)[:160])

        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if any(k in blob for k in ["api","search","tour","offer","adult","child","age","participant","price"]):
                    key=(u,post)
                    if key not in seen:
                        seen.add(key);print("CORAL_REQ",req.get("method"),u[:6000],"POST",post[:6000])
            except:pass
        print("CORAL_REQ_COUNT",len(seen))
        d.save_screenshot("coral-exact.png")
    finally:d.quit()

if __name__=="__main__":main()
