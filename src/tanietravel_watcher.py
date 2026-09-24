import hashlib,json,os,re,time
from datetime import datetime,timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
import requests
from watcher import create_alert, configured_departure_dates

TZ=ZoneInfo("Europe/Warsaw")
API="https://www.katowice-travel.pl/api/search_offers.php"
BASE="https://www.katowice-travel.pl/"
HEADERS={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
         "Accept":"application/json,text/plain,*/*","Referer":BASE,"Content-Type":"application/json"}

def _payload(cfg,family):
    dates=configured_departure_dates(cfg)
    p = {
      "type":"tours","favoritesOnly":False,
      "dateFrom":dates[0].isoformat(),
      "dateTo":dates[-1].isoformat(),
      "stars":"4plus","adults":2,"children":2 if family else 0,
      "childAges":"5,7" if family else "",
      "meal":"ai","limit":500,
      "depCode":",".join(cfg.get("airport_codes",["WAW","WMI","RDO"])),
      "nights":f'{cfg["min_nights"]}:{cfg["max_nights"]}'
    }
    dest=int(cfg.get("destination_id",0) or 0)
    if dest>0:
        p["destinationId"]=dest
    return p

def _post(label,p):
    last=None
    for attempt in range(3):
        try:
            r=requests.post(API,json=p,headers=HEADERS,timeout=45)
            print("TANIE_PROD_STATUS",label,attempt+1,r.status_code,len(r.content))
            r.raise_for_status()
            data=r.json()
            if not isinstance(data,dict):
                print("TANIE_PROD_FAIL_CLOSED_NON_DICT",label,type(data).__name__);return {}
            return data
        except (requests.RequestException,ValueError) as exc:
            last=exc;print("TANIE_PROD_RETRY",label,attempt+1,type(exc).__name__,str(exc)[:220])
            if attempt<2:time.sleep(1.5*(attempt+1))
    print("TANIE_PROD_SOURCE_FAIL_CLOSED",label,type(last).__name__ if last else "unknown")
    return {}

def _items(data):
    rows=data.get("items") or []
    if isinstance(rows,dict):rows=[rows]
    return [x for x in rows if isinstance(x,dict)]

def _s(x):
    return "" if x in (None,"") else str(x)

def _key(x):
    return (
      _s(x.get("offerHash")),_s(x.get("htlCode") or x.get("xCode")),_s(x.get("hotel_name")),
      _s(x.get("departureDate")),_s(x.get("returnDate")),_s(x.get("duration")),
      _s(x.get("roomDesc")),_s(x.get("depCode")),_s(x.get("desCode")),_s(x.get("xServiceId"))
    )

def _price(x):
    try:return int(round(float(str(x.get("price")).replace(",","."))))
    except:return None

def _date(v):
    try:return datetime.strptime(str(v),"%Y-%m-%d").date()
    except:return None

def _airport(code,cfg):
    code=str(code or "").upper()
    aliases={"RDO":"Warszawa - Radom","WMI":"Warszawa - Modlin","WAW":"Warszawa"}
    raw=aliases.get(code,code)
    for wanted in cfg["airports"]:
        wl=wanted.lower().replace("-"," ")
        rl=raw.lower().replace("-"," ")
        if ("radom" in wl and "radom" in rl) or ("modlin" in wl and "modlin" in rl) or (wl=="warszawa" and rl=="warszawa"):
            return wanted
    return None

def _rating(x):
    try:
        v=float(str(x.get("hotelRating")).replace(",","."))
        return v*2 if 0<v<=5 else v
    except:return None

def _reviews(x):
    try:return int(x.get("reviewsCountAll"))
    except:return None

def _clock(v):
    raw=re.sub(r"\D","",str(v or ""))
    if len(raw)==3: raw="0"+raw
    if len(raw)!=4:return None
    hh,mm=int(raw[:2]),int(raw[2:])
    if not (0<=hh<=23 and 0<=mm<=59):return None
    return f"{hh:02d}:{mm:02d}"

def _stars(x):
    raw=re.sub(r"\D","",str(x.get("category") or ""))
    if not raw:return None
    # TanieTravel returns categories such as 40 / 50 for 4★ / 5★.
    n=int(raw)
    if n in range(1,6):return n
    if n%10==0 and 10<=n<=50:return n//10
    return None

def _direct_offer_url(x):
    offer_hash=str(x.get("offerHash") or "").strip()
    if not offer_hash:
        return None
    return BASE+"offer.php?"+urlencode({
      "id":offer_hash,
      "adults":2,
      "children":2,
      "ages":"5,7"
    })

def _plain_html(text):
    text=re.sub(r"<[^>]+>"," ",text or "")
    text=(text.replace("&nbsp;"," ").replace("&oacute;","ó").replace("&Oacute;","Ó")
              .replace("&aogon;","ą").replace("&Aogon;","Ą").replace("&eogon;","ę")
              .replace("&Eogon;","Ę").replace("&lstrok;","ł").replace("&Lstrok;","Ł")
              .replace("&sacute;","ś").replace("&Sacute;","Ś").replace("&cacute;","ć")
              .replace("&Cacute;","Ć").replace("&nacute;","ń").replace("&Nacute;","Ń")
              .replace("&zacute;","ź").replace("&Zacute;","Ź").replace("&zdot;","ż")
              .replace("&Zdot;","Ż"))
    return " ".join(text.lower().split())

def _verify_direct_offer_link(x):
    url=_direct_offer_url(x)
    if not url:
        print("TANIE_DIRECT_LINK_MISSING_HASH",x.get("hotel_name"))
        return None
    try:
        r=requests.get(url,headers={"User-Agent":HEADERS["User-Agent"],"Accept":"text/html,*/*"},timeout=45,allow_redirects=True)
        print("TANIE_DIRECT_LINK_STATUS",r.status_code,r.url)
        r.raise_for_status()
    except requests.RequestException as exc:
        print("TANIE_DIRECT_LINK_FAIL",type(exc).__name__,str(exc)[:220])
        return None

    final=r.url or url
    parts=urlsplit(final)
    q=parse_qs(parts.query)
    expected=str(x.get("offerHash") or "").strip()
    # The offer page is a JS shell: hotel/family text is injected client-side
    # and is not present in the raw HTML returned to requests. Treat the link
    # as concrete only when it stays on offer.php, preserves the exact live
    # offerHash and exact 2+2 party parameters, and does not fall back to
    # results/stale pages. Exact family/price/live proof still comes from the
    # two fresh API reads plus same-package 2+0 control below.
    if not parts.path.lower().endswith("/offer.php"):
        print("TANIE_DIRECT_LINK_NOT_CONCRETE",final)
        return None
    if (q.get("id") or [""])[0] != expected:
        print("TANIE_DIRECT_LINK_HASH_MISMATCH",expected,final)
        return None
    if (q.get("adults") or [""])[0] != "2" or (q.get("children") or [""])[0] != "2":
        print("TANIE_DIRECT_LINK_PARTY_MISMATCH",final)
        return None
    if (q.get("ages") or [""])[0] not in ("5,7","7,5"):
        print("TANIE_DIRECT_LINK_AGES_MISMATCH",final)
        return None
    if "stale_offer=1" in final.lower():
        print("TANIE_DIRECT_LINK_STALE",final)
        return None
    return final

def _certified_rows(cfg):
    if cfg.get("adults")!=2 or cfg.get("children_ages")!=[5,7]:
        raise RuntimeError("TanieTravel adapter locked to exact 2+2 ages 5/7")
    fp=_payload(cfg,True);ap=_payload(cfg,False)
    print("TANIE_PROD_EXACT_PAYLOAD",json.dumps(fp,ensure_ascii=False,sort_keys=True))
    f1=_items(_post("FAMILY1",fp));ad=_items(_post("ADULTS",ap));f2=_items(_post("FAMILY2",fp))
    print("TANIE_PROD_ROWS",len(f1),len(ad),len(f2))
    amap={_key(x):x for x in ad if all(_key(x)[:7])}
    rmap={_key(x):x for x in f2 if all(_key(x)[:7])}
    allowed=set(configured_departure_dates(cfg))
    out=[]
    for x in f1:
        k=_key(x)
        if not all(k[:7]) or k not in amap or k not in rmap:continue
        if str(x.get("status") or "").upper() not in ("OK","AVAILABLE","DOSTEPNE","DOSTĘPNE"):continue
        service=str(x.get("serviceDesc") or x.get("serviceGroup") or "")
        if "all inclusive" not in service.lower():continue
        fp1=_price(x);aprice=_price(amap[k]);fp2=_price(rmap[k])
        if fp1 is None or aprice is None or fp2!=fp1 or not(fp1>aprice>0):continue
        dep=_date(x.get("departureDate"));ret=_date(x.get("returnDate"))
        if dep not in allowed or not ret:continue
        try:nights=int(x.get("duration"))
        except:continue
        if not cfg["min_nights"]<=nights<=cfg["max_nights"]:continue
        airport=_airport(x.get("depCode"),cfg)
        if not airport:continue
        hotel=str(x.get("hotel_name") or "").strip()
        if not hotel:continue
        direct_url=_verify_direct_offer_link(x)
        if not direct_url:
            print("TANIE_REJECT_NO_DIRECT_BOOKABLE_LINK",hotel,x.get("offerHash"))
            continue
        stable="|".join(k)
        rec={"key":hashlib.sha1(stable.encode()).hexdigest()[:16],"hotel":hotel,
             "href":direct_url,"verified_href":direct_url,"price":fp1,
             "departure":dep,"return":ret,"nights":nights,"airport":airport,
             "meal":service,"operator":"TanieTravel","stars":_stars(x),
             "rating":_rating(x),"reviews":_reviews(x),"offer_hash":x.get("offerHash"),
             "departure_time":_clock(x.get("depTime")),
             "room":x.get("roomDesc"),"adult_only_total":aprice,
             "family_price_proof":"same package offerHash/hotel/date/room/airport 2+2 vs 2+0; exact childAges=5,7; identical second 2+2 API total",
             "live_availability_proof":"same exact-family package returned by two fresh search_offers.php calls"}
        out.append(rec);print("TANIE_PROD_EXACT_LIVE",rec)
    print("TANIE_PROD_CERTIFIED",len(out))
    return out

def _quality_ok(x,cfg):
    return (x["price"]>=cfg.get("min_total_price_pln",0)
            and x["price"]<=cfg["max_total_price_pln"] and x["stars"]>=cfg["min_stars"]
            and x["rating"] is not None and x["rating"]>=cfg["min_rating"]
            and x["reviews"] is not None and x["reviews"]>=cfg["min_reviews"])

def run_tanietravel_watcher(cfg):
    rows=_certified_rows(cfg)
    qualified=[x for x in rows if _quality_ok(x,cfg)]
    print("TANIE_PROD_QUALIFIED",len(qualified))
    if rows and not qualified:print("TANIE_PROD_QUALITY_OR_PRICE_FAIL_CLOSED")
    token=os.getenv("GITHUB_TOKEN","");repo=os.getenv("GITHUB_REPOSITORY","")
    for x in qualified[:10]:
        print("TANIE_PROD_RECHECK_VERIFIED",x["hotel"],x["price"],x["offer_hash"])
        if token and repo:
            create_alert(token,repo,cfg,x,"TanieTravel exact 2+2 ages 5/7 + same-package 2+0 price proof + two fresh family API reads")
        else:print("TANIE_PROD_DRY_ALERT",x)
