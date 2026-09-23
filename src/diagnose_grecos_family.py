import time,json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.grecos.pl/last-minute"
def compact(s): return " ".join((s or "").split())

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
    d.execute_script('arguments[0].click()',body);time.sleep(1.5)
    print('PASSENGER_BOX_AFTER',box.get_attribute('outerHTML')[:9000])
    return True

def click_child_plus(d):
    box=passenger_box(d)
    if box is None:return False
    root=box
    for attempt in range(2):
        candidates=root.find_elements(By.XPATH,".//*[contains(normalize-space(.),'Dzieci')]")
        candidates=[x for x in candidates if x.is_displayed() and len(compact(x.text))<300]
        candidates.sort(key=lambda x:len(compact(x.text)))
        clicked=False
        for sec in candidates:
            try:
                txt=compact(sec.text)
                buttons=sec.find_elements(By.XPATH,'.//button|.//*[@role="button"]')
                buttons=[b for b in buttons if b.is_displayed() and b.is_enabled()]
                plus=[b for b in buttons if compact(b.text) in ['+','＋'] or 'plus' in ((b.get_attribute('class') or '')+' '+(b.get_attribute('aria-label') or '')).lower()]
                if not plus and len(buttons)>=2: plus=[buttons[-1]]
                if not plus:continue
                b=plus[-1]
                if 'search__submit' in (b.get_attribute('class') or ''):continue
                print('CHILD_PLUS',attempt,repr({'section':txt,'button':compact(b.text),'html':b.get_attribute('outerHTML')[:1200]}))
                d.execute_script('arguments[0].click()',b);time.sleep(1);clicked=True;break
            except Exception as e:print('CHILD_PLUS_ERR',type(e).__name__,str(e)[:150])
        print('CHILD_PLUS_RESULT',attempt,clicked)
        if not clicked:return False
    return True

def choose_age(d,target,which):
    box=passenger_box(d)
    fields=[]
    for el in box.find_elements(By.XPATH,".//*[self::button or @role='button' or @role='combobox' or self::select or contains(@class,'select')]"):
        try:
            if not el.is_displayed():continue
            s=(compact(el.text)+' '+(el.get_attribute('class') or '')+' '+(el.get_attribute('aria-label') or '')).lower()
            if any(k in s for k in ['wiek','lat','age','dziecko']):fields.append(el)
        except:pass
    print('AGE_FIELDS',[(compact(x.text),x.get_attribute('class')) for x in fields[:20]])
    if which>=len(fields):return False
    try:d.execute_script('arguments[0].click()',fields[which]);time.sleep(.7)
    except:return False
    opts=d.find_elements(By.XPATH,f"//*[(@role='option' or self::li or self::button or self::div or self::span) and (normalize-space(.)='{target}' or normalize-space(.)='{target} lat' or contains(normalize-space(.),'{target} lat'))]")
    opts=[o for o in opts if o.is_displayed() and len(compact(o.text))<35]
    print('AGE_OPTIONS',target,[(o.tag_name,compact(o.text),o.get_attribute('class')) for o in opts[:20]])
    if not opts:return False
    d.execute_script('arguments[0].click()',opts[0]);time.sleep(.7);return True

def apply_search(d):
    for txt in ['Zastosuj','Gotowe','Zatwierdź','Wybierz']:
        es=d.find_elements(By.XPATH,f"//*[self::button or @role='button'][contains(normalize-space(.),'{txt}')]")
        for el in es:
            try:
                if el.is_displayed() and el.is_enabled():print('LOCAL_APPLY',txt);d.execute_script('arguments[0].click()',el);time.sleep(1);break
            except:pass
    es=d.find_elements(By.CSS_SELECTOR,'button.search__submit')
    if es and es[0].is_displayed():d.execute_script('arguments[0].click()',es[0]);time.sleep(4);return True
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
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3000");o.add_argument("--lang=pl-PL")
    o.set_capability('goog:loggingPrefs',{'performance':'ALL'})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=='complete');time.sleep(5)
        for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
            try:
                es=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if es and es[0].is_displayed():d.execute_script('arguments[0].click()',es[0]);time.sleep(.5);break
            except:pass
        print('START_URL',d.current_url);print('PARTY_OPENED',open_passengers(d));dump_visible(d,'PARTY_UI_BEFORE')
        plus_ok=click_child_plus(d);print('CHILD_COUNT_CHANGED',plus_ok);dump_visible(d,'PARTY_UI_AFTER_PLUS')
        age5=choose_age(d,'5',0);age7=choose_age(d,'7',1);print('AGES_CHANGED',{'5':age5,'7':age7});dump_visible(d,'PARTY_UI_AFTER_AGES')
        print('APPLIED',apply_search(d));print('FINAL_URL',d.current_url)
        body=compact(d.find_element(By.TAG_NAME,'body').text)
        for needle in ['Dorośli 2','Dzieci 2','5 lat','7 lat']:
            print('BODY_SIGNAL',needle,needle.lower() in body.lower())
        apis=dump_api(d);print('OFFERS_API_COUNT',len(apis));d.save_screenshot('grecos-family.png')
    finally:d.quit()
if __name__=='__main__':main()
