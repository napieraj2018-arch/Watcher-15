import json,re,time,requests
from urllib.parse import quote,urlsplit
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://www.eccoholiday.com"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36"

def compact(s): return " ".join((s or "").split())
def canon(children):
    p={"resultsPerPage":"30","resultsPageNumber":"1","adults":"2","transport":["samolot"],
       "length":["5","6","7","8"],"departureDateFrom":"2026-09-24","departureDateTo":"2026-09-26",
       "countryRegion":[],"departureFrom":[],"extraType":"samolotem","returnDateTo":"",
       "dateDepFromRetTo":["",""],"category":["4","5"],"children":children,
       "feeding":["all inclusive"],"price":[],"attributes":[],"tourOperator":[],"offerType":[],
       "offerCatalog":"","priceTotal":"1"}
    u=BASE+"/index.php?module=bp/search/searchParamsToUrl&mode=ajax&linkType=getSearchLink&searchParams="+quote(json.dumps(p,separators=(",",":")))
    r=requests.get(u,headers={"User-Agent":UA},timeout=30)
    print("ECCOSESS_CANON",children,r.status_code,r.text[:3000])
    r.raise_for_status()
    return BASE+"/"+(r.text or "").strip().lstrip("/")

def driver():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,4000","--lang=pl-PL"]:
        o.add_argument(a)
    return webdriver.Chrome(options=o)

def total_mode(d):
    nodes=[]
    for e in d.find_elements(By.XPATH,"//*[self::label or self::button or self::span or self::a][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'ZA WSZYSTKICH')]"):
        try:
            if e.is_displayed(): nodes.append((len(compact(e.text)),e,compact(e.text)))
        except: pass
    nodes.sort(key=lambda z:z[0])
    for _,e,t in nodes:
        try:
            d.execute_script("arguments[0].click()",e);time.sleep(5)
            print("ECCOSESS_TOTAL_MODE",t)
            return True
        except: pass
    return False

def parse_price(txt):
    m=re.search(r"([0-9][0-9 ]{2,})\s*zł\s*/\s*razem",txt,re.I)
    return int(m.group(1).replace(" ","")) if m else None

def collect(label,url):
    d=driver()
    try:
        d.get(url);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5)
        print("ECCOSESS_PAGE",label,d.current_url,d.title)
        body=compact(d.find_element(By.TAG_NAME,"body").text)
        print("ECCOSESS_PARTY",label,"Dzieci : 5 lat, 7 lat" in body,"Dorosłych : 2" in body)
        total_mode(d)
        time.sleep(3)
        rows=[]
        seen=set()
        links=d.find_elements(By.XPATH,"//a[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'zobacz ofert')]")
        print("ECCOSESS_LINKS",label,len(links))
        for a in links[:80]:
            try:
                href=a.get_attribute("href") or ""
                if not href: continue
                anc=a
                best=""
                for _ in range(7):
                    txt=compact(anc.text)
                    if "zł/razem" in txt.lower() and len(txt)>len(best) and len(txt)<5000: best=txt
                    anc=anc.find_element(By.XPATH,"..")
                if not best: continue
                price=parse_price(best)
                if not price: continue
                # hotel is usually the first line before country; keep first meaningful phrase
                raw=a.find_element(By.XPATH,"../../..").text if a else ""
                lines=[compact(x) for x in raw.splitlines() if compact(x)]
                hotel=lines[0] if lines else ""
                # robust fallback: first phrase in card before country/date
                if not hotel or len(hotel)>180:
                    hotel=best.split(" ")[0:8]
                    hotel=" ".join(hotel)
                md=re.search(r"(\d{2}\.\d{2}\.\d{4}).{0,80}?(\d+)\s+dni\s*/\s*(\d+)\s+no",best,re.I)
                dep=md.group(1) if md else None
                nights=int(md.group(3)) if md else None
                tm=re.search(r"(?:Warszawa(?:\s*-\s*(?:Modlin|Radom))?)[^\d]{0,80}(\d{1,2}:\d{2})",best,re.I)
                dep_time=tm.group(1) if tm else None
                meal="All Inclusive" if "all inclusive" in best.lower() else ""
                path=urlsplit(href).path.rstrip("/")
                key=(path,dep,nights,meal.lower())
                if key in seen: continue
                seen.add(key)
                rec={"key":key,"hotel":hotel,"href":href,"price":price,"departure":dep,"departure_time":dep_time,"nights":nights,"meal":meal,"text":best[:1800]}
                rows.append(rec);print("ECCOSESS_ROW",label,json.dumps(rec,ensure_ascii=False))
            except Exception as e:
                print("ECCOSESS_ROW_ERR",label,type(e).__name__,str(e)[:180])
        print("ECCOSESS_ROWS",label,len(rows))
        return rows
    finally:
        d.quit()

def main():
    fu=canon(["5","7"]); au=canon([])
    fam=collect("FAMILY",fu); adults=collect("ADULTS",au)
    amap={tuple(x["key"]):x for x in adults}
    proofs=[]
    for f in fam:
        a=amap.get(tuple(f["key"]))
        if a and f["price"]!=a["price"]:
            p={"hotel":f["hotel"],"href":f["href"],"family_total":f["price"],"adult_total":a["price"],"departure":f["departure"],"departure_time":f["departure_time"],"nights":f["nights"],"meal":f["meal"]}
            proofs.append(p);print("ECCOSESS_PROOF",json.dumps(p,ensure_ascii=False))
    print("ECCOSESS_PARTY_SENSITIVE",len(proofs))
    print("ECCOSESS_FAMILY_TOTAL_VERIFIED",bool(proofs))

if __name__=="__main__": main()
