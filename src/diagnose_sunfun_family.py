import json,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL='https://www.sunfun.pl/'
def compact(s): return ' '.join((s or '').split())

def dump(d,label):
    print(label)
    for el in d.find_elements(By.XPATH,"//button|//input|//select|//*[@role='option']|//*[@role='combobox']|//*[@data-cy]"):
        try:
            if not el.is_displayed(): continue
            txt=compact(el.text); blob=' '.join(filter(None,[txt,el.get_attribute('aria-label'),el.get_attribute('name'),el.get_attribute('id'),el.get_attribute('class'),el.get_attribute('data-cy'),el.get_attribute('value')])).lower()
            if any(k in blob for k in ['dzie','doros','wiek','pok','room','adult','child','person','age','toursearch','lat']):
                print(repr({'tag':el.tag_name,'text':txt[:500],'name':el.get_attribute('name'),'value':el.get_attribute('value'),'aria':el.get_attribute('aria-label'),'id':el.get_attribute('id'),'cy':el.get_attribute('data-cy'),'class':el.get_attribute('class'),'html':el.get_attribute('outerHTML')[:3500]}))
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
        overlay=d.find_element(By.CSS_SELECTOR,"[data-cy='children'] .SelectBox_readonly-overlay__ClqUJ");d.execute_script('arguments[0].click()',overlay);time.sleep(1)
        add=d.find_element(By.CSS_SELECTOR,"[data-cy='addChild']")
        for i in range(2):
            d.execute_script('arguments[0].click()',add);time.sleep(.8)
            add=d.find_element(By.CSS_SELECTOR,"[data-cy='addChild']")
            print('ADDED_CHILD',i+1)
            print('CHILDREN_HTML',d.find_element(By.CSS_SELECTOR,"[data-cy='children-wrapper']").get_attribute('outerHTML')[:18000])
        dump(d,'SUNFUN_AFTER_TWO_CHILDREN')
        print('ALL_NAMED_INPUTS')
        for el in d.find_elements(By.XPATH,"//input[@name]|//select[@name]"):
            try: print(repr({'tag':el.tag_name,'name':el.get_attribute('name'),'value':el.get_attribute('value'),'type':el.get_attribute('type'),'html':el.get_attribute('outerHTML')[:2500]}))
            except:pass
        print('DEP_HTML',d.find_element(By.CSS_SELECTOR,"[data-cy='depCity']").get_attribute('outerHTML')[:12000])
        print('PAGE_LINES')
        for line in [x.strip() for x in d.find_element(By.TAG_NAME,'body').text.splitlines() if x.strip()]:
            if any(k in line.lower() for k in ['dzie','lat','wiek','doros','pokój','pokoj']): print(line[:700])
        d.save_screenshot('sunfun-family.png')
    finally:d.quit()
if __name__=='__main__':main()
