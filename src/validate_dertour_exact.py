import json,re,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.dertour.pl/"

def compact(s): return " ".join((s or "").split())

def click_match(d,terms,label):
    cand=[]
    for e in d.find_elements(By.XPATH,"//button|//input|//div|//span|//label|//*[@role='button']"):
        try:
            if not e.is_displayed(): continue
            blob=" ".join(filter(None,[compact(e.text),e.get_attribute("value"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),e.get_attribute("class"),e.get_attribute("id")]))
            if any(t.lower() in blob.lower() for t in terms): cand.append((len(compact(e.text)),e,blob))
        except: pass
    cand.sort(key=lambda x:x[0])
    for _,e,blob in cand[:25]:
        try:
            print("DER_CLICK",label,compact(blob)[:500])
            d.execute_script("arguments[0].click()",e);time.sleep(.7);return True
        except: pass
    return False

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]:o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5)
        for t in ["Akceptuj","Zaakceptuj","Zgadzam","OK"]: click_match(d,[t],"cookies")
        print("DER_START",d.current_url,d.title)
        body=d.find_element(By.TAG_NAME,"body").text
        for s in ["Uczestnicy","Dzieci 0-17","Data urodzenia","WAKACJE SAMOLOTEM","All inclusive"]:
            print("DER_SIGNAL",s,s.lower() in body.lower())
        opened=click_match(d,["Uczestnicy"],"party");print("DER_PARTY_OPENED",opened);time.sleep(1)

        # Add exactly two children through the smallest visible container around "Dzieci".
        child_row=None
        nodes=[x for x in d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Dzieci')]") if x.is_displayed()]
        nodes.sort(key=lambda x:len(compact(x.text)))
        for n in nodes[:30]:
            anc=n
            try:
                for _ in range(6):
                    anc=anc.find_element(By.XPATH,"..")
                    bs=[b for b in anc.find_elements(By.XPATH,".//button|.//input[@type='button']") if b.is_displayed() and b.is_enabled()]
                    if len(bs)>=2:
                        child_row=anc;break
                if child_row:break
            except:pass
        print("DER_CHILD_ROW",compact(child_row.text)[:800] if child_row else None)
        if child_row:
            bs=[b for b in child_row.find_elements(By.XPATH,".//button|.//input[@type='button']") if b.is_displayed() and b.is_enabled()]
            plus=bs[-1] if bs else None
            if plus:
                for i in range(2):
                    d.execute_script("arguments[0].click()",plus);time.sleep(.6);print("DER_CHILD_PLUS",i+1)

        # Exact DOBs for children aged 5 and 7 at current search date.
        dob_fields=[]
        for e in d.find_elements(By.XPATH,"//input"):
            try:
                blob=" ".join(filter(None,[e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),e.get_attribute("class")])).lower()
                if e.is_displayed() and ("urodz" in blob or "birth" in blob or "data" in blob and "dzie" in compact(e.find_element(By.XPATH,"..").text).lower()):
                    dob_fields.append(e)
            except:pass
        print("DER_DOB_COUNT",len(dob_fields))
        vals=["01.01.2021","01.01.2019"]
        setvals=[]
        for i,v in enumerate(vals):
            if i>=len(dob_fields):break
            e=dob_fields[i]
            d.execute_script("arguments[0].removeAttribute('readonly');arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",e,v)
            time.sleep(.4);setvals.append(e.get_attribute("value"));print("DER_DOB_SET",i+1,v,e.get_attribute("value"))
        click_match(d,["Potwierdź","Wybierz","Gotowe","Zastosuj"],"apply")
        print("DER_EXACT_PARTY",json.dumps({"adults":2,"children":2,"birthdates":setvals},ensure_ascii=False))
        # Capture forms and real request schema. Do not promote from UI labels alone.
        for i,f in enumerate(d.find_elements(By.TAG_NAME,"form")[:20]):
            try:
                fields=[]
                for e in f.find_elements(By.XPATH,".//input|.//select"):
                    n=e.get_attribute("name")
                    if n: fields.append((n,e.get_attribute("value")))
                blob=json.dumps(fields,ensure_ascii=False).lower()
                if any(k in blob for k in ["adult","child","birth","uczest","person","age"]):
                    print("DER_FORM",i,f.get_attribute("action"),json.dumps(fields[:160],ensure_ascii=False))
            except:pass
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if "dertour.pl" in u and any(k in blob for k in ["adult","child","birth","search","offer","price","participant","person"]):
                    print("DER_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except:pass
    finally:d.quit()
if __name__=="__main__":main()
