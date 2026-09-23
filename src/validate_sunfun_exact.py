import time,re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL='https://www.sunfun.pl/wyniki-wyszukiwania-wycieczek/?depCity=2&dateFrom=2026-09-23&room1=2%2C5%2C7&priceType=per-person&orderDirection=ascending&orderBy=price'
def compact(s): return ' '.join((s or '').split())

def main():
    o=Options();o.add_argument('--headless=new');o.add_argument('--no-sandbox');o.add_argument('--disable-dev-shm-usage');o.add_argument('--window-size=1440,3600');o.add_argument('--lang=pl-PL')
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete');time.sleep(8)
        for t in ['Akceptuję','Akceptuj','Zgadzam się','Zaakceptuj wszystkie','OK']:
            try:
                e=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if e and e[0].is_displayed(): d.execute_script('arguments[0].click()',e[0]);time.sleep(.5);break
            except:pass
        print('SUN_EXACT_URL',d.current_url)
        print('SUN_ROOM_INPUTS',[(x.get_attribute('name'),x.get_attribute('value')) for x in d.find_elements(By.CSS_SELECTOR,"input[name^='rooms']")])
        print('SUN_RESULT_SIGNALS')
        lines=[x.strip() for x in d.find_element(By.TAG_NAME,'body').text.splitlines() if x.strip()]
        for line in lines:
            lo=line.lower()
            if any(k in lo for k in ['2 doros','2 dzieci','5 lat','7 lat','warszawa','all inclusive','zł','cena','razem','łącznie']): print(line[:1000])
        print('SUN_CLICKABLES')
        cs=[]
        for el in d.find_elements(By.XPATH,"//a|//button|//*[@role='button']"):
            try:
                if not el.is_displayed():continue
                txt=compact(el.text); href=el.get_attribute('href') or ''
                if txt and any(k in txt.lower() for k in ['szczeg','wybierz','rezerw','zobacz','sprawd','hotel','od ']):
                    rec={'tag':el.tag_name,'text':txt[:700],'href':href[:1200],'html':el.get_attribute('outerHTML')[:1800]}
                    print(repr(rec));cs.append((el,txt,href))
            except:pass
        # Prefer an actual offer/detail link with href.
        target=None
        for el,txt,href in cs:
            if href and 'sunfun.pl' in href and any(k in href.lower() for k in ['hotel','ofert','wyciecz','lato']): target=href;break
        if target:
            print('SUN_DETAIL_TARGET',target)
            d.get(target);WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete');time.sleep(8)
            print('SUN_DETAIL_URL',d.current_url)
            print('SUN_DETAIL_LINES')
            for line in [x.strip() for x in d.find_element(By.TAG_NAME,'body').text.splitlines() if x.strip()]:
                lo=line.lower()
                if any(k in lo for k in ['2 doros','2 dzieci','5 lat','7 lat','zł','cena','razem','łącznie','rezerw','all inclusive']): print(line[:1200])
        else:
            print('SUN_NO_DETAIL_TARGET')
        d.save_screenshot('sunfun-exact.png')
    finally:d.quit()
if __name__=='__main__':main()
