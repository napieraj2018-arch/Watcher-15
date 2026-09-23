import re,time
from urllib.parse import urlencode, urlparse, parse_qs, parse_qsl, urlsplit, urlunsplit
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

DEP='2026-09-24'
BASE='https://www.sunfun.pl/wyniki-wyszukiwania-wycieczek/'

def compact(s): return ' '.join((s or '').split())
def exact_url(): return BASE+'?'+urlencode({'depCity':'2','date':DEP,'dateFrom':DEP,'room1':'2,5,7','priceType':'per-person','orderDirection':'ascending','orderBy':'price'})
def exact_state(d):
    q=parse_qs(urlparse(d.current_url).query);b=d.find_element(By.TAG_NAME,'body').text.lower()
    return (q.get('room1') or [''])[0]=='2,5,7' and (q.get('date') or [''])[0]==DEP and '2 doros' in b and '2 dzieci' in b

def with_family(href):
    p=urlsplit(href);q=dict(parse_qsl(p.query,keep_blank_values=True))
    q.update({'date':DEP,'depCity':'2','room1':'2,5,7'})
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),''))

def main():
    o=Options();o.add_argument('--headless=new');o.add_argument('--no-sandbox');o.add_argument('--disable-dev-shm-usage');o.add_argument('--window-size=1440,3200');o.add_argument('--lang=pl-PL')
    d=webdriver.Chrome(options=o)
    try:
        d.get(exact_url());WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete');time.sleep(7)
        print('RESULT_URL',d.current_url);print('RESULT_EXACT_STATE',exact_state(d))
        body=d.find_element(By.TAG_NAME,'body').text;m=re.search(r'Cena całkowita\s*([0-9][0-9 .]*)\s*zł',body,re.I);print('RESULT_FIRST_TOTAL',m.group(1) if m else None)
        links=[];seen=set();raw=0
        for a in d.find_elements(By.CSS_SELECTOR,'a[href]'):
            try:
                href=a.get_attribute('href') or '';txt=compact(a.text);lo=href.lower()
                if 'sunfun.pl/' not in lo or href in seen:continue
                if any(x in lo for x in ['/wyniki-wyszukiwania','/porownanie','facebook','instagram','/kontakt','/faq','/newsletter']):continue
                # Hotel pages have country/region/hotel path; exclude site navigation.
                path=urlparse(href).path.strip('/').split('/')
                if len(path)<3:continue
                raw+=1
                if raw<=30: print('RAW_HOTEL_LINK',repr({'text':txt[:300],'href':href[:1400]}))
                href=with_family(href)
                if href in seen:continue
                seen.add(href);links.append((href,txt))
            except:pass
        print('DETAIL_CANDIDATES',len(links))
        for href,txt in links[:10]:print('DETAIL_CANDIDATE',repr({'text':txt[:500],'href':href[:1800]}))
        if not links:return
        href,_=links[0];d.get(href);WebDriverWait(d,45).until(lambda x:x.execute_script('return document.readyState')=='complete');time.sleep(7)
        print('DETAIL_URL',d.current_url);q=parse_qs(urlparse(d.current_url).query);print('DETAIL_ROOM1',(q.get('room1') or [''])[0]);print('DETAIL_DATE',(q.get('date') or [''])[0])
        body2=d.find_element(By.TAG_NAME,'body').text
        print('DETAIL_RELEVANT')
        for line in [x.strip() for x in body2.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ['gwiazd','ocena','opini','zadowolen','2 doros','2 dzieci','5 lat','7 lat','cena całkowita','cena razem','all inclusive','24.09.2026']):print(line[:1000])
        print('DETAIL_TOTALS',re.findall(r'(?:Cena całkowita|Cena razem)\s*([0-9][0-9 .]*)\s*zł',body2,re.I)[:30])
        d.save_screenshot('sunfun-family.png')
    finally:d.quit()
if __name__=='__main__':main()
