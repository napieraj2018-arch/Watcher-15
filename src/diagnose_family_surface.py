import json,os,time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

REG=Path('config/channels.json')
def compact(s): return ' '.join((s or '').split())

def main():
    cid=os.environ['CHANNEL_ID']
    data=json.loads(REG.read_text(encoding='utf-8'))
    ch=next(x for x in data['channels'] if x['id']==cid)
    o=Options(); o.add_argument('--headless=new');o.add_argument('--no-sandbox');o.add_argument('--disable-dev-shm-usage');o.add_argument('--window-size=1440,3200');o.add_argument('--lang=pl-PL')
    d=webdriver.Chrome(options=o)
    try:
        d.get(ch['url']); WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete');time.sleep(5)
        for t in ['Akceptuję','Akceptuj','Zgadzam się','Zaakceptuj wszystkie','Zezwól na wszystkie','OK']:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed(): d.execute_script('arguments[0].click()',els[0]);time.sleep(.5);break
            except:pass
        print('SURFACE',cid,d.title,d.current_url)
        print('IFRAMES')
        for i,f in enumerate(d.find_elements(By.TAG_NAME,'iframe')): print(i,repr({'src':f.get_attribute('src'),'title':f.get_attribute('title'),'id':f.get_attribute('id')}))
        print('CANDIDATES_BEFORE')
        candidates=[]
        for el in d.find_elements(By.XPATH,"//button|//input|//select|//*[@role='button']|//a"):
            try:
                if not el.is_displayed(): continue
                txt=compact(el.text); blob=' '.join(filter(None,[txt,el.get_attribute('aria-label'),el.get_attribute('name'),el.get_attribute('placeholder'),el.get_attribute('id'),el.get_attribute('class'),el.get_attribute('data-testid'),el.get_attribute('value')])).lower()
                if any(k in blob for k in ['doros','dzie','osob','osób','uczest','pasaż','pasaz','pokój','pokoj','wiek','adult','child','person','guest','room']):
                    rec={'tag':el.tag_name,'text':txt[:350],'name':el.get_attribute('name'),'value':el.get_attribute('value'),'aria':el.get_attribute('aria-label'),'id':el.get_attribute('id'),'testid':el.get_attribute('data-testid'),'href':(el.get_attribute('href') or '')[:800],'html':el.get_attribute('outerHTML')[:1800]}
                    print(repr(rec)); candidates.append(el)
            except:pass
        clicked=False
        for el in candidates:
            try:
                blob=' '.join(filter(None,[compact(el.text),el.get_attribute('aria-label'),el.get_attribute('placeholder'),el.get_attribute('class'),el.get_attribute('data-testid')])).lower()
                if any(k in blob for k in ['doros','osob','osób','uczest','pasaż','pasaz','person','guest','room']):
                    d.execute_script('arguments[0].click()',el);time.sleep(1);clicked=True;print('CLICKED',repr(blob[:500]));break
            except:pass
        print('PICKER_CLICKED',clicked)
        print('CONTROLS_AFTER')
        n=0
        for el in d.find_elements(By.XPATH,"//button|//input|//select|//*[@role='button']"):
            try:
                if not el.is_displayed():continue
                txt=compact(el.text); blob=' '.join(filter(None,[txt,el.get_attribute('aria-label'),el.get_attribute('name'),el.get_attribute('placeholder'),el.get_attribute('id'),el.get_attribute('class'),el.get_attribute('data-testid'),el.get_attribute('value')])).lower()
                if any(k in blob for k in ['doros','dzie','osob','osób','uczest','pasaż','pasaz','pokój','pokoj','wiek','lat','adult','child','person','guest','room','age']):
                    print(repr({'tag':el.tag_name,'text':txt[:350],'name':el.get_attribute('name'),'value':el.get_attribute('value'),'aria':el.get_attribute('aria-label'),'id':el.get_attribute('id'),'testid':el.get_attribute('data-testid'),'html':el.get_attribute('outerHTML')[:2000]}));n+=1
                    if n>=160:break
            except:pass
        print('FORMS')
        for i,f in enumerate(d.find_elements(By.TAG_NAME,'form')):
            try: print('FORM',i,f.get_attribute('outerHTML')[:18000])
            except:pass
        print('SIGNAL_LINES')
        for line in [x.strip() for x in d.find_element(By.TAG_NAME,'body').text.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ['doros','dzie','osob','osób','uczest','pasaż','wiek','warszaw','radom','all inclusive','cena','szukaj']): print(line[:800])
        d.save_screenshot(f'family-surface-{cid}.png')
    finally:d.quit()
if __name__=='__main__':main()
