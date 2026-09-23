import json,time,re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL='https://www.sunfun.pl/'
def compact(s): return ' '.join((s or '').split())

def click_option(d, wrapper_id, wanted):
    wrapper=d.find_element(By.ID,wrapper_id)
    d.execute_script('arguments[0].click()',wrapper.find_element(By.CSS_SELECTOR,'.Select-control'))
    time.sleep(.6)
    opts=d.find_elements(By.CSS_SELECTOR,'.Select-option')
    print('OPTIONS_FOR',wrapper_id,[compact(x.text) for x in opts if x.is_displayed()][:40])
    for x in opts:
        try:
            if x.is_displayed() and compact(x.text).lower().startswith(wanted.lower()):
                d.execute_script('arguments[0].click()',x);time.sleep(.6);return True
        except:pass
    return False

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
        # exact family: default 2 adults + add 2 children
        overlay=d.find_element(By.CSS_SELECTOR,"[data-cy='children'] .SelectBox_readonly-overlay__ClqUJ");d.execute_script('arguments[0].click()',overlay);time.sleep(.7)
        for _ in range(2):
            add=d.find_element(By.CSS_SELECTOR,"[data-cy='addChild']");d.execute_script('arguments[0].click()',add);time.sleep(.5)
        ok5=click_option(d,'wrapper.rooms[0].children[0].age','5 lat')
        ok7=click_option(d,'wrapper.rooms[0].children[1].age','7 lat')
        print('AGES_SET',ok5,ok7)
        ages=[x.get_attribute('value') for x in d.find_elements(By.CSS_SELECTOR,"input[name^='rooms[0].children'][name$='.age']")]
        print('AGE_VALUES',ages)
        try:d.execute_script('arguments[0].click()',d.find_element(By.CSS_SELECTOR,"[data-cy='buttonKids']"));time.sleep(.5)
        except Exception as e:print('CONFIRM_KIDS_ERR',type(e).__name__)
        # departure: prefer Warszawa; keep all departures only if no exact Warsaw option is exposed
        dep=d.find_element(By.CSS_SELECTOR,"[data-cy='depCity'] .Select-control");d.execute_script('arguments[0].click()',dep);time.sleep(.6)
        depopts=[x for x in d.find_elements(By.CSS_SELECTOR,'.Select-option') if x.is_displayed()]
        print('DEP_OPTIONS',[compact(x.text) for x in depopts][:80])
        chosen=None
        for wanted in ['Warszawa','Warszawa - Radom','Radom','Modlin']:
            for x in depopts:
                try:
                    if wanted.lower() in compact(x.text).lower():
                        chosen=compact(x.text);d.execute_script('arguments[0].click()',x);time.sleep(.6);break
                except:pass
            if chosen:break
        print('DEP_CHOSEN',chosen,'DEP_VALUE',d.find_element(By.CSS_SELECTOR,"input[name='depCity']").get_attribute('value'))
        print('PARTY_BEFORE_SUBMIT',d.find_element(By.CSS_SELECTOR,"input[name='rooms[0].adults']").get_attribute('value'),[x.get_attribute('value') for x in d.find_elements(By.CSS_SELECTOR,"input[name^='rooms[0].children'][name$='.age']")])
        d.get_log('performance')
        d.execute_script('arguments[0].click()',d.find_element(By.CSS_SELECTOR,"[data-cy='tourSearch__btn']"));time.sleep(10)
        print('AFTER_URL',d.current_url)
        print('AFTER_PARTY_INPUTS',[(x.get_attribute('name'),x.get_attribute('value')) for x in d.find_elements(By.CSS_SELECTOR,"input[name^='rooms']")])
        body=d.find_element(By.TAG_NAME,'body').text
        lines=[x.strip() for x in body.splitlines() if x.strip()]
        print('RESULT_LINES')
        for line in lines:
            lo=line.lower()
            if any(k in lo for k in ['2 doros','2 dzieci','5 lat','7 lat','cena razem','łącznie','razem','zł/os','zł / os','all inclusive','warszaw','radom']): print(line[:1000])
        print('OFFER_LINKS')
        n=0
        for a in d.find_elements(By.TAG_NAME,'a'):
            try:
                href=a.get_attribute('href') or '';txt=compact(a.text)
                if href and txt and ('zł' in txt or 'hotel' in href.lower() or 'ofert' in href.lower()):
                    print(repr({'text':txt[:800],'href':href[:1200]}));n+=1
                    if n>=30:break
            except:pass
        print('NETWORK_SEARCH')
        seen=set()
        for row in d.get_log('performance'):
            try:
                m=json.loads(row['message'])['message']
                if m['method']!='Network.requestWillBeSent':continue
                req=m['params']['request'];u=req['url'];lo=u.lower()
                if any(k in lo for k in ['search','tour','offer','room','child']):
                    if u not in seen:
                        print('REQ',req.get('method'),u[:4500],(req.get('postData') or '')[:4500]);seen.add(u)
            except:pass
        d.save_screenshot('sunfun-family.png')
    finally:d.quit()
if __name__=='__main__':main()
