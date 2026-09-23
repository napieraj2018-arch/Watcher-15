import base64
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from watcher import chrome, create_alert, dismiss_cookies

TZ=ZoneInfo("Europe/Warsaw")
BASE="https://www.travelplanet.pl/wakacje/"
AIRPORTS={"WAW":"Warszawa","WMI":"Warszawa-Modlin","RDO":"Warszawa-Radom"}

def _number(v):
    try:return float(v)
    except:return None

def _item_price_fields(text):
    m=re.search(r"per:_([0-9.]+)_room:_([0-9.]+)_filter:_total_summary:_([0-9.]+)",str(text or ""))
    if not m:return None
    return tuple(float(x) for x in m.groups())

def _quality(text):
    m=re.search(r"s:_([0-9.]+)_r:_([0-9.]+)_o:_([0-9]+)",str(text or ""))
    if not m:return None,None,None
    stars=float(m.group(1)); rating5=float(m.group(2)); reviews=int(m.group(3))
    return stars,round(rating5*2,2),reviews

def _dates(text):
    m=re.search(r"departure:_(\d{4}-\d{2}-\d{2})_return:_(\d{4}-\d{2}-\d{2})",str(text or ""))
    if not m:return None,None
    return datetime.strptime(m.group(1),"%Y-%m-%d").date(),datetime.strptime(m.group(2),"%Y-%m-%d").date()

def _token_payload(token):
    try:
        part=token.split(".")[1]
        part += "="*((4-len(part)%4)%4)
        return json.loads(base64.urlsafe_b64decode(part.encode()).decode())
    except:return {}

def _token_exact_family(token,total):
    p=_token_payload(token)
    passengers=str(p.get("passengers") or "")
    if not re.fullmatch(r"AA(?:C\d+){2}",passengers):
        return False,p
    ages=sorted(int(x) for x in re.findall(r"C(\d+)",passengers))
    original=_number(p.get("originalTotalPrice"))
    return ages==[5,7] and original is not None and abs(original-total)<0.01,p

def _search_url(cfg, adults_only=False):
    today=datetime.now(TZ).date()
    ds=sorted(int(x) for x in cfg["depart_in_days"])
    start=today+timedelta(days=ds[0]); end=today+timedelta(days=ds[-1])
    q=[
      ("s_action","SEARCH_FORM_SEPARATED"),
      ("d_start_from",start.strftime("%d.%m.%Y")),("d_end_to",end.strftime("%d.%m.%Y")),
      ("nl_transportation_id[]","3"),("b_online_sale_customer","1"),
      ("duration",f"{cfg['min_nights']}-{cfg['max_nights']} days"),
      ("nl_length_from",str(cfg["min_nights"])),("nl_length_to",str(cfg["max_nights"])),
      ("nl_occupancy_adults","2"),("sort","nl_sell")
    ]
    if adults_only:
        q.append(("nl_occupancy_children","0"))
    else:
        q += [("nl_occupancy_children","2"),("nl_ages_children[]","5"),("nl_ages_children[]","7")]
    return BASE+"?"+urlencode(q,doseq=True),{today+timedelta(days=d) for d in ds}

def _read_items(driver,url,label):
    try:driver.execute_script("localStorage.removeItem('ga4_serp_items_last');localStorage.removeItem('ga4_serp_filters_last');")
    except:pass
    driver.get(url)
    WebDriverWait(driver,45).until(lambda d:d.execute_script("return document.readyState")=="complete")
    dismiss_cookies(driver)
    raw=""
    for _ in range(16):
        time.sleep(.75)
        raw=driver.execute_script("return localStorage.getItem('ga4_serp_items_last')||''")
        if raw and "itemsById" in raw:break
    filters=driver.execute_script("return localStorage.getItem('ga4_serp_filters_last')||''")
    print("TP_PROD_URL",label,driver.current_url)
    print("TP_PROD_FILTERS",label,filters[:1800])
    if not raw:
        print("TP_PROD_FAIL_CLOSED_NO_ITEMS",label)
        return {}
    try:
        data=json.loads(raw)
        items=data.get("itemsById") or {}
        print("TP_PROD_ITEM_COUNT",label,len(items))
        return items if isinstance(items,dict) else {}
    except Exception as e:
        print("TP_PROD_ITEMS_JSON_ERR",label,type(e).__name__,str(e)[:180])
        return {}

def _airport(item):
    code=str(item.get("item_parameter_3") or "").upper().strip()
    return AIRPORTS.get(code)

def _meal(item):
    x=str(item.get("item_parameter_8") or "")
    return "All Inclusive" if "board:_all_inclusive" in x.lower() else ""

def _stable_key(item,dep,ret,airport):
    base="|".join([str(item.get("item_id") or ""),dep.isoformat(),ret.isoformat(),airport,str(item.get("item_brand") or "")])
    return hashlib.sha1(base.encode()).hexdigest()[:16]

def _parse_family_items(items,cfg,allowed,url):
    out=[]
    for item in items.values():
        if not isinstance(item,dict):continue
        if str(item.get("item_parameter_9") or "")!="adult:_2_child:_2":continue
        if str(item.get("item_parameter_10") or "")!="age:_5,7":continue
        prices=_item_price_fields(item.get("item_parameter_1"))
        if not prices:continue
        per,room,total=prices
        value=_number(item.get("value"));price=_number(item.get("price"))
        if value is None or price is None or abs(value-total)>.01 or abs(price-total)>.01:continue
        # Deliberately reject child-free edge cases: a family total that is only
        # two adult unit prices is too ambiguous for this watcher.
        if total <= (2*per):continue
        token=str(item.get("item_offer_id") or "")
        exact,payload=_token_exact_family(token,total)
        if not exact:
            print("TP_PROD_REJECT_TOKEN",item.get("item_id"),payload.get("passengers"),payload.get("originalTotalPrice"),total)
            continue
        dep,ret=_dates(item.get("item_parameter_7"))
        if not dep or not ret or dep not in allowed:continue
        nights=(ret-dep).days
        if not (cfg["min_nights"]<=nights<=cfg["max_nights"]):continue
        airport=_airport(item)
        if not airport:continue
        meal=_meal(item)
        if cfg["meal_contains"].lower() not in meal.lower():continue
        stars,rating,reviews=_quality(item.get("item_parameter_4"))
        hotel=str(item.get("item_name") or "").strip()
        if not hotel:continue
        offer={
          "key":_stable_key(item,dep,ret,airport),"hotel":hotel,"href":url,"verified_href":url,
          "price":int(round(total)),"departure":dep,"return":ret,"nights":nights,"airport":airport,
          "meal":meal,"operator":"Travelplanet / "+str(item.get("item_brand") or "operator"),
          "rating":rating,"reviews":reviews,"stars":stars,
          "travelplanet_item_id":str(item.get("item_id") or ""),"offer_token":token,
          "family_price_proof":"adult:_2_child:_2 + age:_5,7 + AAC5C7 JWT + total_summary > 2*per"
        }
        out.append(offer)
        print("TP_PROD_EXACT_CARD",offer)
    return out

def _quality_ok(x,cfg):
    return (
      x["price"]<=cfg["max_total_price_pln"] and
      x["stars"] is not None and x["stars"]>=cfg["min_stars"] and
      x["rating"] is not None and x["rating"]>=cfg["min_rating"] and
      x["reviews"] is not None and x["reviews"]>=cfg["min_reviews"]
    )

def _fetch(driver,cfg):
    url,allowed=_search_url(cfg,False)
    items=_read_items(driver,url,"FAMILY")
    return _parse_family_items(items,cfg,allowed,url)

def run_travelplanet_watcher(cfg):
    if cfg.get("adults")!=2 or cfg.get("children_ages")!=[5,7]:
        raise RuntimeError("Travelplanet production adapter is locked to exact 2+2 ages 5/7")
    driver=chrome()
    try:
        first=_fetch(driver,cfg)
        qualified=[x for x in first if _quality_ok(x,cfg)]
        print("TP_PROD_QUALIFIED",len(qualified))
        if first and not qualified:print("TP_PROD_QUALITY_OR_PRICE_FAIL_CLOSED")
        token=os.getenv("GITHUB_TOKEN","");repo=os.getenv("GITHUB_REPOSITORY","")
        for cand in qualified[:10]:
            fresh=_fetch(driver,cfg)
            confirmed=next((x for x in fresh if x["key"]==cand["key"] and _quality_ok(x,cfg)),None)
            if not confirmed:
                print("TP_PROD_RECHECK_REJECT",cand["key"]);continue
            print("TP_PROD_RECHECK_VERIFIED",confirmed["hotel"],confirmed["price"],confirmed["family_price_proof"])
            if token and repo:
                create_alert(token,repo,cfg,confirmed,"Travelplanet exact 2+2 ages 5/7; live result item; total_summary bound to adult:_2_child:_2, age:_5,7 and AAC5C7 offer token; second live recheck")
            else:print("TP_PROD_DRY_ALERT",confirmed)
    finally:driver.quit()
