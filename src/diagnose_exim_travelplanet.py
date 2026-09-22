import json, os, time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

SOURCES={
 "exim_pl":"https://www.exim.pl/last-minute",
 "travelplanet_pl":"https://www.travelplanet.pl/wakacje/super-last-minute/",
}

def compact(s): return " ".join((s or "").split())

def main():
    cid=os.environ["CHANNEL_ID"]
    url=SOURCES[cid]
    o=Options()
    o.add_argument("--headless=new"); o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage"); o.add_argument("--window-size=1440,3000")
    o.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=o)
    try:
        d.get(url)
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(5)
        for t in ["Nie zezwalaj","Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","Zezwól na wszystkie","OK"]:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed():
                    d.execute_script("arguments[0].click();",els[0]); time.sleep(.7); break
            except: pass

        print("CHANNEL",cid)
        print("TITLE",d.title)
        print("START_URL",d.current_url)

        # Click likely participant control.
        clicked=None
        needles=["uczest","osób","osoby","doros","podróż"]
        for needle in needles:
            els=d.find_elements(By.XPATH,
                "//*[self::button or @role='button' or self::div or self::span]"
                f"[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'{needle}')]")
            for el in els:
                try:
                    if el.is_displayed() and el.size.get("width",0)>20 and el.size.get("height",0)>15:
                        txt=compact(el.text)
                        if len(txt)>180: continue
                        d.execute_script("arguments[0].click();",el)
                        clicked={"needle":needle,"tag":el.tag_name,"text":txt,"aria":el.get_attribute("aria-label"),"testid":el.get_attribute("data-testid"),"class":el.get_attribute("class")}
                        time.sleep(1.2)
                        raise StopIteration
                except StopIteration: raise
                except: pass
            if clicked: break
        print("PARTICIPANT_CLICK",repr(clicked))

        print("VISIBLE_INPUTS")
        for el in d.find_elements(By.TAG_NAME,"input"):
            try:
                if el.is_displayed():
                    print(repr({
                        "name":el.get_attribute("name"),
                        "type":el.get_attribute("type"),
                        "placeholder":el.get_attribute("placeholder"),
                        "aria":el.get_attribute("aria-label"),
                        "value":el.get_attribute("value"),
                        "id":el.get_attribute("id"),
                        "testid":el.get_attribute("data-testid"),
                        "class":(el.get_attribute("class") or "")[:250],
                    }))
            except: pass

        print("VISIBLE_SELECTS")
        for el in d.find_elements(By.TAG_NAME,"select"):
            try:
                if el.is_displayed():
                    print(repr({
                        "name":el.get_attribute("name"),
                        "aria":el.get_attribute("aria-label"),
                        "value":el.get_attribute("value"),
                        "id":el.get_attribute("id"),
                        "html":el.get_attribute("outerHTML")[:1200],
                    }))
            except: pass

        print("VISIBLE_BUTTONS")
        n=0
        for el in d.find_elements(By.TAG_NAME,"button"):
            try:
                if el.is_displayed():
                    txt=compact(el.text); aria=compact(el.get_attribute("aria-label"))
                    if txt or aria:
                        print(repr({
                           "text":txt[:240],"aria":aria[:240],
                           "id":el.get_attribute("id"),
                           "testid":el.get_attribute("data-testid"),
                           "class":(el.get_attribute("class") or "")[:220],
                           "html":el.get_attribute("outerHTML")[:900],
                        }))
                        n+=1
                        if n>=220: break
            except: pass

        print("RELEVANT_TEXT")
        lines=[x.strip() for x in d.find_element(By.TAG_NAME,"body").text.splitlines() if x.strip()]
        for i,line in enumerate(lines):
            lo=line.lower()
            if any(k in lo for k in ["doros","dzieci","dziecko","wiek","uczest","osób","pokój","wylot","all inclusive","warszawa","radom"]):
                print(f"[{i}] {line[:600]}")

        # Inspect data attributes / test IDs.
        print("DATA_ATTR_ELEMENTS")
        n=0
        for el in d.find_elements(By.CSS_SELECTOR,"[data-testid],[data-test],[data-cy],[aria-label]"):
            try:
                if not el.is_displayed(): continue
                txt=compact(el.text)
                attrs={
                    "tag":el.tag_name,
                    "text":txt[:180],
                    "aria":el.get_attribute("aria-label"),
                    "testid":el.get_attribute("data-testid"),
                    "data-test":el.get_attribute("data-test"),
                    "data-cy":el.get_attribute("data-cy"),
                }
                s=json.dumps(attrs,ensure_ascii=False).lower()
                if any(k in s for k in ["adult","child","dzie","doros","person","guest","uczest","traveler","passenger","room"]):
                    print(repr(attrs)); n+=1
                    if n>=180: break
            except: pass

        d.save_screenshot(f"diag-{cid}.png")
    finally:
        d.quit()

if __name__=="__main__": main()
