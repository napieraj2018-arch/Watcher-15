import hashlib
import os
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse, parse_qs
from zoneinfo import ZoneInfo

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from watcher import chrome, dismiss_cookies

TZ = ZoneInfo('Europe/Warsaw')
BASE = 'https://www.sunfun.pl/wyniki-wyszukiwania-wycieczek/'
UNAVAILABLE = ('brak ofert','brak wyników','oferta niedostępna','brak miejsc','wyprzedana')

def compact(s): return ' '.join((s or '').split())

def exact_url(dep, ages):
    q={'depCity':'2','date':dep.isoformat(),'dateFrom':dep.isoformat(),'room1':f'2,{ages[0]},{ages[1]}','priceType':'per-person','orderDirection':'ascending','orderBy':'price'}
    return BASE+'?'+urlencode(q)

def exact_party(driver, ages):
    qs=parse_qs(urlparse(driver.current_url).query)
    wanted=f'2,{ages[0]},{ages[1]}'
    room=(qs.get('room1') or [''])[0]
    body=driver.find_element(By.TAG_NAME,'body').text.lower()
    return room==wanted and '2 doros' in body and '2 dzieci' in body

def exact_departure(driver, expected_dep):
    qs=parse_qs(urlparse(driver.current_url).query)
    return (qs.get('date') or [''])[0]==expected_dep.isoformat()

def _offer_ancestor(driver, anchor):
    return driver.execute_script(r"""
      let el=arguments[0];
      for(let i=0;i<12 && el && el!==document.body;i++,el=el.parentElement){
        const t=(el.innerText||'').replace(/\s+/g,' ').trim();
        if(t.length<80 || t.length>2800) continue;
        if(/Cena całkowita\s*[0-9][0-9 .]*\s*zł/i.test(t) && /Dorosły\s*[0-9][0-9 .]*\s*zł/i.test(t) && /dziecko\s*[0-9][0-9 .]*\s*zł/i.test(t)) return el;
      }
      return null;
    """,anchor)

def parse_cards(driver):
    cards=[];seen=set()
    for a in driver.find_elements(By.CSS_SELECTOR,'a[href]'):
        try:
            if not a.is_displayed():continue
            href=a.get_attribute('href') or '';name=compact(a.text);p=urlparse(href)
            if p.netloc.lower()!='www.sunfun.pl':continue
            parts=[x for x in p.path.split('/') if x]
            if len(parts)!=3 or not name:continue
            chosen=_offer_ancestor(driver,a)
            if chosen is None:continue
            text=compact(chosen.text)
            mtotal=re.search(r'Cena całkowita\s*([0-9][0-9 .]*)\s*zł',text,re.I)
            if not mtotal:continue
            total=int(re.sub(r'\D','',mtotal.group(1)))
            key=hashlib.sha1((href+'|'+str(total)+'|'+text).encode('utf-8')).hexdigest()[:16]
            if key in seen:continue
            seen.add(key)
            meal='All Inclusive' if 'ALL INCLUSIVE' in text.upper() else ''
            ms=re.search(r'\b([1-5])\s*(?:\*|gwiazdk)',text,re.I)
            if not ms:ms=re.search(r'(?:hotel|kategoria)\s*([1-5])\b',text,re.I)
            stars=int(ms.group(1)) if ms else None
            mr=re.search(r'\b([0-9](?:[.,][0-9])?)\s*/\s*10\b',text)
            rating=float(mr.group(1).replace(',','.')) if mr else None
            if rating is None:
                pct=re.search(r'(\d{2,3})\s*%\s*zadowolen',text,re.I)
                if pct:rating=round(int(pct.group(1))/10,1)
            mn=re.search(r'([0-9][0-9 ]*)\s+opini',text,re.I)
            reviews=int(mn.group(1).replace(' ','')) if mn else None
            cards.append({'key':key,'name':name,'total':total,'meal':meal,'stars':stars,'rating':rating,'reviews':reviews,'text':text,'href':href})
        except Exception as e:print('SUNFUN_CARD_ERR',type(e).__name__,str(e)[:160])
    return cards

def qualifies(x,cfg):
    if x['total']>cfg['max_total_price_pln']:return False
    if cfg['meal_contains'].lower() not in x['meal'].lower():return False
    if x['stars'] is None or x['stars']<cfg['min_stars']:return False
    if x['rating'] is None or x['rating']<cfg['min_rating']:return False
    if x['reviews'] is None or x['reviews']<cfg['min_reviews']:return False
    return True

def issue_exists(token,repo,marker):
    r=requests.get(f'https://api.github.com/repos/{repo}/issues?state=all&per_page=100',headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json'},timeout=20)
    if r.status_code>=300:return False
    return any(marker in (x.get('body') or '') for x in r.json())

def create_issue(token,repo,cand,dep,cfg):
    marker=f"SUNFUN:{dep.isoformat()}:{cand['key']}:{cand['total']}"
    if issue_exists(token,repo,marker):print('SUNFUN_DUPLICATE',marker);return
    title=f"🔥 Sun&Fun 2+2 — {cand['total']} zł — {dep.isoformat()}"
    body=(f"{marker}\n\nZweryfikowana oferta Sun & Fun dla **2 dorosłych + dzieci 5 i 7 lat**.\n\n- hotel: **{cand['name']}**\n- cena całkowita: **{cand['total']} zł**\n- wyżywienie: {cand['meal']}\n- hotel: {cand['stars']}★\n- ocena: {cand['rating']}/10 ({cand['reviews']} opinii)\n- wylot: {dep.isoformat()}\n- źródło: {cand['href']}\n\nAutomat wykonał ponowną kontrolę dokładnego składu 2+2, daty i ceny całkowitej przed utworzeniem alarmu.")
    payload={'title':title,'body':body,'assignees':[cfg['notify_github_user']]}
    r=requests.post(f'https://api.github.com/repos/{repo}/issues',headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json'},json=payload,timeout=20)
    print('SUNFUN_ISSUE',r.status_code,(r.text or '')[:400]);r.raise_for_status()

def load_exact(driver,url,ages,expected_dep):
    driver.get(url);WebDriverWait(driver,40).until(lambda d:d.execute_script('return document.readyState')=='complete');time.sleep(6);dismiss_cookies(driver)
    if any(x in driver.find_element(By.TAG_NAME,'body').text.lower() for x in UNAVAILABLE):return False
    party=exact_party(driver,ages);date_ok=exact_departure(driver,expected_dep)
    print('SUNFUN_EXACT_STATE','party=',party,'date=',date_ok,'expected=',expected_dep,'url=',driver.current_url)
    return party and date_ok

def run_sunfun_watcher(cfg):
    if cfg.get('adults')!=2 or cfg.get('children_ages')!=[5,7]:raise RuntimeError('SunFun production adapter is locked to exact 2+2 ages 5/7.')
    token=os.environ.get('GITHUB_TOKEN','');repo=os.environ.get('GITHUB_REPOSITORY','napieraj2018-arch/Watcher-15')
    if not token:raise RuntimeError('GITHUB_TOKEN missing')
    driver=chrome();matches=[];verified_family_total=False
    try:
        today=datetime.now(TZ).date()
        for delta in cfg['depart_in_days']:
            dep=today+timedelta(days=int(delta));url=exact_url(dep,cfg['children_ages']);print('SUNFUN_SEARCH',url)
            if not load_exact(driver,url,cfg['children_ages'],dep):continue
            cards=parse_cards(driver)
            if cards:
                verified_family_total=True;print('SUNFUN_FAMILY_TOTAL_VERIFIED',dep,cards[0]['total'],len(cards));print('SUNFUN_CARD_SAMPLE',cards[0]['text'][:1800])
            print('SUNFUN_CARDS',dep,len(cards),[(x['name'],x['total'],x['stars'],x['rating'],x['reviews'],x['meal']) for x in cards[:12]])
            for x in cards:
                if qualifies(x,cfg):matches.append((dep,url,x))
        print('SUNFUN_VERIFIED_FAMILY_TOTAL',verified_family_total);print('SUNFUN_MATCHES',len(matches))
        for dep,url,x in matches[:10]:
            if not load_exact(driver,url,cfg['children_ages'],dep):continue
            fresh=parse_cards(driver);confirm=next((y for y in fresh if y['total']==x['total'] and y['name']==x['name'] and qualifies(y,cfg)),None)
            if not confirm:print('SUNFUN_RECHECK_REJECT',x['total']);continue
            create_issue(token,repo,confirm,dep,cfg)
    finally:driver.quit()
