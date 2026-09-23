import json,re,time
from urllib.parse import urlsplit,parse_qs
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait,Select

URL="https://www.katowice-travel.pl/"

def compact(s):return " ".join((s or "").split())
def click_text(d,txt):
    xs=[x for x in d.find_elements(By.XPATH,f"//*[self::button or self::div or self::span or self::label][contains(normalize-space(.),'{txt}')]") if x.is_displayed()]
    xs.sort(key=lambda x:len(compact(x.text)))
    for x in xs[:12]:
        try:d.execute_script("arguments[0].click()",x);time.sleep(.6);return True
        except:pass
    return False

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]:o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5)
        for t in ["Zaakceptuj","Akceptuj","OK"]:click_text(d,t)
        print("TANIE_START",d.current_url,d.title)
        body=d.find_element(By.TAG_NAME,"body").text
        for s in ["Turyści","2 dorosłych","Dodaj dziecko","Wiek dziecka","Kup za","All inclusive"]:
            print("TANIE_SIGNAL",s,s.lower() in body.lower())
        # open traveller picker
        opened=any(click_text(d,t) for t in ["Turyści","2 dorosłych","Uczestnicy"])
        print("TANIE_PARTY_OPENED",opened);time.sleep(1)
        # add two children
        added=0
        for _ in range(2):
            if click_text(d,"Dodaj dziecko"):added+=1
            else:
                # fallback child plus in a container mentioning children
                for b in d.find_elements(By.XPATH,"//button"):
                    try:
                        if b.is_displayed() and compact(b.text)=="+" and "dzie" in compact(b.find_element(By.XPATH,"..").text).lower():
                            d.execute_script("arguments[0].click()",b);time.sleep(.5);added+=1;break
                    except:pass
        print("TANIE_CHILDREN_ADDED",added)
        # set exact ages only on explicit age controls
        age_controls=[]
        for e in d.find_elements(By.XPATH,"//select|//input"):
            try:
                blob=" ".join(filter(None,[e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),compact(e.text)])).lower()
                if e.is_displayed() and any(k in blob for k in ["wiek dziecka","childage","child_age","age"]):age_controls.append(e)
            except:pass
        print("TANIE_AGE_CONTROL_COUNT",len(age_controls))
        setages=[]
        for idx,target in enumerate(["5","7"]):
            if idx>=len(age_controls):break
            e=age_controls[idx]
            try:
                if e.tag_name=="select":
                    opts=[(x.get_attribute("value"),compact(x.text)) for x in e.find_elements(By.TAG_NAME,"option")]
                    val=next((v for v,t in opts if str(v)==target or t==target or target in t.split()),None)
                    if val is None:continue
                    Select(e).select_by_value(val)
                else:
                    d.execute_script("arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",e,target)
                time.sleep(.4);setages.append(e.get_attribute("value"));print("TANIE_AGE_SET",idx+1,target,e.get_attribute("value"))
            except Exception as ex:print("TANIE_AGE_ERR",idx,type(ex).__name__)
        for t in ["Potwierdź","Wybierz","Gotowe","Zastosuj"]:click_text(d,t)
        # run search
        clicked=click_text(d,"Szukaj");print("TANIE_SEARCH_CLICKED",clicked);time.sleep(10)
        print("TANIE_FINAL_URL",d.current_url)
        body2=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body2.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["2 dorosłych","2 dzieci","5 lat","7 lat","kup za","zł/os","all inclusive","opinii","warszawa","radom","modlin"]):
                print("TANIE_RESULT",line[:1000])
        # inspect offer cards around explicit whole-offer prices
        cards=[]
        for e in d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Kup za')]"):
            try:
                anc=e
                for _ in range(5):anc=anc.find_element(By.XPATH,"..")
                txt=compact(anc.text)
                if "Kup za" in txt and txt not in cards:
                    cards.append(txt);print("TANIE_CARD",txt[:3500])
                if len(cards)>=12:break
            except:pass
        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if "katowice-travel.pl" in u and any(k in blob for k in ["search","offer","adult","child","age","price","tourist","person"]):
                    if (u,post) not in seen:
                        seen.add((u,post));print("TANIE_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except:pass
        print("TANIE_REQ_COUNT",len(seen))
        print("TANIE_EXACT_SUMMARY",json.dumps({"ages_set":setages,"cards":len(cards),"query":parse_qs(urlsplit(d.current_url).query)},ensure_ascii=False))
    finally:d.quit()
if __name__=="__main__":main()
