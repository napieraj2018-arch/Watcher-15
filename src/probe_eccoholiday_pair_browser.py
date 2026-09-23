import json,re,time
from urllib.parse import urlsplit
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://www.eccoholiday.com"
FAMILY="/l,,,2026-09-24,,,,2,5;7,,,samolot,,,,,1,,,,,,,,,,,,,,,,,,samolotem"
ADULTS="/l,,,2026-09-24,,,,2,,,,samolot,,,,,1,,,,,,,,,,,,,,,,,,samolotem"

def compact(s): return " ".join((s or "").split())

def click_total(d):
    nodes=[]
    for e in d.find_elements(By.XPATH,"//*[self::label or self::button or self::span or self::a][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'ZA WSZYSTKICH')]"):
        try:
            if e.is_displayed(): nodes.append((len(compact(e.text)),e,compact(e.text)))
        except: pass
    nodes.sort(key=lambda z:z[0])
    for _,e,t in nodes[:20]:
        try:
            print("ECCOPAIR_TOTAL_TRY",t[:300],(e.get_attribute("outerHTML") or "")[:2200])
            d.execute_script("arguments[0].click()",e);time.sleep(5);return True
        except: pass
    return False

def best_card(d,node):
    cur=node;best=None
    for _ in range(11):
        try:
            txt=compact(cur.text)
            if 80<=len(txt)<=5000:
                totals=len(re.findall(r"[0-9][0-9 ]{2,}\s*zł\s*/\s*razem",txt,re.I))
                if totals==1 and ("zobacz ofert" in txt.lower() or "dostęp" in txt.lower()):
                    best=cur
                elif totals>1 and best is not None:
                    break
            cur=cur.find_element(By.XPATH,"..")
        except:break
    return best

def parse_cards(d,label):
    nodes=[]
    for e in d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'zł/razem')]"):
        try:
            if e.is_displayed():nodes.append(e)
        except:pass
    rows=[];seen=set()
    for n in nodes:
        card=best_card(d,n)
        if card is None:continue
        txt=compact(card.text)
        m=re.search(r"([0-9][0-9 ]{2,})\s*zł\s*/\s*razem",txt,re.I)
        if not m:continue
        price=int(re.sub(r"\D","",m.group(1)))
        hrefs=[]
        for a in card.find_elements(By.TAG_NAME,"a"):
            try:
                h=a.get_attribute("href") or ""
                if h and h not in hrefs:hrefs.append(h)
            except:pass
        # Prefer an internal offer/hotel detail link, not navigation.
        href=next((h for h in hrefs if "eccoholiday.com" in h and any(k in h.lower() for k in ["ofert","hotel","wczasy"])),hrefs[0] if hrefs else "")
        dates=re.findall(r"\b(\d{2}\.\d{2}\.\d{4})\b",txt)
        mn=re.search(r"(\d+)\s+dni\s*/\s*(\d+)\s+noc",txt,re.I)
        meal=next((x for x in ["Ultra All Inclusive","All inclusive","Pełne wyżywienie","Śniadania","Bez Wyżywienia"] if x.lower() in txt.lower()),"")
        airport=""
        for ap in ["Warszawa - Radom","Warszawa - Modlin","Warszawa"]:
            if ap.lower() in txt.lower():airport=ap;break
        hotel=""
        # First internal link text with a useful non-generic label.
        for a in card.find_elements(By.TAG_NAME,"a"):
            try:
                at=compact(a.text)
                if at and len(at)>3 and "zobacz" not in at.lower() and "dostęp" not in at.lower():
                    hotel=at;break
            except:pass
        if not hotel:
            # Common Ecco card ordering: property name precedes country/date.
            before=re.split(r"\b(?:Włochy|Egipt|Tunezja|Turcja|Grecja|Hiszpania|Cypr|Malta|Bułgaria)\b",txt,1,re.I)[0]
            hotel=compact(before)[-160:]
        key=(hotel.lower(),dates[0] if dates else "",mn.group(2) if mn else "",meal.lower(),airport.lower())
        if key in seen:continue
        seen.add(key)
        rec={"key":key,"hotel":hotel,"price":price,"dates":dates[:2],"nights":int(mn.group(2)) if mn else None,"meal":meal,"airport":airport,"href":href,"text":txt[:2600]}
        rows.append(rec)
        print("ECCOPAIR_CARD",label,json.dumps(rec,ensure_ascii=False))
    print("ECCOPAIR_CARD_COUNT",label,len(rows))
    return rows

def load(d,label,path):
    d.get(BASE+path)
    WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
    time.sleep(6)
    body=d.find_element(By.TAG_NAME,"body").text
    print("ECCOPAIR_START",label,d.current_url,len(body))
    print("ECCOPAIR_PARTY",label,"5 lat" in body,"7 lat" in body,"Dzieci" in body)
    ok=click_total(d)
    print("ECCOPAIR_TOTAL_CLICKED",label,ok)
    return parse_cards(d,label)

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,5000","--lang=pl-PL"]:o.add_argument(a)
    d=webdriver.Chrome(options=o)
    try:
        fam=load(d,"FAMILY",FAMILY)
        ad=load(d,"ADULTS",ADULTS)
        amap={tuple(x["key"]):x for x in ad}
        proofs=[]
        for f in fam:
            a=amap.get(tuple(f["key"]))
            if not a or f["price"]==a["price"]:continue
            p={"key":f["key"],"hotel":f["hotel"],"family_total":f["price"],"adults_total":a["price"],"family_href":f["href"],"adult_href":a["href"]}
            proofs.append(p);print("ECCOPAIR_PROOF",json.dumps(p,ensure_ascii=False))
        print("ECCOPAIR_COMMON",sum(1 for f in fam if tuple(f["key"]) in amap))
        print("ECCOPAIR_PARTY_SENSITIVE",len(proofs))
        print("ECCOPAIR_FAMILY_TOTAL_VERIFIED",bool(proofs))
    finally:d.quit()
if __name__=="__main__":main()
