import json,time
from urllib.parse import urlparse,parse_qs,urlencode
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

URL='https://www.travelplanet.pl/wakacje/super-last-minute/'

def main():
    o=Options(); o.add_argument('--headless=new'); o.add_argument('--no-sandbox'); o.add_argument('--disable-dev-shm-usage'); o.add_argument('--window-size=1440,3000'); o.add_argument('--lang=pl-PL')
    o.set_capability('goog:loggingPrefs', {'performance':'ALL'})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL); WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete'); time.sleep(4)
        for t in ['Akceptuję','Akceptuj','Zgadzam się','Zaakceptuj wszystkie','OK']:
            try:
                b=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if b and b[0].is_displayed(): d.execute_script('arguments[0].click()',b[0]); time.sleep(.5); break
            except: pass
        d.find_element(By.CSS_SELECTOR,"[data-testid='person-textbox-control-children']").click(); time.sleep(.8)
        label=d.find_element(By.XPATH,"//label[contains(normalize-space(.),'Liczba dzieci')]")
        spinner=label.find_element(By.XPATH,"./ancestor::div[contains(@class,'i-textbox--numeric-spinner')][1]")
        plus=spinner.find_elements(By.TAG_NAME,'button')[-1]
        for _ in range(2): d.execute_script('arguments[0].click()',plus); time.sleep(.35)
        s1=d.find_element(By.CSS_SELECTOR,"select[name='child-1']"); s2=d.find_element(By.CSS_SELECTOR,"select[name='child-2']")
        Select(s1).select_by_value('5'); time.sleep(.4)
        Select(s2).select_by_value('7'); time.sleep(.8)
        for s in (s1,s2): d.execute_script("arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));",s)
        time.sleep(.5)
        print('TP_VALUES_OPEN', d.find_element(By.CSS_SELECTOR,"[data-testid='person-textbox-control-adults']").get_attribute('value'), d.find_element(By.CSS_SELECTOR,"[data-testid='person-textbox-control-children']").get_attribute('value'), s1.get_attribute('value'), s2.get_attribute('value'))
        print('TP_FORMS')
        for i,f in enumerate(d.find_elements(By.TAG_NAME,'form')):
            try:
                html=f.get_attribute('outerHTML')
                if any(k in html for k in ['person-textbox','sf-submit-button','child-1','nl_occupancy']): print('FORM',i,html[:18000])
            except: pass
        print('TP_STORAGE_BEFORE')
        for kind,expr in [('local','return JSON.stringify(localStorage)'),('session','return JSON.stringify(sessionStorage)')]:
            try: print(kind,d.execute_script(expr)[:20000])
            except Exception as e: print(kind,'ERR',type(e).__name__)
        try:
            toggle=d.find_element(By.CSS_SELECTOR,"[data-testid='sf-passengers-picker-textbox']"); d.execute_script('arguments[0].click()',toggle); time.sleep(.8)
        except Exception as e: print('TP_CLOSE_ERR',type(e).__name__,str(e)[:200])
        print('TP_VALUES_CLOSED', [x.get_attribute('value') for x in d.find_elements(By.CSS_SELECTOR,"[data-testid='person-textbox-control-adults']")], [x.get_attribute('value') for x in d.find_elements(By.CSS_SELECTOR,"[data-testid='person-textbox-control-children']")])
        print('TP_SELECTS_CLOSED', [(x.get_attribute('name'),x.get_attribute('value')) for x in d.find_elements(By.TAG_NAME,'select') if x.get_attribute('name')])
        d.get_log('performance')
        submit=d.find_element(By.CSS_SELECTOR,"[data-testid='sf-submit-button']")
        d.execute_script('arguments[0].click()',submit)
        time.sleep(8)
        print('TP_AFTER_URL',d.current_url)
        print('TP_AFTER_QS',json.dumps(parse_qs(urlparse(d.current_url).query),ensure_ascii=False,sort_keys=True))
        print('TP_AFTER_PARTY', [(x.get_attribute('data-testid'),x.get_attribute('value')) for x in d.find_elements(By.CSS_SELECTOR,"[data-testid^='person-textbox-control-']")])
        print('TP_NETWORK')
        seen=set()
        for row in d.get_log('performance'):
            try:
                msg=json.loads(row['message'])['message']
                if msg['method']!='Network.requestWillBeSent': continue
                req=msg['params']['request']; u=req['url']; lo=u.lower()
                if any(k in lo for k in ['occup','child','adult','passenger','wakacje/?s_action','search']):
                    if u not in seen:
                        print('REQ',req.get('method'),u[:5000], 'POST', (req.get('postData') or '')[:5000]); seen.add(u)
            except: pass
        print('TP_STORAGE_AFTER')
        for kind,expr in [('local','return JSON.stringify(localStorage)'),('session','return JSON.stringify(sessionStorage)')]:
            try: print(kind,d.execute_script(expr)[:20000])
            except Exception as e: print(kind,'ERR',type(e).__name__)

        # Canonical frontend state uses nl_occupancy_children and an array
        # nl_ages_children. Travelplanet serializes array filters with [] (the
        # same form is visible for nl_transportation_id[]), so bypass the
        # headless picker commit bug and verify the backend directly.
        parsed=urlparse(d.current_url)
        base=parse_qs(parsed.query,keep_blank_values=True)
        base['nl_occupancy_adults']=['2']
        base['nl_occupancy_children']=['2']
        base.pop('nl_ages_children',None); base.pop('nl_ages_children[]',None)
        pairs=[]
        for k,vals in base.items():
            for v in vals: pairs.append((k,v))
        pairs.extend([('nl_ages_children[]','5'),('nl_ages_children[]','7')])
        direct='https://www.travelplanet.pl/wakacje/?'+urlencode(pairs)
        print('TP_DIRECT_EXACT_URL',direct)
        d.get_log('performance')
        d.get(direct); WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete'); time.sleep(8)
        print('TP_DIRECT_FINAL_URL',d.current_url)
        print('TP_DIRECT_QS',json.dumps(parse_qs(urlparse(d.current_url).query),ensure_ascii=False,sort_keys=True))
        try:
            print('TP_DIRECT_PARTY',[
              (x.get_attribute('data-testid'),x.get_attribute('value'))
              for x in d.find_elements(By.CSS_SELECTOR,"[data-testid^='person-textbox-control-']")
            ])
        except Exception as e: print('TP_DIRECT_PARTY_ERR',type(e).__name__)
        body=d.find_element(By.TAG_NAME,'body').text
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ['2 dzieci','5 lat','7 lat','za wszystkich','cena razem','łącznie']):
                print('TP_DIRECT_SIGNAL',line[:1000])
        print('TP_DIRECT_STORAGE')
        for kind,expr in [('local','return JSON.stringify(localStorage)'),('session','return JSON.stringify(sessionStorage)')]:
            try:
                raw=d.execute_script(expr)
                if any(k in raw for k in ['nl_occupancy_children','nl_ages_children','kids','child']):
                    print(kind,raw[:24000])
            except Exception as e: print(kind,'ERR',type(e).__name__)
        print('TP_DIRECT_NETWORK')
        for row in d.get_log('performance'):
            try:
                msg=json.loads(row['message'])['message']
                if msg['method']!='Network.requestWillBeSent': continue
                req=msg['params']['request']; blob=(req.get('url','')+' '+(req.get('postData') or ''))
                if any(k in blob for k in ['nl_occupancy_children','nl_ages_children','adult:_2_child:_2','number_of_kids']):
                    print('TP_DIRECT_REQ',req.get('method'),req.get('url','')[:7000],'POST',(req.get('postData') or '')[:10000])
            except: pass
    finally: d.quit()
if __name__=='__main__': main()
