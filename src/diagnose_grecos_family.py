import time,json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.grecos.pl/last-minute"
def compact(s): return " ".join((s or "").split())

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
        # Smallest clickable/visible node carrying the current passenger summary.
        matches=d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Dorośli 2') and contains(normalize-space(.),'Dzieci 0')]")
        visible=[x for x in matches if x.is_displayed()]
        visible.sort(key=lambda x: len(compact(x.text)))
        print('PARTY_SUMMARY_MATCHES',[(x.tag_name,x.get_attribute('class'),compact(x.text)[:300]) for x in visible[:15]])
        opened=False
        for el in visible:
            try:
                d.execute_script('arguments[0].click()',el);time.sleep(1);opened=True;break
            except Exception as e: print('OPEN_ERR',type(e).__name__,str(e)[:120])
        print('PARTY_OPENED',opened)
        print('PARTY_UI')
        for el in d.find_elements(By.XPATH,"//button|//input|//select|//*[@role='button']|//*[@role='option']"):
            try:
                if not el.is_displayed():continue
                txt=compact(el.text)
                attrs=' '.join(filter(None,[txt,el.get_attribute('aria-label'),el.get_attribute('name'),el.get_attribute('id'),el.get_attribute('class'),el.get_attribute('value')]))
                if any(k in attrs.lower() for k in ['doros','dzie','wiek','lat','osob','plus','minus','adult','child']):
                    print('CTRL',repr({'tag':el.tag_name,'text':txt[:250],'name':el.get_attribute('name'),'id':el.get_attribute('id'),'class':el.get_attribute('class'),'value':el.get_attribute('value'),'aria':el.get_attribute('aria-label'),'html':el.get_attribute('outerHTML')[:1800]}))
            except:pass
        # Also dump the nearest visible popup/dropdown text.
        for el in d.find_elements(By.XPATH,"//*[contains(@class,'dropdown') or contains(@class,'popup') or contains(@class,'passenger') or contains(@class,'person') or contains(@class,'traveller')]"):
            try:
                if el.is_displayed() and 10 < len(compact(el.text)) < 2000:
                    print('POPUP',repr({'tag':el.tag_name,'class':el.get_attribute('class'),'text':compact(el.text)[:1800]}))
            except:pass
        # API call emitted by initial load: useful baseline for query-name mapping.
        seen=set()
        for row in d.get_log('performance'):
            try:
                m=json.loads(row['message'])['message']
                if m.get('method')!='Network.responseReceived':continue
                r=m['params']['response'];u=r.get('url','')
                if 'OffersList/LoadMoreOffers' in u and u not in seen:
                    seen.add(u);print('OFFERS_API',u)
            except:pass
        d.save_screenshot('grecos-family.png')
    finally:d.quit()
if __name__=='__main__':main()
