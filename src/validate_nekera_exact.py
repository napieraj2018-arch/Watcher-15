import json,re,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit,parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.nekera.pl/"
TZ=ZoneInfo("Europe/Warsaw")

def compact(s): return " ".join((s or "").split())

def dismiss(d):
    for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK","Rozumiem"]:
        try:
            es=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
            if es and es[0].is_displayed():
                d.execute_script("arguments[0].click()",es[0]);time.sleep(.5);return
        except: pass

def click_visible(d,xpath,label):
    for e in d.find_elements(By.XPATH,xpath):
        try:
            if e.is_displayed() and e.is_enabled():
                print("NEKERA_CLICK",label,compact(e.text),(e.get_attribute("outerHTML") or "")[:1800])
                d.execute_script("arguments[0].click()",e);time.sleep(.7);return e
        except: pass
    return None

def counter_section(d,label):
    exact=d.find_elements(By.XPATH,f"//*[normalize-space(.)='{label}']")
    for node in exact:
        try:
            if not node.is_displayed():continue
            anc=node
            for level in range(1,7):
                anc=anc.find_element(By.XPATH,"..")
                buttons=[b for b in anc.find_elements(By.TAG_NAME,"button") if b.is_displayed() and b.is_enabled()]
                inputs=[x for x in anc.find_elements(By.TAG_NAME,"input") if x.is_displayed()]
                if len(buttons)>=2 and inputs:
                    print("NEKERA_COUNTER",label,level,(anc.get_attribute("outerHTML") or "")[:4500])
                    return anc,buttons,inputs
        except: pass
    return None,None,None

def set_birth(el,iso,pl):
    for v in [iso,pl]:
        try:
            el.clear();el.send_keys(v);time.sleep(.4)
            got=el.get_attribute("value")
            print("NEKERA_DOB_TYPED",v,"=>",got)
            if got:return got
        except Exception as e:print("NEKERA_DOB_TYPE_ERR",type(e).__name__,str(e)[:140])
        try:
            el.parent
        except: pass
        try:
            # Native setter + input/change/blur works for date/text controls.
            el._parent.execute_script("""
              const e=arguments[0],v=arguments[1];
              const p=Object.getPrototypeOf(e),d=Object.getOwnPropertyDescriptor(p,'value');
              if(d&&d.set)d.set.call(e,v);else e.value=v;
              for(const n of ['input','change','blur'])e.dispatchEvent(new Event(n,{bubbles:true}));
            """,el,v)
            time.sleep(.4);got=el.get_attribute("value")
            print("NEKERA_DOB_JS",v,"=>",got)
            if got:return got
        except Exception as e:print("NEKERA_DOB_JS_ERR",type(e).__name__,str(e)[:140])
    return ""

def main():
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--window-size=1440,3400");o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5);dismiss(d)
        print("NEKERA_START",d.current_url)
        opener=click_visible(d,"//input[@id='searchbar-passengers']|//*[@id='searchbar-passengers']","people")
        print("NEKERA_PEOPLE_OPENED",bool(opener))

        # The passenger modal is anchored by the readonly searchbar input.
        # Dump its nearby DOM before manipulating anything.
        try:
            p=d.find_element(By.ID,"searchbar-passengers")
            anc=p
            for _ in range(5): anc=anc.find_element(By.XPATH,"..")
            print("NEKERA_PASSENGER_DOM",(anc.get_attribute("outerHTML") or "")[:18000])
        except Exception as e: print("NEKERA_PASSENGER_DOM_ERR",type(e).__name__,str(e)[:160])
        a,ab,ai=counter_section(d,"Dorośli")
        c,cb,ci=counter_section(d,"Dzieci")
        # Nekera's child counter is reliably anchored by #children-input even
        # when the visible label is not present in headless rendering.
        if c is None:
            try:
                child_input=d.find_element(By.ID,"children-input")
                anc=child_input
                for level in range(1,8):
                    anc=anc.find_element(By.XPATH,"..")
                    buttons=[b for b in anc.find_elements(By.TAG_NAME,"button") if b.is_displayed() and b.is_enabled()]
                    if len(buttons)>=2:
                        c=anc;cb=buttons;ci=[child_input]
                        print("NEKERA_COUNTER_BY_ID",level,(anc.get_attribute("outerHTML") or "")[:6000])
                        break
            except Exception as e:
                print("NEKERA_COUNTER_BY_ID_ERR",type(e).__name__,str(e)[:180])
        print("NEKERA_COUNTERS_FOUND",bool(a),bool(c))
        if c is not None:
            # Identify the plus control by text/aria/class, falling back to last button.
            plus=[b for b in cb if compact(b.text) in ["+","＋"] or "plus" in ((b.get_attribute("aria-label") or "")+" "+(b.get_attribute("class") or "")).lower()]
            if not plus: plus=[cb[-1]]
            for i in range(2):
                d.execute_script("arguments[0].click()",plus[-1]);time.sleep(.7)
                print("NEKERA_CHILD_PLUS",i+1)
        else:
            print("NEKERA_FAIL_NO_CHILD_COUNTER")

        # Re-read DOB controls because they may be inserted after child-count changes.
        dobs=[e for e in d.find_elements(By.XPATH,"//input[contains(@placeholder,'Data urodzenia dziecka')]") if e.is_displayed()]
        if len(dobs)<2:
            # Keep diagnostic evidence for hidden controls too; do not treat
            # them as valid until the child counter actually reached 2.
            all_dobs=d.find_elements(By.XPATH,"//input[contains(@placeholder,'Data urodzenia dziecka')]")
            print("NEKERA_ALL_DOB_COUNT",len(all_dobs))
        print("NEKERA_DOB_COUNT",len(dobs))
        for i,e in enumerate(dobs):
            print("NEKERA_DOB_FIELD",i,repr({
                "type":e.get_attribute("type"),"name":e.get_attribute("name"),"id":e.get_attribute("id"),
                "value":e.get_attribute("value"),"class":e.get_attribute("class"),
                "html":(e.get_attribute("outerHTML") or "")[:2200]
            }))
        targets=[("2021-01-01","01.01.2021"),("2019-01-01","01.01.2019")]
        for i,(iso,pl) in enumerate(targets):
            if i<len(dobs): set_birth(dobs[i],iso,pl)

        click_visible(d,"//button[normalize-space(.)='Wybierz']|//*[self::button or @role='button'][contains(normalize-space(.),'Wybierz')]","apply_people")
        time.sleep(1)
        body=compact(d.find_element(By.TAG_NAME,"body").text)
        for needle in ["2 doros","2 dzieci","01.01.2021","01.01.2019","5 lat","7 lat"]:
            print("NEKERA_BODY_PARTY",needle,needle.lower() in body.lower())

        # Print form/hidden fields after the exact party is set.
        for i,form in enumerate(d.find_elements(By.TAG_NAME,"form")):
            try:
                html=form.get_attribute("outerHTML") or ""
                if any(k in html.lower() for k in ["uczest","birth","child","adult","osob","dziec","passenger"]):
                    print("NEKERA_FORM",i,html[:35000])
            except: pass
        for e in d.find_elements(By.XPATH,"//input|//select"):
            try:
                blob=" ".join(filter(None,[e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("placeholder"),e.get_attribute("value")]))
                if any(k in blob.lower() for k in ["adult","child","birth","wiek","dziec","osob","passenger","participant"]):
                    print("NEKERA_FIELD",repr({"tag":e.tag_name,"name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),"placeholder":e.get_attribute("placeholder"),"html":(e.get_attribute("outerHTML") or "")[:2200]}))
            except: pass

        # Submit main search and capture exact backend serialization.
        submit=click_visible(d,"//button[normalize-space(.)='Szukaj']|//*[self::button or @role='button'][normalize-space(.)='Szukaj']","search")
        print("NEKERA_SUBMIT",bool(submit))
        time.sleep(8)
        print("NEKERA_FINAL_URL",d.current_url)
        print("NEKERA_FINAL_QUERY",json.dumps(parse_qs(urlsplit(d.current_url).query),ensure_ascii=False,sort_keys=True))
        # Prefer Nekera's explicit "za wszystkich" view; never derive a
        # family total by multiplying a /os. price.
        total_toggle=None
        candidates=d.find_elements(By.XPATH,"//*[self::button or self::label or @role='button'][contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'za wszystkich')]")
        candidates=[x for x in candidates if x.is_displayed()]
        candidates.sort(key=lambda x:len(compact(x.text)))
        if candidates:
            total_toggle=candidates[0]
            print("NEKERA_TOTAL_TOGGLE",(total_toggle.get_attribute("outerHTML") or "")[:3000])
            try:
                d.execute_script("arguments[0].click()",total_toggle);time.sleep(5)
            except Exception as e: print("NEKERA_TOTAL_TOGGLE_ERR",type(e).__name__,str(e)[:180])
        print("NEKERA_TOTAL_VIEW_CLICKED",bool(total_toggle))

        body2=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body2.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["doros","dzieci","2021","2019","5 lat","7 lat","zł","all inclusive"]):
                print("NEKERA_RESULT_SIGNAL",line[:1000])

        # Capture listing blocks only after exact family serialization and
        # the explicit all-participants price view have been applied.
        total_cards=[]
        for a in d.find_elements(By.XPATH,"//a[contains(normalize-space(.),'Szczegóły') or contains(@href,'/hotel') or contains(@href,'/offer')]"):
            try:
                href=a.get_attribute("href") or ""
                anc=a
                chosen=None
                for _ in range(8):
                    anc=anc.find_element(By.XPATH,"..")
                    txt=compact(anc.text)
                    if "zł" in txt and len(txt)<5000:
                        chosen=txt
                        if "za wszystkich" in txt.lower() or "/os" not in txt.lower():
                            break
                if chosen:
                    rec={"href":href,"text":chosen[:2200]}
                    if rec not in total_cards: total_cards.append(rec)
            except: pass
        print("NEKERA_TOTAL_CARD_COUNT",len(total_cards))
        for rec in total_cards[:20]: print("NEKERA_TOTAL_CARD",repr(rec))

        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if any(k in blob for k in ["adult","child","birth","passenger","participant","search","offer","occup","dziec"]):
                    key=(u,post)
                    if key not in seen:
                        seen.add(key);print("NEKERA_REQ",req.get("method"),u[:6000],"POST",post[:5000])
            except: pass
        print("NEKERA_REQ_COUNT",len(seen))
        fq=parse_qs(urlsplit(d.current_url).query)
        exact_children=fq.get("child",[])
        print("NEKERA_EXACT_SUMMARY",json.dumps({
            "adults":fq.get("adults"),
            "children_input":(d.find_element(By.ID,"children-input").get_attribute("value") if d.find_elements(By.ID,"children-input") else None),
            "child_values":exact_children,
            "exact_2plus2":fq.get("adults")==["2"] and len(exact_children)==2
        },ensure_ascii=False))
        d.save_screenshot("nekera-exact.png")
    finally:
        d.quit()

if __name__=="__main__": main()
