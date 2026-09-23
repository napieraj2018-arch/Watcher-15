import json,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL='https://www.sunfun.pl/wyniki-wyszukiwania-wycieczek/?depCity=2&dateFrom=2026-09-23&room1=2%2C5%2C7&priceType=per-person&orderDirection=ascending&orderBy=price'
def compact(s): return ' '.join((s or '').split())

def main():
    o=Options();o.add_argument('--headless=new');o.add_argument('--no-sandbox');o.add_argument('--disable-dev-shm-usage');o.add_argument('--window-size=1440,4200');o.add_argument('--lang=pl-PL')
    o.set_capability('goog:loggingPrefs',{'performance':'ALL'})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete');time.sleep(8)
        print('URL',d.current_url)
        print('TITLE',d.title)
        # Elements whose visible text is exactly/contains total price label.
        totals=d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Cena całkowita')]")
        print('TOTAL_LABEL_COUNT',len(totals))
        seen=set();n=0
        for lab in totals:
            try:
                if not lab.is_displayed(): continue
                anc=lab
                chosen=None
                for level in range(1,8):
                    anc=anc.find_element(By.XPATH,'..')
                    txt=compact(anc.text)
                    if len(txt)>120 and len(txt)<3500 and ('Cena całkowita' in txt) and ('ALL INCLUSIVE' in txt.upper() or 'INCLUSIVE' in txt.upper()):
                        chosen=anc
                        if any(k in (anc.get_attribute('class') or '').lower() for k in ['tour','result','offer','card','item']): break
                if chosen is None: continue
                html=chosen.get_attribute('outerHTML')
                key=hash(compact(chosen.text))
                if key in seen:continue
                seen.add(key);n+=1
                print('CARD',n,'TEXT',compact(chosen.text)[:3500])
                print('CARD',n,'CLASS',chosen.get_attribute('class'))
                print('CARD',n,'HTML',html[:16000])
                print('CARD',n,'LINKS')
                for a in chosen.find_elements(By.TAG_NAME,'a'):
                    print(repr({'text':compact(a.text)[:600],'href':(a.get_attribute('href') or '')[:1500],'html':a.get_attribute('outerHTML')[:1200]}))
                print('CARD',n,'BUTTONS')
                for b in chosen.find_elements(By.XPATH,".//button|.//*[@role='button']"):
                    print(repr({'text':compact(b.text)[:600],'id':b.get_attribute('id'),'class':b.get_attribute('class'),'data':[(x,b.get_attribute(x)) for x in ['data-cy','data-testid','data-offer-id','data-id'] if b.get_attribute(x)] ,'html':b.get_attribute('outerHTML')[:1500]}))
                if n>=6:break
            except Exception as e: print('CARD_ERR',type(e).__name__,str(e)[:180])
        print('NETWORK_JSON')
        for row in d.get_log('performance'):
            try:
                m=json.loads(row['message'])['message']
                if m['method']!='Network.responseReceived': continue
                p=m['params']; resp=p['response'];u=resp['url'];mime=resp.get('mimeType','').lower()
                if ('json' in mime or 'api' in u.lower()) and any(k in u.lower() for k in ['tour','search','offer','result']): print(u[:4000],mime,resp.get('status'))
            except:pass
    finally:d.quit()
if __name__=='__main__':main()
