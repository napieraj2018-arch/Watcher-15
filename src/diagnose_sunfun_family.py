import json,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys

URL='https://www.sunfun.pl/'
def compact(s): return ' '.join((s or '').split())

def dump(d,label):
    print(label)
    for el in d.find_elements(By.XPATH,"//button|//input|//*[@role='option']|//*[@role='combobox']|//*[@data-cy]"):
        try:
            if not el.is_displayed(): continue
            txt=compact(el.text); blob=' '.join(filter(None,[txt,el.get_attribute('aria-label'),el.get_attribute('name'),el.get_attribute('id'),el.get_attribute('class'),el.get_attribute('data-cy'),el.get_attribute('value')])).lower()
            if any(k in blob for k in ['dzie','doros','wiek','pok','room','adult','child','person','age','toursearch']):
                print(repr({'tag':el.tag_name,'text':txt[:500],'name':el.get_attribute('name'),'value':el.get_attribute('value'),'aria':el.get_attribute('aria-label'),'id':el.get_attribute('id'),'cy':el.get_attribute('data-cy'),'class':el.get_attribute('class'),'html':el.get_attribute('outerHTML')[:2500]}))
        except: pass

def main():
    o=Options();o.add_argument('--headless=new');o.add_argument('--no-sandbox');o.add_argument('--disable-dev-shm-usage');o.add_argument('--window-size=1440,3200');o.add_argument('--lang=pl-PL')
    o.set_capability('goog:loggingPrefs',{'performance':'ALL'})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete');time.sleep(5)
        for t in ['Akceptuję','Akceptuj','Zgadzam się','Zaakceptuj wszystkie','OK']:
            try:
                e=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if e and e[0].is_displayed(): d.execute_script('arguments[0].click()',e[0]);time.sleep(.5);break
            except:pass
        dump(d,'SUNFUN_BEFORE')
        ch=d.find_element(By.CSS_SELECTOR,"[data-cy='children']")
        print('CHILD_WRAPPER',ch.get_attribute('outerHTML')[:12000])
        # try overlay first, then control/input
        for css in ["[data-cy='children'] .SelectBox_readonly-overlay__ClqUJ","[data-cy='children'] .Select-control","[data-cy='children'] [role='combobox']"]:
            try:
                e=d.find_element(By.CSS_SELECTOR,css);d.execute_script('arguments[0].click()',e);time.sleep(1);print('CLICKED_CHILD',css);break
            except Exception as ex: print('CHILD_CLICK_FAIL',css,type(ex).__name__)
        dump(d,'SUNFUN_AFTER_CHILD_CLICK')
        print('OPTIONS')
        for el in d.find_elements(By.XPATH,"//*[@role='option']|//*[contains(@class,'Select-option')]"):
            try:
                if el.is_displayed(): print(repr({'text':compact(el.text),'html':el.get_attribute('outerHTML')[:1600]}))
            except:pass
        print('PAGE_LINES')
        for line in [x.strip() for x in d.find_element(By.TAG_NAME,'body').text.splitlines() if x.strip()]:
            if any(k in line.lower() for k in ['dzie','lat','wiek','doros','pokój','pokoj']): print(line[:700])
        print('DEP_HTML',d.find_element(By.CSS_SELECTOR,"[data-cy='depCity']").get_attribute('outerHTML')[:12000])
        print('SUNFUN_NETWORK_ASSETS')
        for row in d.get_log('performance'):
            try:
                m=json.loads(row['message'])['message']
                if m['method']!='Network.requestWillBeSent':continue
                u=m['params']['request']['url'];lo=u.lower()
                if any(k in lo for k in ['toursearch','search','room','child','adult','departure','depcity']): print(u[:4000])
            except:pass
        d.save_screenshot('sunfun-family.png')
    finally:d.quit()
if __name__=='__main__':main()
