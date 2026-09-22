import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.travelplanet.pl/wakacje/super-last-minute/"

def compact(s): return " ".join((s or "").split())

def main():
    o=Options(); o.add_argument("--headless=new"); o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage"); o.add_argument("--window-size=1440,3000"); o.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL); WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete"); time.sleep(4)
        for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed(): d.execute_script("arguments[0].click();",els[0]);time.sleep(.6);break
            except:pass

        child=d.find_element(By.CSS_SELECTOR,"[data-testid='person-textbox-control-children']")
        d.execute_script("arguments[0].click();",child);time.sleep(1)
        print("PICKER_OPEN_URL",d.current_url)

        print("PICKER_ELEMENTS")
        n=0
        for el in d.find_elements(By.CSS_SELECTOR,"[data-testid],button,input,select"):
            try:
                if not el.is_displayed(): continue
                txt=compact(el.text)
                attrs=" ".join(filter(None,[el.get_attribute("data-testid"),el.get_attribute("name"),el.get_attribute("aria-label"),el.get_attribute("placeholder"),txt]))
                if any(k in attrs.lower() for k in ["person","child","adult","dzie","doros","wiek","age","room","pok"]):
                    print(repr({"tag":el.tag_name,"text":txt[:240],"testid":el.get_attribute("data-testid"),"name":el.get_attribute("name"),"value":el.get_attribute("value"),"aria":el.get_attribute("aria-label"),"html":el.get_attribute("outerHTML")[:1200]}));n+=1
                    if n>=120:break
            except:pass

        # Click likely child increment twice.
        pluses=[]
        for el in d.find_elements(By.TAG_NAME,"button"):
            try:
                if not el.is_displayed(): continue
                s=" ".join(filter(None,[compact(el.text),el.get_attribute("aria-label"),el.get_attribute("data-testid"),el.get_attribute("class")])).lower()
                if ("child" in s or "dzie" in s) and ("plus" in s or "add" in s or "increment" in s or "+"==compact(el.text)):
                    pluses.append(el)
            except:pass
        print("CHILD_PLUS_COUNT",len(pluses))
        if pluses:
            for _ in range(2):
                d.execute_script("arguments[0].click();",pluses[-1]);time.sleep(.4)

        print("AFTER_CHILDREN_ELEMENTS")
        for el in d.find_elements(By.XPATH,"//select|//input|//button"):
            try:
                if not el.is_displayed(): continue
                txt=compact(el.text)
                attrs=" ".join(filter(None,[el.get_attribute("data-testid"),el.get_attribute("name"),el.get_attribute("aria-label"),el.get_attribute("placeholder"),txt]))
                if any(k in attrs.lower() for k in ["age","wiek","child","dzie"]):
                    print(repr({"tag":el.tag_name,"text":txt[:240],"testid":el.get_attribute("data-testid"),"name":el.get_attribute("name"),"value":el.get_attribute("value"),"aria":el.get_attribute("aria-label"),"html":el.get_attribute("outerHTML")[:1400]}))
            except:pass

        d.save_screenshot("travelplanet-family.png")
    finally:d.quit()
if __name__=="__main__":main()
