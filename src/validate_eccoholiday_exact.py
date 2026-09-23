import json,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

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
        children=d.find_elements(By.ID,"searchWindow_main_children")
        if children:
            d.execute_script("arguments[0].click()",children[0]);time.sleep(1)
            print("ECCO_CHILD_PICKER_OPEN",True)
            for el in d.find_elements(By.XPATH,"//input|//select|//button|//*[@role='button']"):
                try:
                    if not el.is_displayed():continue
                    txt=compact(el.text)
                    blob=" ".join(filter(None,[txt,el.get_attribute("name"),el.get_attribute("id"),el.get_attribute("value"),el.get_attribute("placeholder"),el.get_attribute("aria-label"),el.get_attribute("class")]))
                    if any(k in blob.lower() for k in ["dzie","child","wiek","age","urodz","birth"]) or txt in ["+","-","−"]:
                        print("ECCO_PICKER_CTRL",json.dumps({"tag":el.tag_name,"text":txt[:220],"name":el.get_attribute("name"),"id":el.get_attribute("id"),"value":el.get_attribute("value"),"placeholder":el.get_attribute("placeholder"),"aria":el.get_attribute("aria-label"),"class":el.get_attribute("class"),"html":(el.get_attribute("outerHTML") or "")[:2800]},ensure_ascii=False))
                except:pass
        # Set exact child ages in Ecco's canonical picker: first child 5, second 7,
        # remaining child slots empty. This is the participant state we must
        # later see serialized by the backend before trusting any price.
        age_values=[]
        for idx,target in [(1,"5"),(2,"7"),(3,""),(4,"")]:
            els=d.find_elements(By.ID,f"searchWindow_main_chd_{idx}")
            if not els:continue
            e=els[0]
            try:
                Select(e).select_by_value(target)
                d.execute_script("arguments[0].dispatchEvent(new Event('change',{bubbles:true}))",e)
                time.sleep(.5)
                age_values.append(e.get_attribute("value"))
                print("ECCO_AGE_SET",idx,target,e.get_attribute("value"))
            except Exception as ex:
                print("ECCO_AGE_SET_ERR",idx,type(ex).__name__,str(ex)[:160])
        print("ECCO_EXACT_AGES",age_values)
        time.sleep(1)
        try:
            print("ECCO_CHILD_LABEL_AFTER",d.find_element(By.ID,"searchWindow_main_children").get_attribute("value"))
        except:pass

        # Clear startup noise, then submit the real search so the exact
        # participant serialization and offer endpoint become visible.
        try:d.get_log("performance")
        except:pass
        clicked=False
        for b in d.find_elements(By.XPATH,"//button|//input[@type='button']|//input[@type='submit']|//a"):
            try:
                if not b.is_displayed():continue
                txt=(compact(b.text)+" "+(b.get_attribute("value") or "")+" "+(b.get_attribute("id") or "")).lower()
                if "szukaj" in txt or "searchwindow_main_search" in txt:
                    print("ECCO_SEARCH_TRY",compact(txt)[:400])
                    d.execute_script("arguments[0].click()",b);clicked=True;break
            except:pass
        print("ECCO_SEARCH_CLICKED",clicked)
        time.sleep(8)
        print("ECCO_FINAL_URL",d.current_url)
        try:
            body2=d.find_element(By.TAG_NAME,"body").text
            for line in [x.strip() for x in body2.splitlines() if x.strip()]:
                lo=line.lower()
                if any(k in lo for k in ["2 doros","dzieci","5 lat","7 lat","all inclusive","cena","zł","dostęp"]):
                    print("ECCO_RESULT",line[:1000])
        except:pass
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
