import time,json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains

URL="https://www.grecos.pl/last-minute"
def compact(s): return " ".join((s or "").split())

def dump_inputs(d,label):
    print(label)
    for i,el in enumerate(d.find_elements(By.TAG_NAME,'input')):
        try:
            parent=''
            try: parent=compact(el.find_element(By.XPATH,'./parent::*').text)
            except: pass
            print('INPUT',i,repr({'displayed':el.is_displayed(),'type':el.get_attribute('type'),'name':el.get_attribute('name'),'id':el.get_attribute('id'),'class':el.get_attribute('class'),'value':el.get_attribute('value'),'placeholder':el.get_attribute('placeholder'),'aria':el.get_attribute('aria-label'),'parent':parent[:300],'html':(el.get_attribute('outerHTML') or '')[:1800]}))
        except Exception as e:print('INPUT_ERR',i,type(e).__name__)

def dump_visible(d,label):
    print(label)
    for el in d.find_elements(By.XPATH,"//button|//input|//select|//*[@role='button']|//*[@role='option']|//*[@role='combobox']"):
        try:
            if not el.is_displayed():continue
            txt=compact(el.text); html=el.get_attribute('outerHTML') or ''
            attrs=' '.join(filter(None,[txt,el.get_attribute('aria-label'),el.get_attribute('name'),el.get_attribute('id'),el.get_attribute('class'),el.get_attribute('value'),el.get_attribute('title')]))
            if any(k in attrs.lower() for k in ['doros','dzie','wiek','lat','osob','plus','minus','adult','child']) or txt in ['+','−','-']:
                print('CTRL',repr({'tag':el.tag_name,'text':txt[:250],'name':el.get_attribute('name'),'id':el.get_attribute('id'),'class':el.get_attribute('class'),'value':el.get_attribute('value'),'aria':el.get_attribute('aria-label'),'html':html[:2400]}))
        except:pass

def passenger_box(d):
    vals=d.find_elements(By.XPATH,"//span[contains(@class,'input-box__value-text') and contains(normalize-space(.),'Dorośli')]")
    vals=[v for v in vals if v.is_displayed()]
    if not vals:return None
    return vals[0].find_element(By.XPATH,"./ancestor::div[contains(concat(' ',normalize-space(@class),' '),' search__input-box ')][1]")

def open_passengers(d):
    box=passenger_box(d)
    if box is None:return False
    print('PASSENGER_BOX_BEFORE',box.get_attribute('outerHTML')[:5000])
    body=box.find_element(By.CSS_SELECTOR,'.input-box__body')
    opened=False
    for mode in ['native','actions','js','box-native']:
        try:
            if mode=='native': body.click()
            elif mode=='actions': ActionChains(d).move_to_element(body).click().perform()
            elif mode=='js': d.execute_script('arguments[0].click()',body)
            else: box.click()
            time.sleep(1)
            vis=[]
            for e in d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Liczba dzieci') or contains(normalize-space(.),'Wiek dziecka') or (self::button and normalize-space(.)='+')]"):
                try:
                    if e.is_displayed():vis.append((e.tag_name,compact(e.text)[:200],e.get_attribute('class')))
                except:pass
            print('OPEN_MODE',mode,'VISIBLE_FAMILY_CONTROLS',vis[:30])
            if vis:opened=True;break
        except Exception as e:print('OPEN_MODE_ERR',mode,type(e).__name__,str(e)[:180])
    print('PASSENGER_BOX_AFTER',box.get_attribute('outerHTML')[:9000])
    return opened

def click_child_plus(d):
    # Prefer controls whose nearby text explicitly identifies the child counter.
    for attempt in range(2):
        candidates=d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Liczba dzieci') or contains(normalize-space(.),'Dzieci')]")
        candidates=[x for x in candidates if x.is_displayed() and len(compact(x.text))<500]
        candidates.sort(key=lambda x:len(compact(x.text)))
        clicked=False
        for sec in candidates:
            try:
                txt=compact(sec.text)
                buttons=sec.find_elements(By.XPATH,'.//button|.//*[@role="button"]')
                buttons=[b for b in buttons if b.is_displayed() and b.is_enabled()]
                plus=[b for b in buttons if compact(b.text) in ['+','＋'] or 'plus' in ((b.get_attribute('class') or '')+' '+(b.get_attribute('aria-label') or '')).lower()]
                if not plus and len(buttons)>=2:plus=[buttons[-1]]
                for b in reversed(plus):
                    if 'search__submit' in (b.get_attribute('class') or ''):continue
                    print('CHILD_PLUS',attempt,repr({'section':txt,'button':compact(b.text),'html':b.get_attribute('outerHTML')[:1200]}))
                    b.click();time.sleep(1);clicked=True;break
                if clicked:break
            except Exception as e:print('CHILD_PLUS_ERR',type(e).__name__,str(e)[:150])
        print('CHILD_PLUS_RESULT',attempt,clicked)
        if not clicked:return False
    return True

def set_hidden_or_visible_age(d,target,index):
    # First try any explicit input whose parent/attributes say child age.
    candidates=[]
    for el in d.find_elements(By.TAG_NAME,'input'):
        try:
            parent=''
            try:parent=compact(el.find_element(By.XPATH,'./parent::*').text)
            except:pass
            blob=' '.join(filter(None,[el.get_attribute('name'),el.get_attribute('id'),el.get_attribute('class'),el.get_attribute('placeholder'),el.get_attribute('aria-label'),parent])).lower()
            if ('wiek' in blob and 'dzie' in blob) or 'childage' in blob or 'child-age' in blob:candidates.append(el)
        except:pass
    print('AGE_INPUT_CANDIDATES',[(x.get_attribute('name'),x.get_attribute('value'),x.is_displayed(),(x.get_attribute('outerHTML') or '')[:600]) for x in candidates])
    if index<len(candidates):
        el=candidates[index]
        try:
            d.execute_script("arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",el,target)
            time.sleep(.5);print('AGE_INPUT_SET',index,target,el.get_attribute('value'));return True
        except Exception as e:print('AGE_INPUT_SET_ERR',type(e).__name__,str(e)[:150])
    return False

def apply_search(d):
    for txt in ['Zastosuj','Gotowe','Zatwierdź','Wybierz']:
        for el in d.find_elements(By.XPATH,f"//*[self::button or @role='button'][contains(normalize-space(.),'{txt}')]"):
            try:
                if el.is_displayed() and el.is_enabled():print('LOCAL_APPLY',txt);el.click();time.sleep(1);break
            except:pass
    es=d.find_elements(By.CSS_SELECTOR,'button.search__submit')
    if es and es[0].is_displayed():es[0].click();time.sleep(5);return True
    return False

def dump_api(d):
    seen=set();found=[]
    for row in d.get_log('performance'):
        try:
            m=json.loads(row['message'])['message']
            if m.get('method')!='Network.responseReceived':continue
            u=m['params']['response'].get('url','')
            if ('OffersList/LoadMoreOffers' in u or '/api/' in u) and u not in seen:
                seen.add(u)
                if 'OffersList/LoadMoreOffers' in u:found.append(u);print('OFFERS_API',u)
                elif any(k in u.lower() for k in ['offer','search','filter']):print('RELATED_API',u)
        except:pass
    return found

def main():
    o=Options();o.add_argument('--headless=new');o.add_argument('--no-sandbox');o.add_argument('--disable-dev-shm-usage');o.add_argument('--window-size=1440,3000');o.add_argument('--lang=pl-PL');o.set_capability('goog:loggingPrefs',{'performance':'ALL'})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete');time.sleep(5)
        for t in ['Akceptuję','Akceptuj','Zgadzam się','Zaakceptuj wszystkie','OK']:
            try:
                es=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if es and es[0].is_displayed():es[0].click();time.sleep(.5);break
            except:pass
        print('START_URL',d.current_url);dump_inputs(d,'ALL_INPUTS_BEFORE')
        print('PARTY_OPENED',open_passengers(d));dump_visible(d,'PARTY_UI_BEFORE');dump_inputs(d,'ALL_INPUTS_AFTER_OPEN')
        plus_ok=click_child_plus(d);print('CHILD_COUNT_CHANGED',plus_ok);dump_visible(d,'PARTY_UI_AFTER_PLUS');dump_inputs(d,'ALL_INPUTS_AFTER_PLUS')
        age5=set_hidden_or_visible_age(d,'5',0);age7=set_hidden_or_visible_age(d,'7',1);print('AGES_CHANGED',{'5':age5,'7':age7})
        print('APPLIED',apply_search(d));print('FINAL_URL',d.current_url)
        body=compact(d.find_element(By.TAG_NAME,'body').text)
        for needle in ['Dorośli 2','Dzieci 2','5 lat','7 lat']:print('BODY_SIGNAL',needle,needle.lower() in body.lower())
        apis=dump_api(d);print('OFFERS_API_COUNT',len(apis));d.save_screenshot('grecos-family.png')
    finally:d.quit()
if __name__=='__main__':main()
