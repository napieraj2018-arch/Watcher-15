import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.tui.pl/last-minute-z-warszawy"

def compact(s):
    return " ".join((s or "").split())

def main():
    opts=Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,2800")
    opts.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=opts)
    try:
        d.get(URL)
        WebDriverWait(d,40).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(5)
        for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed():
                    els[0].click(); time.sleep(1); break
            except: pass
        print("TITLE",d.title)
        print("URL",d.current_url)
        print("INPUTS")
        for el in d.find_elements(By.TAG_NAME,"input"):
            try:
                if el.is_displayed():
                    print(repr({
                      "name":el.get_attribute("name"),
                      "type":el.get_attribute("type"),
                      "placeholder":el.get_attribute("placeholder"),
                      "aria":el.get_attribute("aria-label"),
                      "value":el.get_attribute("value"),
                      "data-testid":el.get_attribute("data-testid"),
                    }))
            except: pass
        print("BUTTONS")
        n=0
        for el in d.find_elements(By.TAG_NAME,"button"):
            try:
                if el.is_displayed():
                    txt=compact(el.text); aria=compact(el.get_attribute("aria-label"))
                    if txt or aria:
                        print(repr({"text":txt[:250],"aria":aria[:250],"testid":el.get_attribute("data-testid")}))
                        n+=1
                        if n>=160: break
            except: pass
        body=d.find_element(By.TAG_NAME,"body").text
        print("LINES")
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["uczest","doros","dzieci","wylot","pobyt","all inclusive","warszawa","radom"]):
                print(line)
        d.save_screenshot("tui-diagnostic.png")
    finally:
        d.quit()
if __name__=="__main__":
    main()
