import re,time
from urllib.parse import urlencode, urlsplit, parse_qsl, urlunsplit
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://www.exim.pl/wyszukanie"
def compact(s): return " ".join((s or "").split())

def main():
    q=[
      ("ac1","2"),("kc1","2"),("ka1","5|7"),
      ("dd","2026-09-24"),("rd","2026-09-26"),
      ("nn","5|6|7|8"),("tt","1")
    ]
    url=BASE+"?"+urlencode(q)
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3000");o.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=o)
    try:
      d.get(url);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(6)
      print("SEARCH_URL",d.current_url)
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
          if not md: continue
          if md.group(1) not in ["24.09.2026","25.09.2026","26.09.2026"]: continue
          mr=re.search(r"(?:trustYouRating\s*)?(\d[,.]\d)\s+(?:Bardzo dobra|Znakomita|Dobra)",t,re.I)
          rating=float(mr.group(1).replace(",",".")) if mr else None
          if rating is not None and rating<8.0: continue
          key=(href,t)
          if key not in cards: cards.append(key)
        except Exception: pass
      print("CANDIDATE_COUNT",len(cards))
      for href,t in cards[:15]:
        print("CARD",repr({"text":t[:1200],"href":href[:2200]}))
      if not cards:
        return
      href,t=cards[0]
      p=urlsplit(href); params=dict(parse_qsl(p.query,keep_blank_values=True))
      params["AC1"]="2";params["KC1"]="2";params["KA1"]="5|7";params["IC1"]="0"
      exact=urlunsplit((p.scheme,p.netloc,p.path,urlencode(params),""))
      print("DETAIL_EXACT",exact)
      d.get(exact);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(7)
      print("DETAIL_FINAL",d.current_url)
      body=d.find_element(By.TAG_NAME,"body").text
      print("DETAIL_RELEVANT")
      for line in [x.strip() for x in body.splitlines() if x.strip()]:
        lo=line.lower()
        if any(k in lo for k in ["doros","dzieci","wiek","cena łącznie","cena razem","zł","all inclusive","24.09","25.09","26.09"]):
          print(line[:800])
    finally:d.quit()
if __name__=="__main__":main()
