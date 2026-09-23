import time,json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.grecos.pl/last-minute"
def compact(s): return " ".join((s or "").split())

def main():
    o=Options(); o.add_argument("--headless=new");o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3000");o.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL); WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete"); time.sleep(4)
        for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed(): d.execute_script("arguments[0].click();",els[0]);time.sleep(.5);break
            except: pass

        print("START_URL",d.current_url)
        print("FAMILY_RELATED_BEFORE")
        candidates=[]
        for el in d.find_elements(By.XPATH,"//button|//input|//select|//*[@role='button']"):
            try:
                if not el.is_displayed():continue
                txt=compact(el.text); attrs=" ".join(filter(None,[txt,el.get_attribute("aria-label"),el.get_attribute("name"),el.get_attribute("placeholder"),el.get_attribute("id"),el.get_attribute("class")]))
                if any(k in attrs.lower() for k in ["doros","dzie","osob","uczest","pokoj","pokój","wiek","adult","child","person","room"]):
                    print(repr({"tag":el.tag_name,"text":txt[:250],"name":el.get_attribute("name"),"value":el.get_attribute("value"),"aria":el.get_attribute("aria-label"),"id":el.get_attribute("id"),"html":el.get_attribute("outerHTML")[:1200]}))
                    candidates.append(el)
            except:pass

        clicked=False
        for el in candidates:
            try:
                blob=(" ".join(filter(None,[compact(el.text),el.get_attribute("aria-label"),el.get_attribute("class")]))).lower()
                if any(k in blob for k in ["doros","osob","uczest","person"]):
                    d.execute_script("arguments[0].click();",el);time.sleep(1);clicked=True;break
            except:pass
        print("PICKER_CLICKED",clicked)

        print("FAMILY_RELATED_AFTER_OPEN")
        for el in d.find_elements(By.XPATH,"//button|//input|//select"):
            try:
                if not el.is_displayed():continue
                txt=compact(el.text); attrs=" ".join(filter(None,[txt,el.get_attribute("aria-label"),el.get_attribute("name"),el.get_attribute("placeholder"),el.get_attribute("id"),el.get_attribute("class")]))
                if any(k in attrs.lower() for k in ["doros","dzie","osob","uczest","pokoj","pokój","wiek","adult","child","person","room","lat"]):
                    print(repr({"tag":el.tag_name,"text":txt[:300],"name":el.get_attribute("name"),"value":el.get_attribute("value"),"aria":el.get_attribute("aria-label"),"id":el.get_attribute("id"),"html":el.get_attribute("outerHTML")[:1600]}))
            except:pass

        d.save_screenshot("grecos-family.png")
    finally:d.quit()
if __name__=="__main__":main()
