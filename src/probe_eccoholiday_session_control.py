import json,re,time
from urllib.parse import urlsplit
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://www.eccoholiday.com/"
FAMILY="https://www.eccoholiday.com/l,,,2026-09-24,2026-09-26,,,2,5;7,all+inclusive,4;5,samolot,,,,,5;6;7;8,,,,,,,,,,,,,,,,,1,samolotem"
ADULTS="https://www.eccoholiday.com/l,,,2026-09-24,2026-09-26,,,2,,all+inclusive,4;5,samolot,,,,,5;6;7;8,,,,,,,,,,,,,,,,,1,samolotem"

def compact(s): return " ".join((s or "").split())
def chrome():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,4200","--lang=pl-PL"]:o.add_argument(a)
    return webdriver.Chrome(options=o)

def accept(d):
    for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
        try:
            xs=[x for x in d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]") if x.is_displayed()]
            if xs:d.execute_script("arguments[0].click()",xs[0]);time.sleep(.5);return
        except:pass

def parse_card_text(txt):
    txt=compact(txt)
    pm=re.search(r"([0-9][0-9 ]{2,})\s*zł\s*/\s*razem",txt,re.I)
    dm=re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})",txt)
    nm=re.search(r"(\d+)\s*dni\s*/\s*(\d+)\s*no",txt,re.I)
    tm=re.search(r"(Warszawa(?:\s*-\s*(?:Modlin|Okęcie|Radom))?)[^0-9]{0,40}([0-2]?\d:[0-5]\d)",txt,re.I)
    if not pm or not dm:return None
    return {
      "price":int(pm.group(1).replace(" ","")),
      "departure":dm.group(1),
      "days":int(nm.group(1)) if nm else None,
      "nights":int(nm.group(2)) if nm else None,
      "airport":tm.group(1) if tm else None,
      "time":tm.group(2) if tm else None,
      "text":txt[:2600],
    }

def cards(d,label):
    body=d.find_element(By.TAG_NAME,"body").text
    print("ECCOSESS_URL",label,d.current_url)
    print("ECCOSESS_BODY",label,len(body),"children_5_7",("5 lat" in body and "7 lat" in body),"total_mode","zł/razem" in body)
    out=[]
    seen=set()
    links=[a for a in d.find_elements(By.TAG_NAME,"a") if a.is_displayed() and a.get_attribute("href")]
    for a in links:
        try:
            at=compact(a.text).lower()
            if "zobacz ofert" not in at and "sprawdź ofert" not in at:continue
            anc=a
            best=None
            for _ in range(8):
                txt=compact(anc.text)
                parsed=parse_card_text(txt)
                if parsed and len(txt)<5000:
                    best=(anc,parsed)
                anc=anc.find_element(By.XPATH,"..")
            if not best:continue
            parsed=best[1]
            href=a.get_attribute("href")
            path=urlsplit(href).path.rstrip("/")
            # hotel name is the text immediately preceding destination/date in most cards;
            # use normalized detail path as stable hotel identity when available.
            key=(path,parsed["departure"],parsed["nights"],parsed["airport"])
            if key in seen:continue
            seen.add(key)
            parsed["href"]=href;parsed["key"]=key
            out.append(parsed)
            print("ECCOSESS_CARD",label,json.dumps(parsed,ensure_ascii=False,default=str))
        except Exception as e:
            print("ECCOSESS_CARD_ERR",label,type(e).__name__,str(e)[:120])
    print("ECCOSESS_CARD_COUNT",label,len(out))
    return out

def load(d,url,label):
    # Prime first-party cookies/session before using serialized search route.
    d.get(BASE)
    WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
    time.sleep(2);accept(d)
    d.get(url)
    WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
    time.sleep(7)
    return cards(d,label)

def main():
    d=chrome()
    try:
        fam=load(d,FAMILY,"FAMILY")
        ad=load(d,ADULTS,"ADULTS")
        amap={tuple(x["key"]):x for x in ad}
        proofs=[]
        for f in fam:
            a=amap.get(tuple(f["key"]))
            if not a:continue
            if f["price"]==a["price"]:continue
            p={"key":f["key"],"family_total":f["price"],"adult_total":a["price"],
               "href":f["href"],"departure":f["departure"],"time":f["time"],
               "family_text":f["text"][:1200]}
            proofs.append(p);print("ECCOSESS_PROOF",json.dumps(p,ensure_ascii=False,default=str))
        print("ECCOSESS_PARTY_SENSITIVE",len(proofs))
        print("ECCOSESS_FAMILY_TOTAL_VERIFIED",bool(proofs))
    finally:d.quit()

if __name__=="__main__":main()
