import json,re,time
from datetime import datetime,timedelta
from urllib.parse import urlsplit,parse_qsl,urlencode,urlunsplit
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
      ("CHECKIN_END",(today+timedelta(days=60)).strftime("%Y%m%d")),
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

def pick_prices_url(logs):
    out=[]
    for row in logs:
        try:
            m=json.loads(row["message"])["message"]
            if m.get("method")!="Network.requestWillBeSent":continue
            u=m["params"]["request"].get("url","")
            if "search.anextour.com.pl/search_tour?" in u and "samo_action=PRICES" in u:
                out.append(u)
        except:pass
    return out[-1] if out else None

def modify_party(url,family):
    s=urlsplit(url);pairs=parse_qsl(s.query,keep_blank_values=True)
    drop={"AGE1","AGE2"}
    out=[]
    saw_child=False;saw_ages=False
    for k,v in pairs:
        ku=k.upper()
        if ku in drop:continue
        if ku=="CHILD":
            out.append((k,"2" if family else "0"));saw_child=True;continue
        if ku=="AGES":
            out.append((k,"5,7" if family else ""));saw_ages=True;continue
        if ku=="ADULT":
            out.append((k,"2"));continue
        out.append((k,v))
    if not saw_child:out.append(("CHILD","2" if family else "0"))
    if family and not saw_ages:out.append(("AGES","5,7"))
    if not family and not saw_ages:out.append(("AGES",""))
    return urlunsplit((s.scheme,s.netloc,s.path,urlencode(out,doseq=True),s.fragment))

def fetch_in_browser(d,url,label):
    raw=d.execute_async_script("""
      const u=arguments[0],done=arguments[arguments.length-1];
      fetch(u,{credentials:'include',headers:{'X-Requested-With':'XMLHttpRequest'}})
      .then(async r=>done(JSON.stringify({status:r.status,text:await r.text(),url:r.url})))
      .catch(e=>done(JSON.stringify({status:0,text:'',error:String(e)})));
    """,url)
    obj=json.loads(raw)
    print("ANEXNET_FETCH",label,obj.get("status"),obj.get("url"),len(obj.get("text") or ""))
    return obj.get("text") or ""

def unwrap(raw):
    # SAMO can return HTML directly or JSON-wrapped HTML.
    try:obj=json.loads(raw)
    except:return raw
    def walk(x,depth=0):
        if depth>10:return None
        if isinstance(x,str):
            if "price_info" in x:return x
            try:
                z=walk(json.loads(x),depth+1)
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
    soup=BeautifulSoup(unwrap(raw),"html.parser")
    out={}
    for tr in soup.select("tr.price_info"):
        cls=" ".join(tr.get("class",[]))
        if "adult-2" not in cls:continue
        if family and "child-2" not in cls:continue
        if not family and "child-0" not in cls:continue
        try:nights=int(tr.get("data-nights") or "0")
        except:continue
        if not 5<=nights<=8:continue
        pe=tr.select_one("[data-converted-price-number]")
        if not pe:continue
        try:price=int(pe.get("data-converted-price-number"))
        except:continue
        cells=[compact(td.get_text(" ",strip=True)) for td in tr.select("td")]
        meal=next((x for x in cells if "All Inclusive" in x),"")
        av=[x.get("title") for x in tr.select(".hotel_availability") if x.get("title")]
        flights=[x.get("title") for x in tr.select(".fr_place_r,.fr_place_l") if x.get("title")]
        live=any(x in ("Dostępne","Ostatnie miejsca") for x in av) and any("Miejsca dostępne" in x for x in flights)
        room=next((x for x in cells if "2+2" in x),"") if family else ""
        if family and not room:continue
        hotel=compact(tr.select_one("td.link-hotel").get_text(" ",strip=True) if tr.select_one("td.link-hotel") else "")
        # Occupancy can change room/htplace. Compare same hotel/tour/date/night/meal/airport.
        key=(tr.get("data-checkin") or "",str(nights),tr.get("data-hotel") or "",
             tr.get("data-tour") or "",tr.get("data-meal") or "",tr.get("data-townfrom") or "")
        rec={"key":key,"hotel":hotel,"price":price,"meal":meal,"live":live,
             "availability":av,"flights":flights,"room":room,
             "roomid":tr.get("data-room"),"htplace":tr.get("data-htplace")}
        # Prefer cheapest row per comparable package key.
        if key not in out or price<out[key]["price"]:out[key]=rec
    print("ANEXNET_ROWS","FAMILY" if family else "ADULTS",len(out))
    for x in list(out.values())[:10]:
        print("ANEXNET_ROW","FAMILY" if family else "ADULTS",json.dumps(x,ensure_ascii=False))
    return out

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]:o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(family_url());WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(4);d.get_log("performance")
        print("ANEXNET_SEARCH_CLICKED",click_search(d));time.sleep(9)
        req=pick_prices_url(d.get_log("performance"))
        print("ANEXNET_CAPTURED",req or "")
        if not req:raise SystemExit("FAIL_CLOSED: SAMO PRICES request not captured")
        fu=modify_party(req,True);au=modify_party(req,False)
        print("ANEXNET_FAMILY_URL",fu)
        print("ANEXNET_ADULT_URL",au)
        fr=rows(fetch_in_browser(d,fu,"FAMILY"),True)
        ar=rows(fetch_in_browser(d,au,"ADULTS"),False)
        proofs=[]
        for k in set(fr)&set(ar):
            f,a=fr[k],ar[k]
            if not f["live"]:continue
            if not f["price"]>a["price"]>0:continue
            rec={**f,"adults_total":a["price"],"delta":f["price"]-a["price"],
                 "adult_roomid":a["roomid"],"adult_htplace":a["htplace"]}
            proofs.append(rec);print("ANEXNET_PROOF",json.dumps(rec,ensure_ascii=False))
        print("ANEXNET_EXACT_PARTY",json.dumps({"adults":2,"children":2,"ages":[5,7]}))
        print("ANEXNET_COMMON",len(set(fr)&set(ar)))
        print("ANEXNET_PARTY_SENSITIVE",len(proofs))
        print("ANEXNET_VERIFIED",bool(proofs))
        if not proofs:raise SystemExit("FAIL_CLOSED: no live same-package family total proof")
    finally:d.quit()
if __name__=="__main__":main()
