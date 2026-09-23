import json,re,time
from datetime import datetime,timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://search.anextour.com.pl/search_tour"
TZ=ZoneInfo("Europe/Warsaw")

def compact(s): return " ".join((s or "").split())

def family_url():
    today=datetime.now(TZ).date()
    q=[
      ("ADULT","2"),("CHILD","2"),("AGE1","5"),("AGE2","7"),("LANG","pol"),
      ("CHECKIN_BEG",(today+timedelta(days=1)).strftime("%Y%m%d")),
      ("CHECKIN_END",(today+timedelta(days=3)).strftime("%Y%m%d")),
      ("NIGHTS_FROM","5"),("NIGHTS_TILL","8")
    ]
    return BASE+"?"+urlencode(q)

def click_search(d):
    for b in d.find_elements(By.XPATH,"//button|//input[@type='submit']"):
        try:
            txt=(compact(b.text)+" "+(b.get_attribute("value") or "")).lower()
            if b.is_displayed() and "szukaj" in txt:
                d.execute_script("arguments[0].click()",b);return True
        except:pass
    return False

def dom_candidates(d):
    out=[]
    for tr in d.find_elements(By.CSS_SELECTOR,"tr.price_info"):
        try:
            cls=tr.get_attribute("class") or ""
            if "adult-2" not in cls or "child-2" not in cls:continue
            nights=int(tr.get_attribute("data-nights") or "0")
            if not 5<=nights<=8:continue
            cells=[compact(x.text) for x in tr.find_elements(By.CSS_SELECTOR,"td")]
            if not any("All Inclusive" in x for x in cells):continue
            room=next((x for x in cells if "2+2" in x),"")
            if not room:continue
            av=[x.get_attribute("title") for x in tr.find_elements(By.CSS_SELECTOR,".hotel_availability") if x.get_attribute("title")]
            if not any(x in ("Dostępne","Ostatnie miejsca") for x in av):continue
            priceel=tr.find_elements(By.CSS_SELECTOR,"[data-converted-price-number]")
            if not priceel:continue
            price=int(priceel[0].get_attribute("data-converted-price-number"))
            rec={
              "checkin":tr.get_attribute("data-checkin"),"nights":nights,
              "town":tr.get_attribute("data-townfrom"),"state":tr.get_attribute("data-state"),
              "tour":tr.get_attribute("data-tour"),"hotel":tr.get_attribute("data-hotel"),
              "room":tr.get_attribute("data-room"),"meal":tr.get_attribute("data-meal"),
              "family_total":price,"room_text":room,
              "hotel_name":compact(tr.find_element(By.CSS_SELECTOR,"td.link-hotel").text) if tr.find_elements(By.CSS_SELECTOR,"td.link-hotel") else "",
              "availability":av
            }
            out.append(rec)
        except Exception:pass
    return out

def prices_params(c,family):
    return {
      "LANG":"pol","samo_action":"PRICES","TOWNFROMINC":c["town"],"STATEINC":c["state"] or "10",
      "TOURTYPE":"0","TOURINC":"0","PROGRAMINC":"0",
      "CHECKIN_BEG":c["checkin"],"CHECKIN_END":c["checkin"],
      "NIGHTS_FROM":str(c["nights"]),"NIGHTS_TILL":str(c["nights"]),
      "ADULT":"2","CURRENCY":"4","CHILD":"2" if family else "0",
      "TOWNS_ANY":"1","townssearch":"0","TOWNS":"",
      "STARS_ANY":"1","STARS":"","HOTELS_ANY":"1","hotelsearch":"0","HOTELS":"",
      "MEALS_ANY":"1","MEALS":"","ROOMS_ANY":"1","ROOMS":"",
      "CHILD_IN_BED":"0","FREIGHT":"0","COMFORTABLE_SEATS":"0","FILTER":"1",
      "MOMENT_CONFIRM":"0","UFILTER":"","HOTELTYPES":"","PARTITION_PRICE":"224",
      "PRICEPAGE":"1","DYN_SEPARATE":"1","AGES":"5,7" if family else ""
    }

def browser_fetch(d,url):
    d.set_script_timeout(55)
    return d.execute_async_script("""
      const url=arguments[0],done=arguments[arguments.length-1];
      fetch(url,{credentials:'include',headers:{'X-Requested-With':'XMLHttpRequest'}})
        .then(async r=>done(JSON.stringify({status:r.status,text:await r.text()})))
        .catch(e=>done(JSON.stringify({status:0,error:String(e),text:''})));
    """,url)

def unwrap(raw):
    try:obj=json.loads(raw)
    except:return raw
    def walk(x,depth=0):
        if depth>10:return None
        if isinstance(x,str):
            if "price_info" in x:return x
            try:
                y=json.loads(x)
                z=walk(y,depth+1)
                if z:return z
            except:pass
        elif isinstance(x,dict):
            for v in x.values():
                z=walk(v,depth+1)
                if z:return z
        elif isinstance(x,list):
            for v in x:
                z=walk(v,depth+1)
                if z:return z
        return None
    return walk(obj) or raw

def rows(raw,family):
    html=unwrap(raw)
    soup=BeautifulSoup(html,"html.parser")
    out={}
    for tr in soup.select("tr.price_info"):
        cls=" ".join(tr.get("class",[]))
        if "adult-2" not in cls:continue
        if family and "child-2" not in cls:continue
        if not family and re.search(r"\bchild-[1-9]\d*\b",cls):continue
        pe=tr.select_one("[data-converted-price-number]")
        if not pe:continue
        rawp=pe.get("data-converted-price-number") or ""
        if not rawp.isdigit():continue
        key=(
          tr.get("data-checkin") or "",tr.get("data-nights") or "",
          tr.get("data-hotel") or "",tr.get("data-tour") or "",
          tr.get("data-room") or "",tr.get("data-meal") or "",
          tr.get("data-townfrom") or ""
        )
        av=[x.get("title") for x in tr.select(".hotel_availability") if x.get("title")]
        flights=[x.get("title") for x in tr.select(".fr_place_r,.fr_place_l") if x.get("title")]
        out[key]={"price":int(rawp),"availability":av,"flights":flights}
    return out

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]:o.add_argument(a)
    d=webdriver.Chrome(options=o)
    try:
        d.get(family_url());WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5)
        click_search(d);time.sleep(9)
        cands=dom_candidates(d)
        print("ANEXSESS_CANDIDATES",len(cands))
        for c in cands[:8]:print("ANEXSESS_CAND",json.dumps(c,ensure_ascii=False))
        proofs=[]
        for c in cands[:8]:
            sets={}
            for label,fam in [("FAMILY",True),("ADULTS",False)]:
                url=BASE+"?"+urlencode(prices_params(c,fam))
                res=json.loads(browser_fetch(d,url))
                print("ANEXSESS_FETCH",label,res.get("status"),url)
                rr=rows(res.get("text") or "",fam)
                print("ANEXSESS_ROWS",label,len(rr))
                sets[label]=rr
            key=(c["checkin"],str(c["nights"]),c["hotel"],c["tour"],c["room"],c["meal"],c["town"])
            f=sets["FAMILY"].get(key);a=sets["ADULTS"].get(key)
            if not f or not a:continue
            live=any(x in ("Dostępne","Ostatnie miejsca") for x in f["availability"]) and any("Miejsca dostępne" in x for x in f["flights"])
            rec={"key":key,"hotel":c["hotel_name"],"family_total":f["price"],"adults_total":a["price"],"delta":f["price"]-a["price"],"live":live,"availability":f["availability"],"flights":f["flights"]}
            print("ANEXSESS_MATCH",json.dumps(rec,ensure_ascii=False))
            if live and f["price"]>a["price"]:proofs.append(rec)
        print("ANEXSESS_PARTY_SENSITIVE",len(proofs))
        for p in proofs:print("ANEXSESS_PROOF",json.dumps(p,ensure_ascii=False))
        print("ANEXSESS_FAMILY_TOTAL_VERIFIED",bool(proofs))
    finally:d.quit()
if __name__=="__main__":main()
