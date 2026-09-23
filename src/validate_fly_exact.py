import json,re,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit,parse_qs,urlencode

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

def visible_people_root(d):
    roots=d.find_elements(By.CSS_SELECTOR,"[data-module='dropdown'][data-drop='person']")
    for el in roots:
        try:
            if el.is_displayed():
                return el
        except:
            pass
    return roots[0] if roots else None

def open_people(d):
    candidates=d.find_elements(By.CSS_SELECTOR,"[data-module='dropdown'][data-drop='person']")
    candidates=sorted(candidates,key=lambda e: 0 if e.is_displayed() else 1)
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
        print("FLY_OPENED",open_people(d))
        root=visible_people_root(d)
        if root is None:
            raise RuntimeError("Fly participant dropdown not found")
        p=root.find_elements(By.CSS_SELECTOR,"input[name='filter[person]']")
        ch=root.find_elements(By.CSS_SELECTOR,"input[name='filter[child]']")
        print("FLY_PARTY_HIDDEN_BEFORE",p[0].get_attribute("value") if p else None,ch[0].get_attribute("value") if ch else None)

        # Scope every interaction to the currently visible participant dropdown.
        # The page contains duplicate/sticky forms; global [0] selectors can hit
        # a hidden copy and silently leave the real search at 2+0.
        adult_hidden=p
        a=bool(adult_hidden and adult_hidden[0].get_attribute("value")=="2")
        print("FLY_ADULTS_EXACT",a,adult_hidden[0].get_attribute("value") if adult_hidden else None)
        child_box=root.find_elements(By.CSS_SELECTOR,"[data-counter='child']")
        c=False
        if child_box:
            plus=child_box[0].find_elements(By.CSS_SELECTOR,"button.plus")
            if plus:
                for i in range(2):
                    try:
                        d.execute_script("arguments[0].scrollIntoView({block:'center'})",plus[0])
                        plus[0].click()
                    except:
                        d.execute_script("arguments[0].click()",plus[0])
                    time.sleep(.8)
                    span=child_box[0].find_elements(By.CSS_SELECTOR,".counter span")
                    hidden=root.find_elements(By.CSS_SELECTOR,"input[name='filter[child]']")
                    visible_count=compact(span[0].text) if span else None
                    hidden_count=hidden[0].get_attribute("value") if hidden else None
                    summary["child_count"]=visible_count
                    print("FLY_CHILD_PLUS",i+1,{"visible":visible_count,"hidden":hidden_count})
                c=True
        print("FLY_COUNTS_SET",a,c)
        time.sleep(1)
        p=root.find_elements(By.CSS_SELECTOR,"input[name='filter[person]']")
        ch=root.find_elements(By.CSS_SELECTOR,"input[name='filter[child]']")
        span=root.find_elements(By.CSS_SELECTOR,"[data-counter='child'] .counter span")
        print("FLY_PARTY_STATE_AFTER_COUNTER",{
            "adults_hidden":p[0].get_attribute("value") if p else None,
            "children_hidden":ch[0].get_attribute("value") if ch else None,
            "children_visible":compact(span[0].text) if span else None
        })
        childlists=root.find_elements(By.CSS_SELECTOR,"[data-childlist]")
        if childlists:
            summary["childlist"]=(childlists[0].get_attribute("outerHTML") or "")
            print("FLY_CHILDLIST_HTML",summary["childlist"][:9000])

        age_controls=[]
        roots=root.find_elements(By.CSS_SELECTOR,"[data-childlist]")
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
            hs=root.find_elements(By.CSS_SELECTOR,f"input[name='filter[childAge][{idx}]']")
            vs=root.find_elements(By.CSS_SELECTOR,f"input[data-birthdate='{idx}']")
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
        hidden_children=root.find_elements(By.CSS_SELECTOR,"input[name='filter[child]']")
        print("FLY_PARTY_BEFORE_APPLY",{
            "adults":adult_hidden[0].get_attribute("value") if adult_hidden else None,
            "children":hidden_children[0].get_attribute("value") if hidden_children else None,
            "ages":summary["age_fields"]
        })

        # Apply the participant dropdown. Fly uses live-search/AJAX; there is
        # no reliable primary "Szukaj" button on this results surface.
        applied=False
        oks=root.find_elements(By.CSS_SELECTOR,"button[data-ok]")
        print("FLY_APPLY_BUTTON_COUNT",len(oks))
        for b in oks:
            try:
                print("FLY_APPLY_BUTTON",{"displayed":b.is_displayed(),"enabled":b.is_enabled(),"html":(b.get_attribute("outerHTML") or "")[:800]})
                if not b.is_enabled():
                    continue
                # Fly keeps duplicate/sticky form layers and Selenium may report
                # the active OK as not displayed after datepicker DOM updates.
                # Dispatch on the exact button inside the active participant root.
                d.execute_script("arguments[0].click()",b)
                applied=True
                break
            except Exception as e:
                print("FLY_APPLY_ERR",type(e).__name__,str(e)[:180])
        summary["applied"]=applied
        print("FLY_PARTY_APPLIED",applied)
        time.sleep(8)
        try:
            newroot=visible_people_root(d)
            if newroot is not None:
                nh=newroot.find_elements(By.CSS_SELECTOR,"input[name='filter[child]']")
                ns=newroot.find_elements(By.CSS_SELECTOR,"[data-counter='child'] .counter span")
                print("FLY_PARTY_STATE_AFTER_APPLY",{
                  "hidden":nh[0].get_attribute("value") if nh else None,
                  "visible":compact(ns[0].text) if ns else None
                })
        except Exception as e:
            print("FLY_AFTER_APPLY_STATE_ERR",type(e).__name__,str(e)[:180])
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
                if "fly.pl" in u and any(k in blob for k in ["search","filter","adult","child","person","dziec","occup"]):
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
        # Direct GET proof using the exact field names exposed by Fly's own
        # form. This avoids relying on a fragile dropdown close/apply event.
        direct_params=[
            ("filter[person]","2"),("filter[child]","2"),
            ("filter[childAge][1]",dobs[0]),("filter[childAge][2]",dobs[1]),
            ("filter[addTransport]","F"),("filter[forceFilter]","1")
        ]
        direct=URL+"?"+urlencode(direct_params)
        print("FLY_DIRECT_URL",direct)
        d.get(direct);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(7)
        print("FLY_DIRECT_FINAL",d.current_url)
        direct_q=parse_qs(urlsplit(d.current_url).query)
        print("FLY_DIRECT_QUERY",json.dumps(direct_q,ensure_ascii=False,sort_keys=True))
        vals={}
        for sel,key in [
            ("input[name='filter[person]']","person"),
            ("input[name='filter[child]']","child"),
            ("input[name='filter[childAge][1]']","age1"),
            ("input[name='filter[childAge][2]']","age2")]:
            es=d.find_elements(By.CSS_SELECTOR,sel)
            vals[key]=es[0].get_attribute("value") if es else None
        print("FLY_DIRECT_FIELDS",vals)
        body_direct=d.find_element(By.TAG_NAME,"body").text
        lines=[x.strip() for x in body_direct.splitlines() if x.strip()]
        for line in lines:
            lo=line.lower()
            if any(k in lo for k in ["2 dzieci","2 osoby dorosłe","za wszystkich","zł/os","all inclusive"]):
                print("FLY_DIRECT_SIGNAL",line[:1000])
        exact_direct=(
            vals.get("person")=="2" and vals.get("child")=="2"
            and vals.get("age1")==dobs[0] and vals.get("age2")==dobs[1]
        )
        print("FLY_DIRECT_EXACT_2PLUS2",exact_direct)

        d.save_screenshot("fly-exact.png")
    finally:d.quit()

if __name__=="__main__":main()
