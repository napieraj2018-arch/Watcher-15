import json,re,time
from datetime import datetime,timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://search.anextour.com.pl/search_tour"
TZ=ZoneInfo("Europe/Warsaw")

def compact(s): return " ".join((s or "").split())

def make_url(family):
    today=datetime.now(TZ).date()
    q=[
      ("ADULT","2"),("CHILD","2" if family else "0"),("LANG","pol"),
      ("CHECKIN_BEG",(today+timedelta(days=1)).strftime("%Y%m%d")),
      ("CHECKIN_END",(today+timedelta(days=3)).strftime("%Y%m%d")),
      ("NIGHTS_FROM","5"),("NIGHTS_TILL","8")
    ]
    if family:q += [("AGE1","5"),("AGE2","7")]
    return BASE+"?"+urlencode(q)

def click_search(d):
    for b in d.find_elements(By.XPATH,"//button|//input[@type='submit']"):
        try:
            txt=(compact(b.text)+" "+(b.get_attribute("value") or "")).lower()
            if b.is_displayed() and "szukaj" in txt:
                d.execute_script("arguments[0].click()",b);return True
        except: pass
    return False

def row_key(tr):
    attrs=lambda n: tr.get_attribute(n) or ""
    # Production proof must keep the room identical too. Otherwise a price
    # delta could come from a different room rather than from adding children.
    return (
      attrs("data-checkin"),attrs("data-nights"),attrs("data-hotel"),
      attrs("data-tour"),attrs("data-room"),attrs("data-meal"),attrs("data-townfrom")
    )

def read_rows(d,label,family):
    d.get(make_url(family))
    WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
    time.sleep(5)
    clicked=click_search(d);time.sleep(9)
    print("ANEXCTRL_SEARCH",label,clicked,d.current_url)
    rows={}
    for tr in d.find_elements(By.CSS_SELECTOR,"tr.price_info"):
        try:
            cls=tr.get_attribute("class") or ""
            if family:
                expected=("adult-2" in cls and "child-2" in cls)
            else:
                expected=("adult-2" in cls and not re.search(r"\\bchild-[1-9]\\b",cls))
            if not expected:continue
            price_el=tr.find_elements(By.CSS_SELECTOR,"[data-converted-price-number]")
            if not price_el:continue
            raw=price_el[0].get_attribute("data-converted-price-number") or ""
            if not raw.isdigit():continue
            price=int(raw)
            hotel=compact(tr.find_element(By.CSS_SELECTOR,"td.link-hotel").text) if tr.find_elements(By.CSS_SELECTOR,"td.link-hotel") else ""
            meal=""
            cells=tr.find_elements(By.CSS_SELECTOR,"td")
            for td in cells:
                t=compact(td.text)
                if "All Inclusive" in t:meal=t;break
            avail=[x.get_attribute("title") for x in tr.find_elements(By.CSS_SELECTOR,".hotel_availability") if x.get_attribute("title")]
            room=""
            for td in cells:
                t=compact(td.text)
                if "2+2" in t or (not family and ("Room" in t or "Pok" in t)):
                    room=t;break
            rec={"key":row_key(tr),"hotel":hotel,"price":price,"meal":meal,"availability":avail,"room_text":room[:400]}
            rows[rec["key"]]=rec
        except: pass
    print("ANEXCTRL_ROWS",label,len(rows))
    if not rows:
        for tr in d.find_elements(By.CSS_SELECTOR,"tr.price_info")[:12]:
            try:
                print("ANEXCTRL_RAW_ROW_CLASS",label,(tr.get_attribute("class") or "")[:600],compact(tr.text)[:500])
            except: pass
    for x in list(rows.values())[:8]:print("ANEXCTRL_ROW",label,json.dumps(x,ensure_ascii=False))
    return rows

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]:o.add_argument(a)
    d=webdriver.Chrome(options=o)
    try:
        fam=read_rows(d,"FAMILY",True)
        adults=read_rows(d,"ADULTS",False)
        common=set(fam)&set(adults)
        proofs=[]
        for k in common:
            f,a=fam[k],adults[k]
            if f["price"]!=a["price"]:
                proofs.append({"key":k,"hotel":f["hotel"],"family_total":f["price"],"adults_total":a["price"],"delta":f["price"]-a["price"],"availability":f["availability"],"meal":f["meal"],"room":f["room_text"]})
        print("ANEXCTRL_COMMON",len(common))
        print("ANEXCTRL_PARTY_SENSITIVE",len(proofs))
        for p in sorted(proofs,key=lambda x:x["family_total"])[:15]:
            print("ANEXCTRL_PROOF",json.dumps(p,ensure_ascii=False))
        print("ANEXCTRL_FAMILY_TOTAL_VERIFIED",bool(proofs))
    finally:d.quit()

if __name__=="__main__":main()
