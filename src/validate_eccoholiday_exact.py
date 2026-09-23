import json,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.eccoholiday.com/"
def compact(s):return " ".join((s or "").split())

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]:o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5)
        print("ECCO_START",d.current_url,d.title)
        body=d.find_element(By.TAG_NAME,"body").text
        for s in ["Dorośli","Dzieci","Last Minute","All inclusive","Lotnisko"]:
            print("ECCO_SIGNAL",s,s.lower() in body.lower())
        for e in d.find_elements(By.XPATH,"//input|//select|//button"):
            try:
                txt=compact(e.text);blob=" ".join(filter(None,[txt,e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("value"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),e.get_attribute("class")]))
                if any(k in blob.lower() for k in ["doros","dzie","child","adult","wiek","age","urodz","birth"]):
                    print("ECCO_CTRL",json.dumps({"tag":e.tag_name,"text":txt[:200],"name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),"placeholder":e.get_attribute("placeholder"),"aria":e.get_attribute("aria-label"),"class":e.get_attribute("class"),"html":(e.get_attribute("outerHTML") or "")[:2400]},ensure_ascii=False))
            except:pass
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if "eccoholiday.com" in u and any(k in blob for k in ["adult","child","age","search","offer","price","person"]):
                    print("ECCO_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except:pass
    finally:d.quit()
if __name__=="__main__":main()
