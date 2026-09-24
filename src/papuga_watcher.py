import os,re,time
from datetime import datetime
from urllib.parse import urlsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from watcher import (
    chrome,dismiss_cookies,configured_departure_dates,create_alert
)

BASE="https://wczasy.wakacyjnapapuga.pl"

def compact(s): return " ".join((s or "").split())

def search_url(cfg):
    dates=configured_departure_dates(cfg)
    start=min(dates).isoformat()
    ages=";".join(str(x) for x in cfg["children_ages"])
    # KSI canonical search serialization confirmed by the exact-family proof.
    return f"{BASE}/l?,,,{start},,,,,{cfg['adults']},{ages},,,,,,,,5;8"

def load(driver,url):
    driver.get(url)
    WebDriverWait(driver,45).until(lambda d:d.execute_script("return document.readyState")=="complete")
    time.sleep(4)
    dismiss_cookies(driver)

def click_filter(driver,text):
    low=text.lower()
    for el in driver.find_elements(By.XPATH,"//*[self::label or self::button or self::span or self::div]"):
        try:
            if not el.is_displayed():continue
            if compact(el.text).lower()==low:
                driver.execute_script("arguments[0].click()",el);time.sleep(.5);return True
        except:pass
    return False

def candidate_links(driver,cfg):
    target={d.strftime("%d.%m.%Y") for d in configured_departure_dates(cfg)}
    target_short={d.strftime("%d.%m") for d in configured_departure_dates(cfg)}
    out={}
    # Narrow visible surface where possible; all correctness is rechecked on detail.
    click_filter(driver,"Last Minute")
    click_filter(driver,"All inclusive")
    time.sleep(2)

    for _ in range(8):
        for a in driver.find_elements(By.TAG_NAME,"a"):
            try:
                href=a.get_attribute("href") or ""
                if "/ofr-" not in href:continue
                anc=a;txt=""
                for _ in range(6):
                    t=compact(anc.text)
                    if len(t)<4000 and ("all inclusive" in t.lower() or any(x in t for x in target_short)):
                        txt=t
                    anc=anc.find_element(By.XPATH,"..")
                if not txt:continue
                if "all inclusive" not in txt.lower():continue
                if not any(x in txt for x in target_short):continue
                if not any(x.lower() in txt.lower() for x in cfg["airports"]):continue
                out[urlsplit(href).path]=href
            except:pass
        # Try next page.
        moved=False
        for el in driver.find_elements(By.XPATH,"//*[self::a or self::button]"):
            try:
                if not el.is_displayed():continue
                txt=compact(el.text)
                aria=(el.get_attribute("aria-label") or "").lower()
                if txt in [">","›","»"] or "next" in aria or "następ" in aria:
                    before=driver.current_url
                    driver.execute_script("arguments[0].click()",el);time.sleep(3)
                    moved=(driver.current_url!=before) or True
                    break
            except:pass
        if not moved:break
    print("PAP_PROD_LINKS",len(out))
    return list(out.values())

def parse_date_range(body):
    # Detail pages use "03.12 - 09.12.2026 / ...".
    m=re.search(r"\b(\d{2})\.(\d{2})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})\b",body)
    if not m:return None,None
    year=int(m.group(5))
    dep=datetime(year,int(m.group(2)),int(m.group(1))).date()
    ret=datetime(year,int(m.group(4)),int(m.group(3))).date()
    return dep,ret

def parse_detail(driver,href,cfg):
    load(driver,href)
    body=driver.find_element(By.TAG_NAME,"body").text
    low=body.lower()
    if "dorośli: 2 dzieci: 2" not in compact(body).lower():
        return None,"party_not_2plus2"
    if ",2,5;7," not in driver.current_url and "%2C2%2C5%3B7%2C" not in driver.current_url:
        return None,"ages_not_serialized"
    if "all inclusive" not in low:
        return None,"meal_not_ai"
    if "rezerwuj" not in low:
        return None,"not_bookable"
    dep,ret=parse_date_range(body)
    if not dep or dep not in set(configured_departure_dates(cfg)):
        return None,"departure_outside_window"
    nights=(ret-dep).days
    if not (cfg["min_nights"]<=nights<=cfg["max_nights"]):
        return None,"nights_outside_window"
    airport=""
    for x in cfg["airports"]:
        if x.lower() in low:
            airport=x;break
    if not airport:return None,"airport_not_allowed"
    pm=re.search(r"Razem\s*:\s*([0-9][0-9 ]{2,})\s*zł",body,re.I)
    if not pm:return None,"no_total"
    price=int(pm.group(1).replace(" ",""))
    if price>cfg["max_total_price_pln"]:
        return None,"over_max"

    hotel=""
    try:
        h=driver.find_element(By.TAG_NAME,"h1")
        hotel=compact(h.text)
    except:pass
    if not hotel:hotel=urlsplit(driver.current_url).path.split("/")[-1]

    stars=None
    # KSI details often expose "Kategoria 4" or operator category text.
    for pat in [r"Kategoria\s+(?:lokalna\s+)?([1-5])\b",r"kat\.\s*(?:lokalna\s*)?([1-5])\*"]:
        m=re.search(pat,body,re.I)
        if m:stars=int(m.group(1));break

    rating=None;reviews=None
    mr=re.search(r"\b(\d{1,2}[.,]\d)\s*/\s*10\b",body)
    if mr:rating=float(mr.group(1).replace(",","."))
    mn=re.search(r"([0-9][0-9 ]*)\s+opini",body,re.I)
    if mn:reviews=int(mn.group(1).replace(" ",""))

    operator=""
    mo=re.search(r"Organizator\s*-\s*([^\n]+)",body,re.I)
    if mo:operator=compact(mo.group(1))[:100]

    offer={
        "hotel":hotel,"price":price,"departure":dep,"return":ret,"nights":nights,
        "airport":airport,"meal":"All Inclusive","operator":operator or "Wakacyjna Papuga",
        "rating":rating,"reviews":reviews,"stars":stars,
        "href":driver.current_url,"verified_href":driver.current_url,
    }
    return offer,"papuga_detail_family_total"

def recheck(driver,offer,cfg):
    first=offer["price"]
    href=offer["verified_href"]
    again,reason=parse_detail(driver,href,cfg)
    if not again:return None,"recheck_"+reason
    if again["price"]!=first:return None,"price_changed_on_recheck"
    return again,"papuga_double_live_recheck"

def run_papuga_watcher(cfg):
    driver=chrome()
    token=os.getenv("GITHUB_TOKEN","")
    repo=os.getenv("GITHUB_REPOSITORY","")
    alerts=0
    try:
        url=search_url(cfg)
        print("PAP_PROD_SEARCH",url)
        load(driver,url)
        body=driver.find_element(By.TAG_NAME,"body").text
        if ",2,5;7," not in driver.current_url and "2,5;7" not in driver.current_url:
            print("PAP_FAIL search_lost_family");return
        links=candidate_links(driver,cfg)
        checked=0
        for href in links[:35]:
            offer,reason=parse_detail(driver,href,cfg)
            checked+=1
            if not offer:
                print("PAP_REJECT",reason,href);continue
            offer2,verification=recheck(driver,offer,cfg)
            if not offer2:
                print("PAP_REJECT",verification,href);continue
            print("PAP_VERIFIED",offer2["hotel"],offer2["price"],offer2["departure"],offer2["airport"],offer2["rating"],offer2["reviews"],offer2["stars"])
            if token and repo and create_alert(token,repo,cfg,offer2,verification):
                alerts+=1
        print("PAP_CHECKED",checked)
        print("PAP_ALERTS_CREATED",alerts)
    finally:
        driver.quit()
