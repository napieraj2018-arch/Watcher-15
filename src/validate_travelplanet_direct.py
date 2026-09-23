import json,time,re
from urllib.parse import urlencode,urlsplit,parse_qs
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://www.travelplanet.pl/wakacje/"
COMMON=[
 ("b_online_sale_customer","1"),("d_start_from","24.09.2026"),("d_end_to","26.09.2026"),
 ("duration","5-8 days"),("nl_length_from","5"),("nl_length_to","8"),
 ("nl_transportation_id[]","3"),("nl_occupancy_adults","2"),
 ("s_action","SEARCH_FORM_SEPARATED"),("sort","nl_sell")
]
VARIANTS=[
 ("array",[("nl_occupancy_children","2"),("nl_ages_children[]","5"),("nl_ages_children[]","7")]),
 ("repeat",[("nl_occupancy_children","2"),("nl_ages_children","5"),("nl_ages_children","7")]),
 ("comma",[("nl_occupancy_children","2"),("nl_ages_children","5,7")]),
]
def store(d,kind,key):
    try:return d.execute_script("return window."+kind+".getItem(arguments[0])",key) or ""
    except:return ""
def main():
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3000");o.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=o)
    try:
      for label,extra in VARIANTS:
        u=BASE+"?"+urlencode(COMMON+extra,doseq=True)
        d.get(u);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(7)
        print("TP_NATIVE_VARIANT",label,d.current_url)
        print("TP_NATIVE_QS",label,json.dumps(parse_qs(urlsplit(d.current_url).query),ensure_ascii=False,sort_keys=True))
        filt=store(d,"localStorage","ga4_serp_filters_last")
        items=store(d,"localStorage","ga4_serp_items_last")
        occ=store(d,"sessionStorage","searchPreferencesOccupancy")
        print("TP_NATIVE_OCCUPANCY",label,occ)
        print("TP_NATIVE_FILTERS",label,filt[:2500])
        kid2=len(re.findall(r'adult:_?2_child:_?2',items,re.I));kid0=len(re.findall(r'adult:_?2_child:_?0',items,re.I))
        print("TP_NATIVE_ITEM_COUNTS",label,{"child2":kid2,"child0":kid0,"items_len":len(items)})
        try:
            data=json.loads(items); vals=list((data.get("itemsById") or {}).values())
            for x in vals[:12]:
                print("TP_NATIVE_ITEM",label,{"id":x.get("item_id"),"price":x.get("item_parameter_1"),"party":x.get("item_parameter_9"),"airport":x.get("item_parameter_3"),"stay":x.get("item_parameter_7"),"meal":x.get("item_parameter_8")})
        except Exception as e: print("TP_NATIVE_ITEMS_PARSE_ERR",label,type(e).__name__)
        ok=('"kids":"2"' in filt or '"kids":2' in filt or kid2>0)
        print("TP_NATIVE_EXACT_FAMILY_ACCEPTED",label,ok)
    finally:d.quit()
if __name__=="__main__":main()


# ---- Production adapter -------------------------------------------------
# Kept in this module so the same native query proof used by diagnostics is
# exactly the mechanism used by the production channel.
import hashlib
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from watcher import chrome, create_alert

TZ=ZoneInfo("Europe/Warsaw")

def _tp_float(text, name):
    m=re.search(r"(?:^|_)"+re.escape(name)+r":_([0-9]+(?:\.[0-9]+)?)",str(text or ""))
    return float(m.group(1)) if m else None

def _tp_token(text, name):
    m=re.search(r"(?:^|_)"+re.escape(name)+r":_([^_]+)",str(text or ""))
    return m.group(1) if m else None

def _tp_url(cfg, family=True):
    today=datetime.now(TZ).date()
    ds=sorted(int(x) for x in cfg["depart_in_days"])
    start=today+timedelta(days=ds[0]); end=today+timedelta(days=ds[-1])
    p=[
      ("b_online_sale_customer","1"),
      ("d_start_from",start.strftime("%d.%m.%Y")),
      ("d_end_to",end.strftime("%d.%m.%Y")),
      ("duration",f"{cfg['min_nights']}-{cfg['max_nights']} days"),
      ("nl_length_from",str(cfg["min_nights"])),
      ("nl_length_to",str(cfg["max_nights"])),
      ("nl_transportation_id[]","3"),
      ("nl_occupancy_adults","2"),
      ("s_action","SEARCH_FORM_SEPARATED"),
      ("sort","nl_sell"),
    ]
    if family:
        p += [("nl_occupancy_children","2"),("nl_ages_children[]","5"),("nl_ages_children[]","7")]
    else:
        p += [("nl_occupancy_children","0")]
    return BASE+"?"+urlencode(p), {today+timedelta(days=d) for d in ds}

def _tp_parse_item(x, cfg, allowed, href, require_family):
    if not isinstance(x,dict): return None
    party=str(x.get("item_parameter_9") or "")
    ages=str(x.get("item_parameter_10") or "")
    if require_family:
        if party!="adult:_2_child:_2": return None
        if ages not in ("age:_5,7","age:_7,5"): return None
    else:
        if party!="adult:_2_child:_0": return None

    price_blob=str(x.get("item_parameter_1") or "")
    total=_tp_float(price_blob,"total_summary")
    per=_tp_float(price_blob,"per")
    if total is None or per is None or total<=0 or total==per: return None
    # create_alert's historical dedupe marker is integer PLN. Fail closed on
    # fractional internal totals instead of silently rounding a final price.
    if abs(total-round(total))>1e-9: return None
    total=int(round(total))

    dates=str(x.get("item_parameter_7") or "")
    md=re.search(r"departure:_(\d{4}-\d{2}-\d{2})_return:_(\d{4}-\d{2}-\d{2})",dates)
    if not md: return None
    dep=datetime.strptime(md.group(1),"%Y-%m-%d").date()
    ret=datetime.strptime(md.group(2),"%Y-%m-%d").date()
    nights=(ret-dep).days
    if dep not in allowed or not (int(cfg["min_nights"])<=nights<=int(cfg["max_nights"])): return None

    board=str(x.get("item_parameter_8") or "")
    if "board:_all_inclusive" not in board.lower(): return None

    code=str(x.get("item_parameter_3") or "").upper()
    airport={"RDO":"Warszawa - Radom","WMI":"Warszawa - Modlin","WAW":"Warszawa"}.get(code)
    if not airport: return None

    quality=str(x.get("item_parameter_4") or "")
    stars=_tp_float(quality,"s")
    rating=_tp_float(quality,"r")
    reviews=_tp_float(quality,"o")
    if rating is not None and rating<=5: rating*=2
    if stars is None or rating is None or reviews is None: return None

    hotel=str(x.get("item_name") or "").strip()
    item_id=str(x.get("item_id") or "").strip()
    if not hotel or not item_id: return None
    stable="|".join([item_id,dep.isoformat(),ret.isoformat(),code,board])
    return {
      "key":hashlib.sha1(stable.encode()).hexdigest()[:16],
      "control_key":stable,
      "hotel":hotel,
      "href":href,
      "verified_href":href,
      "price":total,
      "per_price":per,
      "departure":dep,
      "return":ret,
      "nights":nights,
      "airport":airport,
      "meal":"All Inclusive",
      "operator":"Travelplanet",
      "rating":rating,
      "reviews":int(reviews),
      "stars":int(stars),
    }

def _tp_fetch(driver,cfg,family=True):
    url,allowed=_tp_url(cfg,family)
    driver.get(url)
    WebDriverWait(driver,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
    time.sleep(7)
    filters=driver.execute_script("return localStorage.getItem('ga4_serp_filters_last')||''")
    raw=driver.execute_script("return localStorage.getItem('ga4_serp_items_last')||''")
    try: fp=json.loads(filters).get("filters",{}).get("participants",{})
    except Exception: fp={}
    expected={"total":"4","adults":"2","kids":"2"} if family else {"total":"2","adults":"2","kids":"0"}
    if any(str(fp.get(k))!=v for k,v in expected.items()):
        print("TP_FAIL_CLOSED_PARTY",family,fp,expected); return []
    try: vals=list((json.loads(raw).get("itemsById") or {}).values())
    except Exception as e:
        print("TP_FAIL_CLOSED_ITEMS",type(e).__name__); return []
    out=[]
    for x in vals:
        v=_tp_parse_item(x,cfg,allowed,url,family)
        if v: out.append(v)
    print("TP_LIVE_ROWS", "FAMILY" if family else "ADULTS", len(out))
    return out

def _tp_quality_ok(x,cfg):
    return (
      x["price"]<=int(cfg["max_total_price_pln"])
      and x["stars"]>=int(cfg["min_stars"])
      and x["rating"]>=float(cfg["min_rating"])
      and x["reviews"]>=int(cfg["min_reviews"])
    )

def run_travelplanet_watcher(cfg):
    if cfg.get("adults")!=2 or cfg.get("children_ages")!=[5,7]:
        raise RuntimeError("Travelplanet production adapter is locked to exact 2+2 ages 5/7")
    d=chrome()
    try:
        fam=_tp_fetch(d,cfg,True)
        adults=_tp_fetch(d,cfg,False)
        amap={x["control_key"]:x["price"] for x in adults}
        proven=[]
        for x in fam:
            adult_total=amap.get(x["control_key"])
            # Same package must price differently for 2+2 than for 2 adults.
            if adult_total is None or adult_total==x["price"]:
                print("TP_REJECT_NO_PARTY_PRICE_PROOF",x["hotel"],x["price"],adult_total); continue
            x["adult_only_total"]=adult_total
            if _tp_quality_ok(x,cfg): proven.append(x)
        print("TP_PARTY_SENSITIVE_QUALIFIED",len(proven))

        token=os.getenv("GITHUB_TOKEN",""); repo=os.getenv("GITHUB_REPOSITORY","")
        for candidate in proven[:10]:
            fresh=_tp_fetch(d,cfg,True)
            confirmed=next((x for x in fresh if x["control_key"]==candidate["control_key"] and x["price"]==candidate["price"] and _tp_quality_ok(x,cfg)),None)
            if not confirmed:
                print("TP_RECHECK_REJECT",candidate["hotel"]); continue
            print("TP_RECHECK_VERIFIED",confirmed["hotel"],confirmed["price"])
            if token and repo:
                create_alert(token,repo,cfg,confirmed,
                  "Travelplanet exact 2+2 ages 5/7 + live total_summary family price + adults-only control + second live recheck")
            else:
                print("TP_DRY_ALERT",confirmed)
    finally:
        d.quit()
