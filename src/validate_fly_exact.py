import json,re,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit,parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

URL="https://fly.pl/szukaj-wycieczek/"
TZ=ZoneInfo("Europe/Warsaw")

def compact(s): return " ".join((s or "").split())

def dismiss(d):
    for t in ["Allow all","Zezwól na wszystkie","Zaakceptuj wszystko","Akceptuję","Akceptuj","OK"]:
        try:
            es=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
            if es and es[0].is_displayed():
                d.execute_script("arguments[0].click()",es[0]);time.sleep(.7);return
        except: pass

def dump_people(d,label):
    print(label)
    for el in d.find_elements(By.XPATH,"//input|//select|//button|//*[@data-module='dropdown']"):
        try:
            txt=compact(el.text)
            attrs=" ".join(filter(None,[
                txt,el.get_attribute("name"),el.get_attribute("id"),
                el.get_attribute("placeholder"),el.get_attribute("aria-label"),
                el.get_attribute("class"),el.get_attribute("data-itext"),
                el.get_attribute("data-name"),el.get_attribute("value")
            ]))
            lo=attrs.lower()
            if any(k in lo for k in ["doros","dziec","dzieci","child","adult","person","osob","osób","wiek","age","people","kto"]):
                print("FLY_PEOPLE",repr({
                    "tag":el.tag_name,"displayed":el.is_displayed(),"text":txt[:300],
                    "name":el.get_attribute("name"),"id":el.get_attribute("id"),
                    "value":el.get_attribute("value"),"placeholder":el.get_attribute("placeholder"),
                    "class":el.get_attribute("class"),"data_name":el.get_attribute("data-name"),
                    "html":(el.get_attribute("outerHTML") or "")[:2400]
                }))
        except: pass

def open_people(d):
    candidates=d.find_elements(By.CSS_SELECTOR,"[data-module='dropdown'][data-drop='person']")
    print("FLY_PEOPLE_OPEN_CANDIDATES",len(candidates))
    for el in candidates:
        try:
            target=el.find_element(By.CSS_SELECTOR,".main_advance_filters_container")
        except:
            target=el
        try:
            print("FLY_OPEN_TRY",(el.get_attribute("outerHTML") or "")[:2600])
            d.execute_script("arguments[0].click()",target);time.sleep(1)
            menu=el.find_elements(By.CSS_SELECTOR,".menu")
            print("FLY_MENU_CLASS",menu[0].get_attribute("class") if menu else None)
            return True
        except Exception as e: print("FLY_OPEN_ERR",type(e).__name__,str(e)[:180])
    return False

def set_numeric(d,needle,target):
    els=d.find_elements(By.XPATH,f"//input[contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'{needle}')]")
    els += d.find_elements(By.XPATH,f"//input[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZĄĆĘŁŃÓŚŹŻ','abcdefghijklmnopqrstuvwxyząćęłńóśźż'),'{needle}')]")
    seen=[]
    for el in els:
        if el in seen: continue
        seen.append(el)
        try:
            print("FLY_NUMERIC_TARGET",needle,repr({"name":el.get_attribute("name"),"value":el.get_attribute("value"),"html":el.get_attribute("outerHTML")[:1400]}))
            d.execute_script("""
              const e=arguments[0],v=String(arguments[1]);
              const proto=Object.getPrototypeOf(e);
              const desc=Object.getOwnPropertyDescriptor(proto,'value');
              if(desc&&desc.set) desc.set.call(e,v); else e.value=v;
              e.dispatchEvent(new Event('input',{bubbles:true}));
              e.dispatchEvent(new Event('change',{bubbles:true}));
              e.dispatchEvent(new Event('blur',{bubbles:true}));
            """,el,target)
            time.sleep(.7)
            print("FLY_NUMERIC_AFTER",needle,el.get_attribute("value"))
            return True
        except Exception as e: print("FLY_NUMERIC_ERR",needle,type(e).__name__,str(e)[:180])
    return False

def main():
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--window-size=1440,3400");o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    summary={"child_count":None,"childlist":"","age_fields":[],"applied":False,"final_query":{},"body_party":""}
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5);dismiss(d)
        print("FLY_START",d.current_url)
        dump_people(d,"FLY_PEOPLE_BEFORE")
        print("FLY_OPENED",open_people(d));dump_people(d,"FLY_PEOPLE_AFTER_OPEN")

        # Adults default to 2. Change children through the real counter UI so
        # Fly's frontend creates the DOB controls and serializes the party.
        adult_hidden=d.find_elements(By.CSS_SELECTOR,"input[name='filter[person]']")
        a=bool(adult_hidden and adult_hidden[0].get_attribute("value")=="2")
        print("FLY_ADULTS_EXACT",a,adult_hidden[0].get_attribute("value") if adult_hidden else None)
        child_box=d.find_elements(By.CSS_SELECTOR,"[data-counter='child']")
        c=False
        if child_box:
            plus=child_box[0].find_elements(By.CSS_SELECTOR,"button.plus")
            if plus:
                for i in range(2):
                    d.execute_script("arguments[0].click()",plus[0]);time.sleep(.8)
                    hidden=d.find_elements(By.CSS_SELECTOR,"input[name='filter[child]']")
                    val=hidden[0].get_attribute("value") if hidden else None
                    summary["child_count"]=val
                    print("FLY_CHILD_PLUS",i+1,val)
                c=True
        print("FLY_COUNTS_SET",a,c)
        time.sleep(1);dump_people(d,"FLY_AFTER_COUNTS")
        childlists=d.find_elements(By.CSS_SELECTOR,"[data-childlist]")
        if childlists:
            summary["childlist"]=(childlists[0].get_attribute("outerHTML") or "")
            print("FLY_CHILDLIST_HTML",summary["childlist"][:9000])

        age_controls=[]
        roots=d.find_elements(By.CSS_SELECTOR,"[data-childlist]")
        scan=(roots[0].find_elements(By.XPATH,".//select|.//input") if roots else [])
        for el in scan:
            try:
                rec={"tag":el.tag_name,"type":el.get_attribute("type"),"name":el.get_attribute("name"),"id":el.get_attribute("id"),"value":el.get_attribute("value"),"placeholder":el.get_attribute("placeholder"),"class":el.get_attribute("class"),"html":(el.get_attribute("outerHTML") or "")[:2400]}
                print("FLY_CHILD_FIELD",repr(rec))
                age_controls.append(el)
            except: pass
        print("FLY_CHILD_FIELD_COUNT",len(age_controls))
        # Do not invent child-age serialization. We first expose every generated
        # field; setting happens only when its type/name/options make the schema explicit.
        for idx,el in enumerate(age_controls):
            if el.tag_name=="select":
                try:
                    opts=[(o.get_attribute("value"),compact(o.text)) for o in el.find_elements(By.TAG_NAME,"option")]
                    print("FLY_CHILD_OPTIONS",idx,opts[:80])
                except: pass

        # The generated child controls expose canonical hidden fields:
        # filter[childAge][1] and filter[childAge][2]. Fly uses DD-MM-YYYY
        # throughout the same search form (e.g. whenFrom/whenTo), so write
        # exact DOBs there and mirror them into the visible readonly date inputs.
        dep=(datetime.now(TZ).date()+timedelta(days=1))
        dobs=[datetime(dep.year-5,1,1).strftime("%d-%m-%Y"),datetime(dep.year-7,1,1).strftime("%d-%m-%Y")]
        for idx,dob in enumerate(dobs,1):
            hs=d.find_elements(By.CSS_SELECTOR,f"input[name='filter[childAge][{idx}]']")
            vs=d.find_elements(By.CSS_SELECTOR,f"input[data-birthdate='{idx}']")
            if hs:
                d.execute_script("""
                  const e=arguments[0],v=arguments[1];
                  e.value=v;
                  e.dispatchEvent(new Event('input',{bubbles:true}));
                  e.dispatchEvent(new Event('change',{bubbles:true}));
                """,hs[0],dob)
            if vs:
                d.execute_script("""
                  const e=arguments[0],v=arguments[1];
                  e.removeAttribute('readonly');
                  e.value=v;
                  e.dispatchEvent(new Event('input',{bubbles:true}));
                  e.dispatchEvent(new Event('change',{bubbles:true}));
                  e.dispatchEvent(new Event('blur',{bubbles:true}));
                """,vs[0],dob)
            summary["age_fields"].append({"index":idx,"dob":dob,
                "hidden":hs[0].get_attribute("value") if hs else None,
                "visible":vs[0].get_attribute("value") if vs else None})
            print("FLY_CHILD_DOB_SET",summary["age_fields"][-1])
        hidden_children=d.find_elements(By.CSS_SELECTOR,"input[name='filter[child]']")
        print("FLY_PARTY_BEFORE_APPLY",{
            "adults":adult_hidden[0].get_attribute("value") if adult_hidden else None,
            "children":hidden_children[0].get_attribute("value") if hidden_children else None,
            "ages":summary["age_fields"]
        })

        # Apply the participant dropdown. Fly uses live-search/AJAX; there is
        # no reliable primary "Szukaj" button on this results surface.
        applied=False
        roots=d.find_elements(By.CSS_SELECTOR,"[data-drop='person']")
        if roots:
            oks=roots[0].find_elements(By.CSS_SELECTOR,"button[data-ok]")
            for b in oks:
                try:
                    if b.is_displayed() and b.is_enabled():
                        d.execute_script("arguments[0].click()",b);applied=True;break
                except: pass
        summary["applied"]=applied
        print("FLY_PARTY_APPLIED",applied)
        time.sleep(8)
        print("FLY_FINAL_URL",d.current_url)
        q=parse_qs(urlsplit(d.current_url).query)
        summary["final_query"]=q
        print("FLY_FINAL_QUERY",json.dumps(q,ensure_ascii=False,sort_keys=True))
        body=d.find_element(By.TAG_NAME,"body").text
        party_lines=[x.strip() for x in body.splitlines() if x.strip() and ("doros" in x.lower() or "dzieci" in x.lower())]
        summary["body_party"]=" | ".join(party_lines[:8])
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["doros","dzieci","5 lat","7 lat","za wszystkich","zł/os","all inclusive","warszawa - radom","warszawa - modlin","warszawa - okęcie"]):
                print("FLY_SIGNAL",line[:1000])
        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or ""; blob=(u+" "+post).lower()
                if any(k in blob for k in ["search","filter","adult","child","person","dziec","occup"]):
                    if (u,post) not in seen:
                        seen.add((u,post));print("FLY_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except: pass
        print("FLY_EXACT_SUMMARY",json.dumps({
            "child_count":summary["child_count"],
            "age_fields":summary["age_fields"],
            "applied":summary["applied"],
            "final_query":summary["final_query"],
            "body_party":summary["body_party"],
            "childlist_snip":compact(summary["childlist"])[:3500]
        },ensure_ascii=False))
        d.save_screenshot("fly-exact.png")
    finally:d.quit()

if __name__=="__main__":main()
