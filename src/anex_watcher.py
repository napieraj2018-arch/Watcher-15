import hashlib
import os
import re
import time
from datetime import datetime,timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from watcher import chrome, create_alert

TZ=ZoneInfo("Europe/Warsaw")
BASE="https://search.anextour.com.pl/search_tour"

def compact(s): return " ".join((s or "").split())

def _url(cfg,townfrom=None):
    today=datetime.now(TZ).date()
    ds=sorted(int(x) for x in cfg["depart_in_days"])
    q=[
      ("ADULT","2"),("CHILD","2"),("AGE1","5"),("AGE2","7"),("LANG","pol"),
      ("CHECKIN_BEG",(today+timedelta(days=ds[0])).strftime("%Y%m%d")),
      ("CHECKIN_END",(today+timedelta(days=ds[-1])).strftime("%Y%m%d")),
      ("NIGHTS_FROM",str(cfg["min_nights"])),("NIGHTS_TILL",str(cfg["max_nights"]))
    ]
    if townfrom is not None:
        q.append(("TOWNFROMINC",str(townfrom)))
    return BASE+"?"+urlencode(q),{today+timedelta(days=d) for d in ds}

def _click_search(d):
    for b in d.find_elements(By.XPATH,"//button|//input[@type='submit']"):
        try:
            txt=(compact(b.text)+" "+(b.get_attribute("value") or "")).lower()
            if b.is_displayed() and "szukaj" in txt:
                d.execute_script("arguments[0].click()",b);return True
        except: pass
    return False

def _stars(text):
    m=re.search(r"([1-5])\*{3,5}",text or "")
    return int(m.group(1)) if m else None

def _route_airport(route,cfg):
    r=(route or "").upper()
    if "RADOM" in r:
        for a in cfg["airports"]:
            if "radom" in a.lower(): return a
    if "WARSAW" in r or "WARSZAWA" in r:
        for a in cfg["airports"]:
            if "warszawa" in a.lower() and "radom" not in a.lower() and "modlin" not in a.lower(): return a
    return None

def _read(cfg,townfrom=None):
    url,allowed=_url(cfg,townfrom)
    d=chrome()
    try:
        d.get(url);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(5);_click_search(d);time.sleep(9)
        print("ANEX_PROD_URL",d.current_url)
        offers=[];seen=set()
        for tr in d.find_elements(By.CSS_SELECTOR,"tr.price_info"):
            try:
                cls=tr.get_attribute("class") or ""
                if "adult-2" not in cls or "child-2" not in cls: continue
                checkin=tr.get_attribute("data-checkin") or ""
                if len(checkin)!=8: continue
                dep=datetime.strptime(checkin,"%Y%m%d").date()
                if dep not in allowed: continue
                nights=int(tr.get_attribute("data-nights") or "0")
                if not cfg["min_nights"]<=nights<=cfg["max_nights"]: continue
                cells=[compact(td.text) for td in tr.find_elements(By.CSS_SELECTOR,"td")]
                meal=next((x for x in cells if "All Inclusive" in x),"")
                if cfg["meal_contains"].lower() not in meal.lower(): continue
                room=next((x for x in cells if "2+2" in x),"")
                if not room: continue

                av=[x.get_attribute("title") for x in tr.find_elements(By.CSS_SELECTOR,".hotel_availability") if x.get_attribute("title")]
                flights=[x.get_attribute("title") for x in tr.find_elements(By.CSS_SELECTOR,".fr_place_r,.fr_place_l") if x.get_attribute("title")]
                if not any(x in ("Dostępne","Ostatnie miejsca") for x in av): continue
                if not any("Miejsca dostępne" in x for x in flights): continue

                price_el=tr.find_elements(By.CSS_SELECTOR,"[data-converted-price-number]")
                if not price_el: continue
                raw=price_el[0].get_attribute("data-converted-price-number") or ""
                if not raw.isdigit(): continue
                total=int(raw)

                hotel_cell=tr.find_elements(By.CSS_SELECTOR,"td.link-hotel")
                hotel=compact(hotel_cell[0].text) if hotel_cell else ""
                if not hotel: continue
                stars=_stars(hotel)
                route_el=tr.find_elements(By.CSS_SELECTOR,"td.tour")
                route=compact(route_el[0].text) if route_el else ""
                airport=_route_airport(route,cfg)
                if not airport: continue

                stable="|".join([
                  checkin,str(nights),tr.get_attribute("data-hotel") or "",
                  tr.get_attribute("data-tour") or "",tr.get_attribute("data-meal") or "",
                  tr.get_attribute("data-townfrom") or ""
                ])
                key=hashlib.sha1(stable.encode()).hexdigest()[:16]
                if key in seen: continue
                seen.add(key)
                href=""
                links=tr.find_elements(By.CSS_SELECTOR,"td.link-hotel a[href]")
                if links: href=links[0].get_attribute("href") or ""
                offer={
                  "key":key,"hotel":hotel,"href":href or url,"verified_href":href or url,
                  "price":total,"departure":dep,"return":dep+timedelta(days=nights),"nights":nights,
                  "airport":airport,"meal":meal,"operator":"ANEX Tour Poland",
                  "stars":stars,"rating":None,"reviews":None,
                  "room":room,"availability":av,"flight_availability":flights,
                  "family_price_proof":"exact SAMO row adult-2 child-2 + AGES=5,7 + explicit converted PLN total"
                }
                offers.append(offer);print("ANEX_PROD_EXACT_CARD",offer)
            except Exception as e:
                print("ANEX_PROD_ROW_ERR",type(e).__name__,str(e)[:160])
        print("ANEX_PROD_EXACT_COUNT",len(offers))
        return offers
    finally:d.quit()

def _quality_ok(x,cfg):
    return (
      x["price"]<=cfg["max_total_price_pln"] and
      x["stars"] is not None and x["stars"]>=cfg["min_stars"] and
      x["rating"] is not None and x["rating"]>=cfg["min_rating"] and
      x["reviews"] is not None and x["reviews"]>=cfg["min_reviews"]
    )

def run_anex_watcher(cfg):
    if cfg.get("adults")!=2 or cfg.get("children_ages")!=[5,7]:
        raise RuntimeError("ANEX adapter is locked to exact 2+2 ages 5/7")
    first=[]
    # SAMO defaults to Gdańsk when TOWNFROMINC is omitted. Query the user's
    # relevant departure cities explicitly: Warszawa=1885, Radom=2200.
    for townfrom in cfg.get("anex_townfrom_ids",[1885,2200]):
        first.extend(_read(cfg,townfrom))
    dedup={}
    for x in first:
        old=dedup.get(x["key"])
        if old is None or x["price"]<old["price"]:
            dedup[x["key"]]=x
    first=list(dedup.values())
    qualified=[x for x in first if _quality_ok(x,cfg)]
    print("ANEX_PROD_QUALIFIED",len(qualified))
    if first and not qualified: print("ANEX_PROD_QUALITY_FAIL_CLOSED")
    token=os.getenv("GITHUB_TOKEN","");repo=os.getenv("GITHUB_REPOSITORY","")
    for cand in qualified[:10]:
        fresh=[]
        for townfrom in cfg.get("anex_townfrom_ids",[1885,2200]):
            fresh.extend(_read(cfg,townfrom))
        confirmed=next((x for x in fresh if x["key"]==cand["key"] and x["price"]==cand["price"] and _quality_ok(x,cfg)),None)
        if not confirmed:
            print("ANEX_PROD_RECHECK_REJECT",cand["key"]);continue
        print("ANEX_PROD_RECHECK_VERIFIED",confirmed["hotel"],confirmed["price"])
        if token and repo:
            create_alert(token,repo,cfg,confirmed,"ANEX exact 2+2 ages 5/7 + live SAMO availability + verified family-price semantics + second live recheck")
        else:
            print("ANEX_PROD_DRY_ALERT",confirmed)
