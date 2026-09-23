import os,re,time,hashlib
from datetime import datetime,timedelta
from urllib.parse import urlencode,urlparse,parse_qs
from zoneinfo import ZoneInfo
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from watcher import chrome,dismiss_cookies,create_alert

TZ=ZoneInfo('Europe/Warsaw')
BASE='https://www.exim.pl/wyszukanie'
AIRPORT_IDS='3850|4380|4381'

def exact_party(url):
    q=parse_qs(urlparse(url).query)
    def one(*keys):
        for k in keys:
            if q.get(k): return q[k][0]
        return ''
    return one('ac1','AC1')=='2' and one('kc1','KC1')=='2' and one('ka1','KA1') in ('5|7','7|5')

def intval(s):
    x=re.sub(r'\D','',s or '')
    return int(x) if x else None

def search_url(cfg):
    today=datetime.now(TZ).date(); ds=sorted(cfg['depart_in_days'])
    start=today+timedelta(days=ds[0]); end=today+timedelta(days=ds[-1])
    nn='|'.join(str(i) for i in range(cfg['min_nights'],cfg['max_nights']+1))
    q={'ac1':'2','kc1':'2','ka1':'5|7','dd':start.isoformat(),'rd':end.isoformat(),'nn':nn,'tt':'1','to':AIRPORT_IDS}
    return BASE+'?'+urlencode(q),start,end

def load(driver,url):
    driver.get(url)
    WebDriverWait(driver,45).until(lambda d:d.execute_script('return document.readyState')=='complete')
    time.sleep(7); dismiss_cookies(driver)
    print('EXIM_LIVE_URL',driver.current_url)
    return exact_party(driver.current_url)

def card_root(driver,a):
    return driver.execute_script("""
let e=arguments[0],best=null;
for(let i=0;i<10 && e && e!==document.body;i++,e=e.parentElement){
 const t=(e.innerText||'').replace(/\\s+/g,' ').trim();
 if(t.length<80||t.length>6500) continue;
 const n=(t.match(/Cena całkowita\\s*[0-9][0-9 .]*\\s*zł/gi)||[]).length;
 if(n===1 && /Dostępne online/i.test(t)){best=e;continue;}
 if(n>1 && best) break;
} return best;""",a)

def collect(driver,cfg,start,end):
    if not exact_party(driver.current_url): return []
    body=driver.find_element(By.TAG_NAME,'body').text.lower()
    if '2 doros' not in body or '2 dzieci' not in body: return []
    out=[]; seen=set()
    for a in driver.find_elements(By.CSS_SELECTOR,"a[href*='exim.pl/kierunki/']"):
        try:
            href=a.get_attribute('href') or ''
            if not exact_party(href): continue
            root=card_root(driver,a)
            if root is None: continue
            text=' '.join(root.text.split())
            m=re.search(r'Cena całkowita\s*([0-9][0-9 .]*)\s*zł',text,re.I)
            if not m: continue
            total=intval(m.group(1)); q=parse_qs(urlparse(href).query)
            dd=(q.get('DD') or q.get('dd') or [''])[0]
            try: dep=datetime.strptime(dd,'%Y-%m-%d').date()
            except Exception: continue
            if not(start<=dep<=end): continue
            nights=intval((q.get('NN') or q.get('nn') or [''])[0])
            if nights is None or not(cfg['min_nights']<=nights<=cfg['max_nights']): continue
            if 'dostępne online' not in text.lower() or cfg['meal_contains'].lower() not in text.lower(): continue
            airport=next((x for x in cfg['airports'] if x.lower() in text.lower()),None)
            if not airport: continue
            rm=re.search(r'(?:trustYouRating|ocena)\s*([0-9](?:[.,][0-9])?)',text,re.I)
            rating=float(rm.group(1).replace(',','.')) if rm else None
            vm=re.search(r'([0-9][0-9 ]*)\s+opini',text,re.I); reviews=intval(vm.group(1)) if vm else None
            sm=re.search(r'\b([1-5])\s*(?:\*|gwiazdk)',text,re.I); stars=int(sm.group(1)) if sm else None
            name=' '.join(a.text.split()) or text[:100]
            key=hashlib.sha1((href+'|'+str(total)).encode()).hexdigest()[:16]
            if key in seen: continue
            seen.add(key)
            rec={'key':key,'hotel':name,'href':href,'verified_href':href,'price':total,'departure':dep,
                 'return':dep+timedelta(days=nights),'nights':nights,'airport':airport,'meal':'All Inclusive',
                 'operator':'EXIM tours','rating':rating,'reviews':reviews,'stars':stars}
            out.append(rec); print('EXIM_EXACT_CARD',rec)
        except Exception as e: print('EXIM_CARD_ERR',type(e).__name__,str(e)[:180])
    return out

def quality_ok(x,cfg):
    return x['price']<=cfg['max_total_price_pln'] and x['stars'] is not None and x['stars']>=cfg['min_stars'] and x['rating'] is not None and x['rating']>=cfg['min_rating'] and x['reviews'] is not None and x['reviews']>=cfg['min_reviews']

def run_exim_watcher(cfg):
    if cfg.get('adults')!=2 or cfg.get('children_ages')!=[5,7]: raise RuntimeError('EXIM locked to 2+2 ages 5/7')
    url,start,end=search_url(cfg); driver=chrome()
    try:
        if not load(driver,url): print('EXIM_FAIL_CLOSED_PARTY'); return
        cards=collect(driver,cfg,start,end); print('EXIM_EXACT_TOTAL_CARDS',len(cards))
        qualified=[x for x in cards if quality_ok(x,cfg)]; print('EXIM_QUALIFIED',len(qualified))
        if cards and not qualified: print('EXIM_QUALITY_FAIL_CLOSED')
        token=os.getenv('GITHUB_TOKEN',''); repo=os.getenv('GITHUB_REPOSITORY','')
        for x in qualified[:10]:
            if not load(driver,url): continue
            fresh=collect(driver,cfg,start,end)
            y=next((z for z in fresh if z['key']==x['key'] and z['price']==x['price'] and quality_ok(z,cfg)),None)
            if not y: print('EXIM_RECHECK_REJECT',x['key']); continue
            print('EXIM_RECHECK_VERIFIED',y['hotel'],y['price'])
            if token and repo: create_alert(token,repo,cfg,y,'EXIM exact 2+2 ages 5/7 + Dostępne online + Cena całkowita; second listing recheck')
            else: print('EXIM_DRY_ALERT',y)
    finally: driver.quit()