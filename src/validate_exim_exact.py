import json,re,time
from datetime import datetime,timedelta
from urllib.parse import urlencode, urlsplit, parse_qsl, urlunsplit, parse_qs
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://www.exim.pl/wyszukanie"
TZ=ZoneInfo('Europe/Warsaw')
def compact(s): return " ".join((s or "").split())

def party_params(url):
    q={k.upper():v[-1] for k,v in parse_qs(urlsplit(url).query,keep_blank_values=True).items()}
    return {k:q.get(k) for k in ["AC1","KC1","KA1","IC1"]}

def exact_party_in_url(url):
    p=party_params(url)
    return p.get("AC1")=="2" and p.get("KC1")=="2" and p.get("KA1") in ("5|7","5%7C7")

def dump_search_api(d,label):
    urls=[]
    for row in d.get_log('performance'):
        try:
            m=json.loads(row['message'])['message']
            if m.get('method')!='Network.responseReceived':continue
            u=m['params']['response'].get('url','')
            if '/api/searchapi/' in u or '/api/searchfilter/' in u:
                if u not in urls:urls.append(u);print(label,u)
        except:pass
    return urls

def main():
    today=datetime.now(TZ).date();start=today+timedelta(days=1);end=today+timedelta(days=3)
    q=[
      ("ac1","2"),("kc1","2"),("ka1","5|7"),
      ("dd",start.isoformat()),("rd",end.isoformat()),
      ("nn","5|6|7|8"),("tt","1"),("to","3850|4380|4381")
    ]
    url=BASE+"?"+urlencode(q)
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3000");o.add_argument("--lang=pl-PL")
    o.set_capability('goog:loggingPrefs',{'performance':'ALL'})
    d=webdriver.Chrome(options=o)
    try:
      d.get(url);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(8)
      print("SEARCH_URL",d.current_url)
      print("SEARCH_PARTY_PARAMS",party_params(d.current_url),"EXACT",exact_party_in_url(d.current_url))
      api_urls=dump_search_api(d,'SEARCH_API')
      print('SEARCH_API_COUNT',len(api_urls))
      body0=d.find_element(By.TAG_NAME,"body").text
      for line in [x.strip() for x in body0.splitlines() if x.strip()]:
        lo=line.lower()
        if any(k in lo for k in ["2 doros","2 dzieci","5 lat","7 lat","uczestnik"]): print("SEARCH_PARTY_LINE",line[:600])
      cards=[]
      for a in d.find_elements(By.TAG_NAME,"a"):
        try:
          href=a.get_attribute("href") or ""; txt=compact(a.text)
          if not href or "exim.pl/kierunki/" not in href: continue
          anc=None
          for xp in ["./ancestor::article[1]","./ancestor::div[contains(.,'Dorosły od')][1]"]:
            try: anc=a.find_element(By.XPATH,xp);break
            except: pass
          if anc is None: continue
          t=compact(anc.text)
          if "All inclusive" not in t and "All Inclusive" not in t: continue
          if "Warszawa" not in t and "Radom" not in t: continue
          md=re.search(r"(\d{1,2}\.\d{1,2}\.\d{4}).*?(\d+)\s+nocy",t)
          mr=re.search(r"(?:trustYouRating\s*)?(\d[,.]\d)\s+(?:Bardzo dobra|Znakomita|Dobra)",t,re.I)
          rating=float(mr.group(1).replace(",",".")) if mr else None
          if rating is not None and rating<8.0: continue
          key=(href,t)
          if key not in cards: cards.append(key)
        except Exception: pass
      print("CANDIDATE_COUNT",len(cards))
      for href,t in cards[:15]: print("CARD",repr({"text":t[:1200],"href":href[:2200]}))
      if not cards: return
      href,t=cards[0]
      p=urlsplit(href); params=dict(parse_qsl(p.query,keep_blank_values=True))
      params["AC1"]="2";params["KC1"]="2";params["KA1"]="5|7";params["IC1"]="0"
      exact=urlunsplit((p.scheme,p.netloc,p.path,urlencode(params),""))
      print("DETAIL_EXACT",exact)
      d.get(exact);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(8)
      print("DETAIL_FINAL",d.current_url)
      print("DETAIL_PARTY_PARAMS",party_params(d.current_url),"EXACT",exact_party_in_url(d.current_url))
      dump_search_api(d,'DETAIL_API')
      body=d.find_element(By.TAG_NAME,"body").text
      lines=[x.strip() for x in body.splitlines() if x.strip()]
      for line in lines:
        lo=line.lower()
        if any(k in lo for k in ["doros","dzieci","wiek","cena łącznie","cena razem","zł","all inclusive",start.strftime('%d.%m'),(start+timedelta(days=1)).strftime('%d.%m')]): print("DETAIL_LINE",line[:800])
      totals=[]
      for pat in [r"Cena\s*(?:łącznie|razem|całkowita)\s*[: ]\s*([0-9][0-9 .]*)\s*zł",r"Razem\s*[: ]\s*([0-9][0-9 .]*)\s*zł"]:
        totals.extend(int(re.sub(r"\D","",m)) for m in re.findall(pat,body,re.I) if re.sub(r"\D","",m))
      print("EXIM_EXPLICIT_TOTALS",totals[:30])
      print("EXIM_EXACT_FAMILY_TOTAL_VERIFIED",bool(totals) and exact_party_in_url(d.current_url))
    finally:d.quit()
if __name__=="__main__":main()
