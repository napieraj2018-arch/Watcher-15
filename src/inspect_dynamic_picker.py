import json,os,time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

REG=Path('config/channels.json')
PHRASES={
 'nekera_pl':['Ile osób?','Szukaj'],
 'oasis_pl':['Uczestnicy','Dorośli','Dzieci','Szukaj'],
 'fly_pl':['Wyszukaj i zarezerwuj','Osoby','Dorośli','Dzieci','Szukaj']
}
def compact(s): return ' '.join((s or '').split())
def main():
 cid=os.environ['CHANNEL_ID'];data=json.loads(REG.read_text(encoding='utf-8'));ch=next(x for x in data['channels'] if x['id']==cid)
 o=Options();o.add_argument('--headless=new');o.add_argument('--no-sandbox');o.add_argument('--disable-dev-shm-usage');o.add_argument('--window-size=1440,3400');o.add_argument('--lang=pl-PL')
 d=webdriver.Chrome(options=o)
 try:
  d.get(ch['url']);WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete');time.sleep(5)
  for t in ['Akceptuję','Akceptuj','Zgadzam się','Zaakceptuj wszystkie','OK','Nie zezwalaj']:
   try:
    e=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
    if e and e[0].is_displayed(): d.execute_script('arguments[0].click()',e[0]);time.sleep(.5);break
   except:pass
  print('DYN',cid,d.title,d.current_url)
  for phrase in PHRASES[cid]:
   els=d.find_elements(By.XPATH,f"//*[contains(normalize-space(.),'{phrase}')]")
   print('PHRASE',phrase,'COUNT',len(els))
   for j,el in enumerate(els[:8]):
    try:
     if not el.is_displayed():continue
     print('MATCH',j,repr({'tag':el.tag_name,'text':compact(el.text)[:700],'id':el.get_attribute('id'),'class':el.get_attribute('class'),'html':el.get_attribute('outerHTML')[:5000]}))
     anc=el
     for level in range(1,6):
      anc=anc.find_element(By.XPATH,'..')
      print('ANCESTOR',j,level,anc.get_attribute('outerHTML')[:12000])
    except Exception as e:print('MATCH_ERR',type(e).__name__,str(e)[:150])
  print('NAMED_FIELDS')
  for el in d.find_elements(By.XPATH,'//input|//select|//button'):
   try:
    if not el.is_displayed():continue
    print(repr({'tag':el.tag_name,'name':el.get_attribute('name'),'value':el.get_attribute('value'),'id':el.get_attribute('id'),'class':el.get_attribute('class'),'aria':el.get_attribute('aria-label'),'placeholder':el.get_attribute('placeholder'),'text':compact(el.text)[:350],'html':el.get_attribute('outerHTML')[:1800]}))
   except:pass
  print('SCRIPTS')
  for s in d.find_elements(By.TAG_NAME,'script'):
   src=s.get_attribute('src') or ''
   if src: print(src)
  print('STORAGE')
  for name,expr in [('local','return JSON.stringify(localStorage)'),('session','return JSON.stringify(sessionStorage)')]:
   try:print(name,d.execute_script(expr)[:25000])
   except Exception as e:print(name,'ERR',type(e).__name__)
 finally:d.quit()
if __name__=='__main__':main()
