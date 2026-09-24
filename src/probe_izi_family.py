import json,re,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select,WebDriverWait

BASE="https://iziwakacje.pl/lastminute/"

def compact(s): return " ".join((s or "").split())

def chrome():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,4200","--lang=pl-PL"]:
        o.add_argument(a)
    return webdriver.Chrome(options=o)

def cookies(d):
    for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
        try:
            xs=[x for x in d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]") if x.is_displayed()]
            if xs:
                d.execute_script("arguments[0].click()",xs[0]);time.sleep(.4);return
        except: pass

def set_party(d,family):
    # KSI-based search widgets used by this surface.
    child_input=None
    for sel in ["#searchWindow_main_children","input[id*='children']"]:
        try:
            xs=[x for x in d.find_elements(By.CSS_SELECTOR,sel) if x.is_displayed()]
            if xs: child_input=xs[0];break
        except: pass
    print("IZI_CHILD_INPUT",bool(child_input), child_input.get_attribute("id") if child_input else None)
    if child_input:
        d.execute_script("arguments[0].click()",child_input);time.sleep(.5)
    selects=[x for x in d.find_elements(By.CSS_SELECTOR,"select[id*='chd_'],select[class*='children_select']") if x.is_displayed()]
    print("IZI_CHILD_SELECTS",[(x.get_attribute("id"),x.get_attribute("value")) for x in selects])
    ages=[5,7] if family else []
    for i,s in enumerate(selects):
        try:
            Select(s).select_by_value(str(ages[i]) if i<len(ages) else "")
            d.execute_script("arguments[0].dispatchEvent(new Event('change',{bubbles:true}))",s)
        except Exception as e:
            print("IZI_AGE_SET_ERR",i,type(e).__name__,str(e)[:120])
    time.sleep(.5)
    print("IZI_AGE_VALUES",[x.get_attribute("value") for x in selects])
    return len([x for x in selects if x.get_attribute("value")])==len(ages)

def click_search(d):
    for el in d.find_elements(By.XPATH,"//button|//input[@type='submit']"):
        try:
            txt=(compact(el.text)+" "+(el.get_attribute("value") or "")).lower()
            if el.is_displayed() and "szukaj" in txt:
                d.execute_script("arguments[0].click()",el);return True
        except: pass
    return False

def total_mode(d):
    for xp in ["//label[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'za wszystkich')]",
               "//*[self::button or self::label][contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'za wszystkich')]"]:
        for el in d.find_elements(By.XPATH,xp):
            try:
                if el.is_displayed():
                    d.execute_script("arguments[0].click()",el);time.sleep(2);return True
            except: pass
    return False

def card_from(a):
    try:
        href=a.get_attribute("href") or ""
        if not href:return None
        anc=a
        best=None
        for _ in range(8):
            txt=compact(anc.text)
            if ("cena za wszystkich" in txt.lower() or "zł" in txt.lower()) and len(txt)<5000:
                best=(anc,txt)
            anc=anc.find_element(By.XPATH,"..")
        if not best:return None
        anc,txt=best
        pm=re.search(r"(?:cena za wszystkich[^0-9]{0,40}|od\s+)([0-9][0-9 ]{2,})\s*zł",txt,re.I)
        if not pm:
            # total mode often renders "... 7 898 zł ... za wszystkich"
            ms=re.findall(r"([0-9][0-9 ]{2,})\s*zł",txt,re.I)
            if not ms:return None
            price=int(ms[-1].replace(" ",""))
        else: price=int(pm.group(1).replace(" ",""))
        dm=re.search(r"(\d{2}\.\d{2})\s*-\s*(\d{2}\.\d{2}\.\d{4})",txt)
        if not dm:return None
        nm=re.search(r"(\d+)\s+dni\s*\((\d+)\s+noc",txt,re.I)
        airport=""
        am=re.search(r"(Warszawa(?:\s*-\s*(?:Radom|Modlin|Okęcie))?|Katowice|Kraków|Poznań|Wrocław|Gdańsk)\s*/\s*(\d{1,2}:\d{2})",txt,re.I)
        if am:airport=am.group(1)
        meal="All Inclusive" if "all inclusive" in txt.lower() else ""
        # title from nearest h2/h3 or link text
        hotel=""
        for h in anc.find_elements(By.CSS_SELECTOR,"h1,h2,h3,h4"):
            t=compact(h.text)
            if t and len(t)<120: hotel=t;break
        if not hotel:
            hotel=compact(a.text).replace("Sprawdź cenę","").strip()[:100]
        key=(hotel.lower(),dm.group(1),dm.group(2),nm.group(2) if nm else "",meal.lower(),airport.lower())
        return {"key":key,"hotel":hotel,"price":price,"href":href,"text":txt[:1800]}
    except Exception:return None

def collect(d,label):
    total_mode(d)
    time.sleep(2)
    body=d.find_element(By.TAG_NAME,"body").text
    print("IZI_PARTY",label,"children5",("5 lat" in body),"children7",("7 lat" in body),"url",d.current_url)
    out={}
    for a in d.find_elements(By.TAG_NAME,"a"):
        try:
            txt=compact(a.text).lower()
            if "sprawdź cenę" not in txt and "kup online" not in txt:continue
            x=card_from(a)
            if x and x["key"] not in out:out[x["key"]]=x
        except:pass
    print("IZI_CARD_COUNT",label,len(out))
    for x in list(out.values())[:15]:print("IZI_CARD",label,json.dumps(x,ensure_ascii=False,default=str))
    return out

def run(family,label):
    d=chrome()
    try:
        d.get(BASE);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(4);cookies(d)
        set_party(d,family)
        print("IZI_SEARCH_CLICK",label,click_search(d))
        time.sleep(8)
        return collect(d,label)
    finally:d.quit()

def main():
    fam=run(True,"FAMILY")
    ad=run(False,"ADULTS")
    proofs=[]
    for k,f in fam.items():
        a=ad.get(k)
        if not a or f["price"]==a["price"]:continue
        p={"key":k,"hotel":f["hotel"],"family_total":f["price"],"adult_total":a["price"],"delta":f["price"]-a["price"],"href":f["href"]}
        proofs.append(p);print("IZI_PROOF",json.dumps(p,ensure_ascii=False,default=str))
    print("IZI_PARTY_SENSITIVE",len(proofs))
    print("IZI_FAMILY_TOTAL_VERIFIED",bool(proofs))

if __name__=="__main__":main()
