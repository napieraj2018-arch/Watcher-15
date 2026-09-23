import json,time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys

URL="https://oasis.pl/"

def compact(s):
    return " ".join((s or "").split())

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3000","--lang=pl-PL"]:
        o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL)
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(4)
        for b in d.find_elements(By.TAG_NAME,"button"):
            try:
                if b.is_displayed() and "Zaakceptuj" in compact(b.text):
                    d.execute_script("arguments[0].click()",b);time.sleep(.4);break
            except: pass

        root=[x for x in d.find_elements(By.CSS_SELECTOR,".participants") if x.is_displayed()][0]
        d.execute_script("arguments[0].click()",root.find_element(By.CSS_SELECTOR,".mainInput"))
        time.sleep(.8)
        root=[x for x in d.find_elements(By.CSS_SELECTOR,".participants") if x.is_displayed()][0]

        child=None
        for row in root.find_elements(By.CSS_SELECTOR,".inputWrapper"):
            try:
                if compact(row.find_element(By.CSS_SELECTOR,".title").text)=="Dzieci":
                    child=row;break
            except: pass
        print("OASIS2_CHILD_ROW",child is not None)
        if child is None:return
        plus=child.find_elements(By.CSS_SELECTOR,"button.inputButton")[-1]
        for i in range(2):
            d.execute_script("arguments[0].click()",plus);time.sleep(.6)
            val=compact(child.find_element(By.CSS_SELECTOR,".inputValue").text)
            print("OASIS2_CHILD_COUNT",i+1,val)

        inputs=[x for x in root.find_elements(By.CSS_SELECTOR,"input.ageInput") if x.is_displayed()]
        print("OASIS2_AGE_INPUT_COUNT",len(inputs))
        pairs=[("01012021","01.01.2021"),("01012019","01.01.2019")]
        oks=[]
        for i,(e,pair) in enumerate(zip(inputs,pairs)):
            keys,want=pair
            e.click();e.send_keys(Keys.CONTROL,"a");e.send_keys(Keys.BACKSPACE)
            e.send_keys(keys);e.send_keys(Keys.TAB);time.sleep(.7)
            got=e.get_attribute("value");ok=got==want;oks.append(ok)
            print("OASIS2_DOB",i+1,want,got,ok)

        root=[x for x in d.find_elements(By.CSS_SELECTOR,".participants") if x.is_displayed()][0]
        confirm=root.find_element(By.CSS_SELECTOR,"button.confirmButton")
        disabled=confirm.get_attribute("disabled")
        print("OASIS2_CONFIRM_DISABLED",disabled)
        confirmed=False
        if disabled is None and oks==[True,True]:
            d.execute_script("arguments[0].click()",confirm);time.sleep(1);confirmed=True
        print("OASIS2_CONFIRMED",confirmed)
        label=d.find_element(By.CSS_SELECTOR,".participants .mainInput")
        print("OASIS2_PARTY_LABEL",compact(label.text))

        d.get_log("performance")
        search=[x for x in d.find_elements(By.CSS_SELECTOR,"button.searchButton") if x.is_displayed()]
        if search and confirmed:
            d.execute_script("arguments[0].click()",search[0]);time.sleep(8)
            print("OASIS2_SEARCH_CLICKED",True)
        else:
            print("OASIS2_SEARCH_CLICKED",False)

        family_payload=None
        for row in d.get_log("performance"):
            try:
                msg=json.loads(row["message"])["message"]
                if msg.get("method")!="Network.requestWillBeSent":continue
                req=msg["params"]["request"]
                if "/api-bv/search-search" in req.get("url",""):
                    raw=req.get("postData") or ""
                    print("OASIS2_FAMILY_PAYLOAD",raw)
                    try:
                        p=json.loads(raw)
                        if str(p.get("adults"))=="2" and str(p.get("infants"))=="5,7":
                            family_payload=p
                    except: pass
            except: pass

        if family_payload:
            sess=requests.Session()
            for cookie in d.get_cookies():
                sess.cookies.set(cookie["name"],cookie["value"])
            headers={"User-Agent":d.execute_script("return navigator.userAgent"),
                     "Referer":"https://oasis.pl/","Content-Type":"application/json"}
            for label,payload in [("FAMILY",dict(family_payload)),("ADULTS",{k:v for k,v in family_payload.items() if k!="infants"})]:
                r=sess.post("https://oasis.pl/api-bv/search-search",json=payload,headers=headers,timeout=35)
                print("OASIS2_API_STATUS",label,r.status_code,len(r.content))
                print("OASIS2_API_HEAD",label,compact(r.text)[:16000])
    finally:
        d.quit()

if __name__=="__main__":
    main()
