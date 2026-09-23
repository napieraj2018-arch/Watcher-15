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
    o.set_capability('goog:loggingPrefs', {'performance':'ALL'})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL); WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete"); time.sleep(5)
        for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed(): d.execute_script("arguments[0].click();",els[0]);time.sleep(.5);break
            except: pass

        print("START_URL",d.current_url)
        print("TITLE",d.title)
        print("IFRAMES")
        for i,f in enumerate(d.find_elements(By.TAG_NAME,'iframe')):
            print(i,repr({'src':f.get_attribute('src'),'title':f.get_attribute('title'),'name':f.get_attribute('name'),'id':f.get_attribute('id')}))

        print("VISIBLE_CONTROLS")
        n=0
        for el in d.find_elements(By.XPATH,"//button|//input|//select|//*[@role='button']|//a"):
            try:
                if not el.is_displayed():continue
                txt=compact(el.text); attrs=" ".join(filter(None,[txt,el.get_attribute("aria-label"),el.get_attribute("name"),el.get_attribute("placeholder"),el.get_attribute("id"),el.get_attribute("class"),el.get_attribute('href'),el.get_attribute('data-testid')]))
                if txt or el.get_attribute('value') or el.get_attribute('placeholder'):
                    print(repr({"tag":el.tag_name,"text":txt[:300],"name":el.get_attribute("name"),"value":el.get_attribute("value"),"aria":el.get_attribute("aria-label"),"id":el.get_attribute("id"),"href":(el.get_attribute('href') or '')[:600],"testid":el.get_attribute('data-testid'),"html":el.get_attribute("outerHTML")[:1600]}));n+=1
                    if n>=260:break
            except:pass

        print('FORMS')
        for i,f in enumerate(d.find_elements(By.TAG_NAME,'form')):
            try: print('FORM',i,f.get_attribute('outerHTML')[:16000])
            except: pass

        print('BODY_SIGNAL_LINES')
        for line in [x.strip() for x in d.find_element(By.TAG_NAME,'body').text.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ['doros','dzie','osob','uczest','wylot','warszaw','radom','all inclusive','cena','szukaj','filtr']): print(line[:800])

        print('STORAGE')
        for kind,expr in [('local','return JSON.stringify(localStorage)'),('session','return JSON.stringify(sessionStorage)')]:
            try: print(kind,d.execute_script(expr)[:25000])
            except Exception as e: print(kind,'ERR',type(e).__name__)

        d.save_screenshot("grecos-family.png")
    finally:d.quit()
if __name__=="__main__":main()
