import json,re,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://krok-travel.pl/offerts/"

def compact(s): return " ".join((s or "").split())
def chrome():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,4500","--lang=pl-PL"]:
        o.add_argument(a)
    return webdriver.Chrome(options=o)

def cookies(d):
    for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
        try:
            xs=[x for x in d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]") if x.is_displayed()]
            if xs:d.execute_script("arguments[0].click()",xs[0]);time.sleep(.4);return
        except:pass

def click_party(d):
    # click the visible participant field near "Ile osób?"
    for el in d.find_elements(By.XPATH,"//*[self::button or self::input or @role='button']"):
        try:
            blob=(compact(el.text)+" "+(el.get_attribute("value") or "")+" "+(el.get_attribute("placeholder") or "")).lower()
            if el.is_displayed() and ("2 osoby" in blob or "ile osób" in blob):
                d.execute_script("arguments[0].click()",el);time.sleep(.8);return True
        except:pass
    return False

def set_family(d,family):
    print("KROK_PARTY_OPEN",click_party(d))
    if family:
        # Find row containing Dzieci and click plus twice.
        row=None
        for el in d.find_elements(By.XPATH,"//*[normalize-space(.)='Dzieci']"):
            try:
                anc=el
                for _ in range(5):
                    btns=[b for b in anc.find_elements(By.TAG_NAME,"button") if b.is_displayed()]
                    if len(btns)>=2:row=anc;break
                    anc=anc.find_element(By.XPATH,"..")
                if row:break
            except:pass
        if not row:
            print("KROK_CHILD_ROW_MISSING");return False
        btns=[b for b in row.find_elements(By.TAG_NAME,"button") if b.is_displayed() and b.is_enabled()]
        plus=btns[-1]
        for _ in range(2):
            d.execute_script("arguments[0].click()",plus);time.sleep(.5)

        # Exact child birth dates.
        date_inputs=[]
        for e in d.find_elements(By.TAG_NAME,"input"):
            try:
                if not e.is_displayed():continue
                typ=e.get_attribute("type") or ""
                ph=e.get_attribute("placeholder") or ""
                blob=" ".join(filter(None,[e.get_attribute("name"),e.get_attribute("id"),ph,e.get_attribute("aria-label")])).lower()
                parent=compact(e.find_element(By.XPATH,"..").text).lower()
                if typ=="date" or "urodzenia" in blob or "urodzenia" in parent:
                    date_inputs.append(e)
            except:pass
        print("KROK_DATE_INPUTS",[(x.get_attribute("type"),x.get_attribute("name"),x.get_attribute("id"),x.get_attribute("placeholder")) for x in date_inputs])
        vals=["2021-08-24","2019-08-24"]
        for i,v in enumerate(vals):
            if i>=len(date_inputs):break
            e=date_inputs[i]
            d.execute_script("arguments[0].removeAttribute('readonly')",e)
            try:
                e.click();e.send_keys(Keys.CONTROL,"a");e.send_keys(v);e.send_keys(Keys.TAB)
            except:pass
            if e.get_attribute("value")!=v:
                d.execute_script("arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",e,v)
            print("KROK_DOB_SET",i+1,v,e.get_attribute("value"))
    # close participant popup
    for b in d.find_elements(By.XPATH,"//button[contains(normalize-space(.),'Wybierz')]"):
        try:
            if b.is_displayed():d.execute_script("arguments[0].click()",b);time.sleep(.6);break
        except:pass
    body=d.find_element(By.TAG_NAME,"body").text
    print("KROK_PARTY_VISIBLE",family, "4 osoby" in body, "2 osoby" in body)
    return True

def set_search_filters(d):
    # Transport: Samolot
    try:
        for el in d.find_elements(By.XPATH,"//*[self::button or self::input or @role='button']"):
            blob=(compact(el.text)+" "+(el.get_attribute("value") or "")).lower()
            if el.is_displayed() and ("typ transportu" in blob or blob.strip()==""):
                pass
        # click label/input Samolot if visible
        xs=d.find_elements(By.XPATH,"//*[normalize-space(.)='Samolot']")
        for x in xs:
            if x.is_displayed():
                try:d.execute_script("arguments[0].click()",x);time.sleep(.3)
                except:pass
    except:pass
    for b in d.find_elements(By.XPATH,"//button[contains(normalize-space(.),'Szukaj')]"):
        try:
            if b.is_displayed():d.execute_script("arguments[0].click()",b);time.sleep(8);return True
        except:pass
    return False

def apply_filters(d):
    # All inclusive
    for el in d.find_elements(By.XPATH,"//*[normalize-space(.)='All inclusive']"):
        try:
            if el.is_displayed():
                d.execute_script("arguments[0].click()",el);time.sleep(.3);break
        except:pass
    # price za wszystkich
    for el in d.find_elements(By.XPATH,"//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'za wszystkich')]"):
        try:
            if el.is_displayed():
                d.execute_script("arguments[0].click()",el);time.sleep(2);break
        except:pass

def parse_cards(d,label):
    apply_filters(d)
    body=d.find_element(By.TAG_NAME,"body").text
    print("KROK_BODY_PARTY",label,"4 osoby",("4 osoby" in body),"child1",("Data urodzenia dziecka 1" in body))
    out={}
    # find nodes containing explicit total price
    for node in d.find_elements(By.XPATH,"//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'za wszystkich')]"):
        try:
            anc=node
            best=None
            for _ in range(7):
                txt=compact(anc.text)
                if "zł za wszystkich" in txt.lower() and len(txt)<5000:best=(anc,txt)
                anc=anc.find_element(By.XPATH,"..")
            if not best:continue
            anc,txt=best
            pm=re.search(r"([0-9][0-9 ]{2,})\s*zł\s+za wszystkich",txt,re.I)
            if not pm:continue
            total=int(pm.group(1).replace(" ",""))
            dm=re.search(r"(?:Tam:\s*)?(\d{2}\.\d{2}\.\d{2,4}).*?(?:Powrót:\s*)?(\d{2}\.\d{2}\.\d{2,4})",txt,re.I)
            nm=re.search(r"(\d+)\s+noc",txt,re.I)
            meal="All Inclusive" if "all inclusive" in txt.lower() else ""
            airport=""
            for a in ["Warszawa Chopin","Warszawa Modlin","Warszawa","Radom","Katowice","Kraków","Poznań","Wrocław","Gdańsk"]:
                if a.lower() in txt.lower():airport=a;break
            hotel=""
            for h in anc.find_elements(By.CSS_SELECTOR,"h1,h2,h3,h4,a"):
                t=compact(h.text)
                if t and len(t)<120 and not any(k in t.lower() for k in ["rezerw","wybierz","cena"]):
                    hotel=t;break
            key=(hotel.lower(),dm.group(1) if dm else "",dm.group(2) if dm else "",nm.group(1) if nm else "",meal.lower(),airport.lower())
            if key not in out:
                out[key]={"key":key,"hotel":hotel,"price":total,"text":txt[:1800]}
        except:pass
    print("KROK_CARD_COUNT",label,len(out))
    for x in list(out.values())[:15]:print("KROK_CARD",label,json.dumps(x,ensure_ascii=False,default=str))
    return out

def run(family,label):
    d=chrome()
    try:
        d.get(BASE);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5);cookies(d)
        set_family(d,family)
        print("KROK_SEARCH",label,set_search_filters(d))
        return parse_cards(d,label)
    finally:d.quit()

def main():
    fam=run(True,"FAMILY");ad=run(False,"ADULTS")
    proofs=[]
    for k,f in fam.items():
        a=ad.get(k)
        if not a or f["price"]==a["price"]:continue
        p={"key":k,"hotel":f["hotel"],"family_total":f["price"],"adult_total":a["price"],"delta":f["price"]-a["price"]}
        proofs.append(p);print("KROK_PROOF",json.dumps(p,ensure_ascii=False,default=str))
    print("KROK_PARTY_SENSITIVE",len(proofs))
    print("KROK_FAMILY_TOTAL_VERIFIED",bool(proofs))

if __name__=="__main__":main()
