import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit, parse_qsl, urlunsplit, parse_qs
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://www.exim.pl/wyszukanie"
TZ=ZoneInfo("Europe/Warsaw")

def compact(s):
    return " ".join((s or "").split())

def party_params(url):
    q={k.upper():v[-1] for k,v in parse_qs(urlsplit(url).query,keep_blank_values=True).items()}
    return {k:q.get(k) for k in ["AC1","KC1","KA1","IC1"]}

def exact_party_in_url(url):
    p=party_params(url)
    return p.get("AC1")=="2" and p.get("KC1")=="2" and p.get("KA1") in ("5|7","5%7C7")

def dump_search_api(d,label):
    urls=[]
    for row in d.get_log("performance"):
        try:
            m=json.loads(row["message"])["message"]
            if m.get("method")!="Network.responseReceived":
                continue
            u=m["params"]["response"].get("url","")
            if "/api/searchapi/" in u or "/api/searchfilter/" in u:
                if u not in urls:
                    urls.append(u)
                    print(label,u)
        except Exception:
            pass
    return urls

def load(d,url,label):
    d.get(url)
    WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
    time.sleep(8)
    print(label+"_URL",d.current_url)
    print(label+"_PARTY_PARAMS",party_params(d.current_url),"EXACT",exact_party_in_url(d.current_url))
    apis=dump_search_api(d,label+"_API")
    print(label+"_API_COUNT",len(apis))
    body=d.find_element(By.TAG_NAME,"body").text
    for line in [x.strip() for x in body.splitlines() if x.strip()]:
        lo=line.lower()
        if any(k in lo for k in ["2 doros","2 dzieci","5 lat","7 lat"]):
            print(label+"_PARTY_LINE",line[:700])
    return body

def collect_cards(d,label):
    cards=[]
    seen=set()
    for a in d.find_elements(By.TAG_NAME,"a"):
        try:
            href=a.get_attribute("href") or ""
            if not href or "exim.pl/kierunki/" not in href:
                continue
            anc=None
            for xp in [
                "./ancestor::article[1]",
                "./ancestor::div[contains(.,'Dorosły od')][1]",
                "./ancestor::div[contains(.,'zł')][1]",
            ]:
                try:
                    cand=a.find_element(By.XPATH,xp)
                    t=compact(cand.text)
                    if len(t)>50:
                        anc=cand
                        break
                except Exception:
                    pass
            if anc is None:
                continue
            t=compact(anc.text)
            if href in seen:
                continue
            seen.add(href)
            cards.append((href,t))
        except Exception:
            pass
    print(label+"_CANDIDATE_COUNT",len(cards))
    for href,t in cards[:20]:
        print(label+"_CARD",repr({"text":t[:1700],"href":href[:2200]}))
    return cards

def detail_url(href):
    p=urlsplit(href)
    params=dict(parse_qsl(p.query,keep_blank_values=True))
    params["AC1"]="2"
    params["KC1"]="2"
    params["KA1"]="5|7"
    params["IC1"]="0"
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(params),""))

def inspect_detail(d,href,label):
    exact=detail_url(href)
    print(label+"_DETAIL_EXACT",exact)
    body=load(d,exact,label+"_DETAIL")
    print(label+"_DETAIL_FINAL",d.current_url)
    lines=[x.strip() for x in body.splitlines() if x.strip()]
    for line in lines:
        lo=line.lower()
        if any(k in lo for k in ["doros","dzieci","wiek","cena łącznie","cena razem","cena całkowita","razem","zł","all inclusive"]):
            print(label+"_DETAIL_LINE",line[:900])
    totals=[]
    for pat in [
        r"Cena\s*(?:łącznie|razem|całkowita)\s*[: ]\s*([0-9][0-9 .]*)\s*zł",
        r"(?:Łącznie|Razem)\s*[: ]\s*([0-9][0-9 .]*)\s*zł",
    ]:
        for m in re.findall(pat,body,re.I):
            n=re.sub(r"\D","",m)
            if n:
                totals.append(int(n))
    print(label+"_EXPLICIT_TOTALS",totals[:40])
    verified=bool(totals) and exact_party_in_url(d.current_url)
    print(label+"_EXACT_FAMILY_TOTAL_VERIFIED",verified)
    return verified,totals

def main():
    today=datetime.now(TZ).date()
    start=today+timedelta(days=1)
    end=today+timedelta(days=3)
    strict=[
        ("ac1","2"),("kc1","2"),("ka1","5|7"),
        ("dd",start.isoformat()),("rd",end.isoformat()),
        ("nn","5|6|7|8"),("tt","1"),("to","3850|4380|4381"),
    ]

    o=Options()
    o.add_argument("--headless=new");o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3000");o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        strict_url=BASE+"?"+urlencode(strict)
        load(d,strict_url,"STRICT")
        strict_cards=collect_cards(d,"STRICT")
        if strict_cards:
            inspect_detail(d,strict_cards[0][0],"STRICT")
            return

        # Validation-only fallback: keep exact 2+2 ages 5/7 but broaden dates
        # and use high-inventory Egypt destination IDs. This can prove schema
        # and family-total extraction, but never qualifies an alert by itself.
        fallback=[
            ("ac1","2"),("kc1","2"),("ka1","5|7"),
            ("dd",start.isoformat()),("rd",(today+timedelta(days=180)).isoformat()),
            ("nn","7|10"),("tt","1"),("d","64419|64420|64425"),
        ]
        fallback_url=BASE+"?"+urlencode(fallback)
        print("EXIM_VALIDATION_FALLBACK",fallback_url)
        load(d,fallback_url,"FALLBACK")
        cards=collect_cards(d,"FALLBACK")
        verified=False
        for href,_ in cards[:6]:
            ok,_=inspect_detail(d,href,"FALLBACK")
            if ok:
                verified=True
                break
        print("EXIM_VALIDATION_FALLBACK_TOTAL_VERIFIED",verified)
    finally:
        d.quit()

if __name__=="__main__":
    main()
