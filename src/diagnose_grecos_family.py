import time,json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select

URL="https://www.grecos.pl/last-minute"
def compact(s): return " ".join((s or "").split())

def dump_controls(d,label):
    print(label)
    for el in d.find_elements(By.XPATH,"//button|//input|//select|//*[@role='button']|//*[@role='option']|//*[@role='combobox']"):
        try:
            if not el.is_displayed():continue
            txt=compact(el.text)
            attrs=' '.join(filter(None,[txt,el.get_attribute('aria-label'),el.get_attribute('name'),el.get_attribute('id'),el.get_attribute('class'),el.get_attribute('value'),el.get_attribute('title')]))
            if any(k in attrs.lower() for k in ['doros','dzie','wiek','lat','osob','plus','minus','adult','child','5','7']):
                print('CTRL',repr({'tag':el.tag_name,'text':txt[:250],'name':el.get_attribute('name'),'id':el.get_attribute('id'),'class':el.get_attribute('class'),'value':el.get_attribute('value'),'aria':el.get_attribute('aria-label'),'title':el.get_attribute('title'),'html':el.get_attribute('outerHTML')[:2200]}))
        except:pass

def smallest_visible_with_text(d,needle):
    xs=d.find_elements(By.XPATH,f"//*[contains(normalize-space(.),'{needle}')]")
    xs=[x for x in xs if x.is_displayed()]
    xs.sort(key=lambda x:len(compact(x.text)))
    return xs

def click_child_plus(d):
    # Locate the smallest visible section containing the Dzieci counter and click
    # the right-most enabled button in that section. Repeat twice for two children.
    for attempt in range(2):
        done=False
        for el in smallest_visible_with_text(d,'Dzieci')[:20]:
            try:
                t=compact(el.text)
                if len(t)>500:continue
                buttons=el.find_elements(By.XPATH,'.//button|.//*[@role="button"]')
                buttons=[b for b in buttons if b.is_displayed() and b.is_enabled()]
                if not buttons:continue
                print('CHILD_SECTION',attempt,repr({'text':t[:500],'html':el.get_attribute('outerHTML')[:2500],'buttons':[compact(b.text) or b.get_attribute('aria-label') for b in buttons]}))
                d.execute_script('arguments[0].click()',buttons[-1]);time.sleep(1);done=True;break
            except Exception as e: print('CHILD_PLUS_ERR',type(e).__name__,str(e)[:150])
        print('CHILD_PLUS_RESULT',attempt,done)
        if not done:return False
    return True

def set_child_ages(d):
    changed=[]
    sels=[s for s in d.find_elements(By.TAG_NAME,'select') if s.is_displayed()]
    for idx,s in enumerate(sels):
        try:
            opts=[compact(o.text) for o in s.find_elements(By.TAG_NAME,'option')]
            if any('5' in x for x in opts) and any('7' in x for x in opts):
                target='5' if len(changed)==0 else '7'
                sel=Select(s)
                option=next((o for o in sel.options if compact(o.text).startswith(target+' ') or compact(o.text)==target or compact(o.text).startswith(target+' lat')),None)
                if option:
                    sel.select_by_visible_text(compact(option.text));changed.append(target);time.sleep(.5)
                    print('AGE_SELECT',idx,target,opts[:30])
                    if len(changed)>=2:return changed
        except Exception as e: print('AGE_SELECT_ERR',idx,type(e).__name__,str(e)[:120])
    # Custom controls: click age/child field then visible '5 lat'/'7 lat' option.
    for target in ['5','7']:
        if target in changed:continue
        age_fields=[]
        for el in d.find_elements(By.XPATH,"//*[self::button or @role='button' or @role='combobox']"):
            try:
                if el.is_displayed() and any(k in (compact(el.text)+' '+(el.get_attribute('aria-label') or '')).lower() for k in ['wiek','lat','dziecko']):age_fields.append(el)
            except:pass
        for field in age_fields:
            try:
                d.execute_script('arguments[0].click()',field);time.sleep(.5)
                options=d.find_elements(By.XPATH,f"//*[(@role='option' or self::li or self::button or self::div) and (normalize-space(.)='{target}' or contains(normalize-space(.),'{target} lat'))]")
                options=[o for o in options if o.is_displayed() and len(compact(o.text))<40]
                if options:
                    d.execute_script('arguments[0].click()',options[0]);changed.append(target);print('AGE_CUSTOM',target,compact(options[0].text));time.sleep(.5);break
            except:pass
    return changed

def click_apply_search(d):
    for txt in ['Zastosuj','Gotowe','Zatwierdź','Wybierz','Szukaj','Pokaż oferty']:
        for el in d.find_elements(By.XPATH,f"//*[self::button or @role='button'][contains(normalize-space(.),'{txt}')]"):
            try:
                if el.is_displayed() and el.is_enabled():
                    print('APPLY_CLICK',txt,compact(el.text));d.execute_script('arguments[0].click()',el);time.sleep(2);return True
            except:pass
    return False

def dump_api(d):
    seen=set();found=[]
    for row in d.get_log('performance'):
        try:
            m=json.loads(row['message'])['message']
            if m.get('method')!='Network.responseReceived':continue
            r=m['params']['response'];u=r.get('url','')
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
        print('START_URL',d.current_url)
        matches=d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Dorośli 2') and contains(normalize-space(.),'Dzieci 0')]")
        visible=[x for x in matches if x.is_displayed()];visible.sort(key=lambda x:len(compact(x.text)))
        print('PARTY_SUMMARY_MATCHES',[(x.tag_name,x.get_attribute('class'),compact(x.text)[:300]) for x in visible[:15]])
        opened=False
        for el in visible:
            try:d.execute_script('arguments[0].click()',el);time.sleep(1);opened=True;break
            except Exception as e:print('OPEN_ERR',type(e).__name__,str(e)[:120])
        print('PARTY_OPENED',opened);dump_controls(d,'PARTY_UI_BEFORE')
        plus_ok=click_child_plus(d);print('CHILD_COUNT_CHANGED',plus_ok);dump_controls(d,'PARTY_UI_AFTER_PLUS')
        ages=set_child_ages(d);print('AGES_CHANGED',ages);dump_controls(d,'PARTY_UI_AFTER_AGES')
        print('APPLIED',click_apply_search(d));time.sleep(3)
        print('FINAL_URL',d.current_url)
        body=compact(d.find_element(By.TAG_NAME,'body').text)
        for needle in ['Dorośli','Dzieci','5 lat','7 lat']:
            if needle.lower() in body.lower():print('BODY_SIGNAL',needle)
        apis=dump_api(d);print('OFFERS_API_COUNT',len(apis))
        d.save_screenshot('grecos-family.png')
    finally:d.quit()
if __name__=='__main__':main()
