import json,time,re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.rego-bis.pl/rodzina2plus2"

def compact(s): return " ".join((s or "").split())

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]:
        o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5)
        for b in d.find_elements(By.TAG_NAME,"button"):
            try:
                t=compact(b.text).lower()
                if b.is_displayed() and any(x in t for x in ["akceptuj","zaakceptuj","zgadzam","allow all"]):
                    d.execute_script("arguments[0].click()",b);time.sleep(.5);break
            except:pass
        print("REGO_START",d.current_url,"TITLE",d.title)
        body=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["goście","goscie","dorośli","dzieci","uczest","data urod","wiek","cena razem","zł/os","all inclusive","warszawa","radom"]):
                print("REGO_SIGNAL",line[:1000])
        # Print controls and shortest clickable containers around participant terms.
        for e in d.find_elements(By.XPATH,"//input|//select|//button|//*[@role='button']|//*[@role='combobox']"):
            try:
                txt=compact(e.text)
                blob=" ".join(filter(None,[txt,e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),e.get_attribute("class"),e.get_attribute("value")]))
                if any(k in blob.lower() for k in ["goś","gos","doros","dzie","uczest","guest","adult","child","birth","urodz","wiek","age","person"]):
                    print("REGO_CTRL",json.dumps({"tag":e.tag_name,"displayed":e.is_displayed(),"text":txt[:250],
                      "name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),
                      "placeholder":e.get_attribute("placeholder"),"aria":e.get_attribute("aria-label"),
                      "class":e.get_attribute("class"),"html":(e.get_attribute("outerHTML") or "")[:3000]},ensure_ascii=False))
            except:pass
        nodes=d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'2 doro') or contains(normalize-space(.),'Goście') or contains(normalize-space(.),'Uczestnicy')]")
        nodes=[x for x in nodes if x.is_displayed()]
        nodes.sort(key=lambda x:len(compact(x.text)))
        opened=False
        for e in nodes[:20]:
            try:
                if len(compact(e.text))>300:continue
                print("REGO_OPEN_TRY",e.tag_name,compact(e.text)[:300],(e.get_attribute("outerHTML") or "")[:2400])
                d.execute_script("arguments[0].click()",e);time.sleep(1);opened=True;break
            except:pass
        print("REGO_PARTY_OPENED",opened)
        trigger=d.find_elements(By.CSS_SELECTOR,"[data-search-option-id='participants']")
        if trigger:
            did=trigger[0].get_attribute("aria-controls")
            if did:
                dialogs=d.find_elements(By.ID,did)
                if dialogs:
                    print("REGO_PARTY_DIALOG",json.dumps({
                      "id":did,"text":compact(dialogs[0].text)[:6000],
                      "html":(dialogs[0].get_attribute("outerHTML") or "")[:30000]
                    },ensure_ascii=False))
        for e in d.find_elements(By.XPATH,"//input|//select|//button|//*[@role='button']|//*[@role='combobox']"):
            try:
                if not e.is_displayed():continue
                txt=compact(e.text); html=e.get_attribute("outerHTML") or ""
                blob=" ".join(filter(None,[txt,e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),e.get_attribute("class"),e.get_attribute("value")]))
                if any(k in blob.lower() for k in ["doros","dzie","urodz","wiek","adult","child","birth","age"]) or txt in ["+","-","−"]:
                    print("REGO_AFTER_CTRL",json.dumps({"tag":e.tag_name,"text":txt[:300],"name":e.get_attribute("name"),
                      "id":e.get_attribute("id"),"value":e.get_attribute("value"),"placeholder":e.get_attribute("placeholder"),
                      "aria":e.get_attribute("aria-label"),"class":e.get_attribute("class"),"html":html[:4000]},ensure_ascii=False))
            except:pass
        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or ""
                blob=(u+" "+post).lower()
                if "rego-bis.pl" in u and any(k in blob for k in ["search","filter","offer","guest","adult","child","participant","person","birth"]):
                    key=(u,post)
                    if key not in seen:
                        seen.add(key);print("REGO_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except:pass
        print("REGO_REQ_COUNT",len(seen))
    finally:d.quit()

if __name__=="__main__":main()
