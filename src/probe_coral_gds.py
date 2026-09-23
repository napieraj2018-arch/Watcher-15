import json,re,time
from urllib.parse import urlsplit,parse_qs
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

URL="https://booking.coraltravel.pl/"

def compact(s): return " ".join((s or "").split())

def click_text(d,terms,label):
    nodes=d.find_elements(By.XPATH,"//button|//a|//div|//span|//label")
    cand=[]
    for e in nodes:
        try:
            if not e.is_displayed():continue
            txt=compact(e.text)
            if any(t.lower() in txt.lower() for t in terms):
                cand.append((len(txt),e,txt))
        except:pass
    cand.sort(key=lambda x:x[0])
    for _,e,txt in cand[:25]:
        try:
            print("CORALGDS_CLICK",label,txt[:300],(e.get_attribute("outerHTML") or "")[:1800])
            d.execute_script("arguments[0].click()",e);time.sleep(.8);return True
        except:pass
    return False

def controls(d,label):
    print(label)
    for e in d.find_elements(By.XPATH,"//input|//select|//button"):
        try:
            txt=compact(e.text)
            blob=" ".join(filter(None,[txt,e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),e.get_attribute("value"),e.get_attribute("class")]))
            if any(k in blob.lower() for k in ["adult","child","dziec","doros","wiek","age","traveller","traveler","passenger","guest","room","hotel"]):
                print("CORALGDS_CTRL",json.dumps({"tag":e.tag_name,"text":txt[:200],"name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),"placeholder":e.get_attribute("placeholder"),"aria":e.get_attribute("aria-label"),"class":e.get_attribute("class"),"html":(e.get_attribute("outerHTML") or "")[:2200]},ensure_ascii=False))
        except:pass

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3200","--lang=pl-PL"]:o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5)
        print("CORALGDS_START",d.current_url,d.title)
        click_text(d,["Hotel","Hotele"],"hotel-tab");time.sleep(1)
        controls(d,"CORALGDS_BEFORE")
        click_text(d,["Podróżni","Dorośli"],"party");time.sleep(1)
        controls(d,"CORALGDS_PARTY_OPEN")
        # Prefer plus button from the smallest ancestor containing Dziecko.
        child_nodes=[x for x in d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Dziecko') or contains(normalize-space(.),'Dzieci')]") if x.is_displayed()]
        child_nodes.sort(key=lambda x:len(compact(x.text)))
        child_plus=None
        for n in child_nodes[:30]:
            anc=n
            try:
                for _ in range(6):
                    anc=anc.find_element(By.XPATH,"..")
                    bs=[b for b in anc.find_elements(By.TAG_NAME,"button") if b.is_displayed() and b.is_enabled()]
                    if len(bs)>=2:
                        child_plus=bs[-1];print("CORALGDS_CHILD_ROW",(anc.get_attribute("outerHTML") or "")[:5000]);break
                if child_plus:break
            except:pass
        if child_plus:
            for i in range(2):
                d.execute_script("arguments[0].click()",child_plus);time.sleep(.7);print("CORALGDS_CHILD_PLUS",i+1)
        controls(d,"CORALGDS_AFTER_CHILDREN")
        ages=[]
        for e in d.find_elements(By.TAG_NAME,"select"):
            try:
                opts=[(x.get_attribute("value"),compact(x.text)) for x in e.find_elements(By.TAG_NAME,"option")]
                vals={str(v) for v,t in opts}; texts=" ".join(t for v,t in opts)
                if ("5" in vals or re.search(r"(^|\s)5(\s|$)",texts)) and ("7" in vals or re.search(r"(^|\s)7(\s|$)",texts)):
                    ages.append((e,opts))
            except:pass
        print("CORALGDS_AGE_COUNT",len(ages))
        for i,target in enumerate(["5","7"]):
            if i>=len(ages):break
            e,opts=ages[i]
            chosen=next((v for v,t in opts if str(v)==target or compact(t)==target or target in compact(t).split()),None)
            if chosen is not None:
                Select(e).select_by_value(chosen);time.sleep(.4);print("CORALGDS_AGE_SET",i+1,target,e.get_attribute("value"))
        click_text(d,["Zamknij","Zatwierdź","Wybierz","Gotowe"],"party-apply");time.sleep(.8)
        controls(d,"CORALGDS_FINAL_CONTROLS")
        # Do not submit an empty hotel search; inspect form serialization and network schema only.
        for i,f in enumerate(d.find_elements(By.TAG_NAME,"form")):
            try:
                fields=[]
                for e in f.find_elements(By.XPATH,".//input|.//select"):
                    n=e.get_attribute("name")
                    if n:
                        fields.append((n,e.get_attribute("value")))
                if fields:
                    blob=json.dumps(fields,ensure_ascii=False).lower()
                    if any(k in blob for k in ["child","adult","age","hotel","passenger"]):
                        print("CORALGDS_FORM",i,f.get_attribute("action"),f.get_attribute("method"),json.dumps(fields[:120],ensure_ascii=False))
            except:pass
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if "coraltravel.pl" in u and any(k in blob for k in ["hotel","adult","child","age","passenger","search","traveler","traveller"]):
                    print("CORALGDS_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except:pass
    finally:d.quit()
if __name__=="__main__":main()
