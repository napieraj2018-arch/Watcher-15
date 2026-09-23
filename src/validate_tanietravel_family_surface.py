import json,re,time
from datetime import datetime,timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

TZ=ZoneInfo("Europe/Warsaw")
BASE="https://www.katowice-travel.pl/results.php"

def compact(s): return " ".join((s or "").split())

def url():
    today=datetime.now(TZ).date()
    q=[
      ("type","tours"),("dest","11"),
      ("dateFrom",(today+timedelta(days=1)).isoformat()),
      ("dateTo",(today+timedelta(days=3)).isoformat()),
      ("adults","2"),("children","2"),("ages","5,7"),
      ("dep","WAW,WMI,RDO"),("nMin","5"),("nMax","8"),
      ("ai","1"),("meal","ai"),("stars","4plus")
    ]
    return BASE+"?"+urlencode(q)

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,4200","--lang=pl-PL"]:
        o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(url())
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(12)
        print("TANIESURF_URL",d.current_url)
        body=d.find_element(By.TAG_NAME,"body").text
        for needle in ["2 + 2","5, 7 lat","All inclusive","Kup za","zł/os","Hotele 4"]:
            print("TANIESURF_BODY_SIGNAL",needle,needle.lower() in body.lower())
        cards=[]
        nodes=d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Kup za')]")
        for e in nodes:
            try:
                if not e.is_displayed():continue
                anc=e
                best=""
                for _ in range(7):
                    txt=compact(anc.text)
                    if len(txt)>len(best) and len(txt)<5000:best=txt
                    anc=anc.find_element(By.XPATH,"..")
                if "Kup za" not in best:continue
                price=None
                m=re.search(r"Kup za\s*([0-9\s\u00a0]+)\s*z[łl]",best,re.I)
                if m:price=int(re.sub(r"\D","",m.group(1)))
                rec={"text":best[:3200],"price":price}
                if rec not in cards:
                    cards.append(rec);print("TANIESURF_CARD",json.dumps(rec,ensure_ascii=False))
                if len(cards)>=20:break
            except:pass
        print("TANIESURF_CARD_COUNT",len(cards))
        print("TANIESURF_WHOLE_OFFER_PRICES",sum(1 for x in cards if x["price"]))
        # Capture the actual API request emitted by this exact family surface.
        seen=0
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or ""
                if "/api/search_offers.php" in u:
                    seen+=1
                    print("TANIESURF_API_REQ",req.get("method"),u,"POST",post[:6000])
            except:pass
        print("TANIESURF_API_REQ_COUNT",seen)
    finally:d.quit()

if __name__=="__main__":main()
