import json,re,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://oasis.pl/"

def compact(s): return " ".join((s or "").split())

def click_text(d,text,label):
    xp=f"//*[self::button or self::div or self::span or @role='button'][contains(normalize-space(.),'{text}')]"
    els=d.find_elements(By.XPATH,xp)
    els=[e for e in els if e.is_displayed()]
    els.sort(key=lambda e:len(compact(e.text)))
    for e in els[:12]:
        try:
            print("OASIS_CLICK_TRY",label,repr({"tag":e.tag_name,"text":compact(e.text)[:400],"class":e.get_attribute("class"),"html":(e.get_attribute("outerHTML") or "")[:1800]}))
            d.execute_script("arguments[0].click()",e);time.sleep(.8);return True
        except Exception as ex:print("OASIS_CLICK_ERR",type(ex).__name__,str(ex)[:160])
    return False

def family_controls(d,label):
    print(label)
    out=[]
    for e in d.find_elements(By.XPATH,"//button|//input|//select|//*[@role='button']|//*[@role='combobox']"):
        try:
            if not e.is_displayed():continue
            txt=compact(e.text)
            blob=" ".join(filter(None,[txt,e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("class"),e.get_attribute("aria-label"),e.get_attribute("placeholder"),e.get_attribute("value"),e.get_attribute("title")]))
            lo=blob.lower()
            if any(k in lo for k in ["doros","dzie","wiek","lat","adult","child","person","osob","uczest","passenger","birth"]) or txt in ["+","-","−","＋"]:
                rec={"tag":e.tag_name,"text":txt[:250],"name":e.get_attribute("name"),"id":e.get_attribute("id"),"class":e.get_attribute("class"),"aria":e.get_attribute("aria-label"),"placeholder":e.get_attribute("placeholder"),"value":e.get_attribute("value"),"html":(e.get_attribute("outerHTML") or "")[:2200]}
                out.append((e,rec));print("OASIS_CTRL",repr(rec))
        except:pass
    return out

def counter(d,label):
    nodes=d.find_elements(By.XPATH,f"//*[contains(normalize-space(.),'{label}')]")
    nodes=[n for n in nodes if n.is_displayed()]
    nodes.sort(key=lambda x:len(compact(x.text)))
    for n in nodes:
        try:
            anc=n
            for level in range(1,7):
                anc=anc.find_element(By.XPATH,"..")
                buttons=[b for b in anc.find_elements(By.TAG_NAME,"button") if b.is_displayed() and b.is_enabled()]
                if len(buttons)>=2:
                    print("OASIS_COUNTER",label,level,(anc.get_attribute("outerHTML") or "")[:5000])
                    return anc,buttons
        except:pass
    return None,[]

def set_field(d,e,value):
    try:
        d.execute_script("""
        const e=arguments[0],v=arguments[1],p=Object.getPrototypeOf(e),desc=Object.getOwnPropertyDescriptor(p,'value');
        if(desc&&desc.set)desc.set.call(e,v);else e.value=v;
        for(const n of ['input','change','blur'])e.dispatchEvent(new Event(n,{bubbles:true}));
        """,e,value);time.sleep(.5)
        print("OASIS_SET",value,"=>",e.get_attribute("value"))
        return e.get_attribute("value")
    except Exception as ex:print("OASIS_SET_ERR",type(ex).__name__,str(ex)[:160]);return ""

def main():
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3400");o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(6)
        for t in ["Zaakceptuj wszystko","Akceptuję","Akceptuj","OK"]:
            if click_text(d,t,"cookies"):break
        print("OASIS_START",d.current_url)
        opened=click_text(d,"2 dorosłych","party")
        time.sleep(.8)
        # The outer .participants div is not the React click target. If the
        # dropdown did not materialize, click the inner .mainInput directly.
        has_children=any(e.is_displayed() for e in d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Dzieci')]"))
        if not has_children:
            mains=[e for e in d.find_elements(By.CSS_SELECTOR,".participants .mainInput") if e.is_displayed()]
            for e in mains[:3]:
                try:
                    print("OASIS_PARTY_MAININPUT",(e.get_attribute("outerHTML") or "")[:2500])
                    e.click();time.sleep(1)
                    has_children=any(x.is_displayed() for x in d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Dzieci')]"))
                    if has_children: break
                except Exception as ex:
                    print("OASIS_PARTY_MAININPUT_ERR",type(ex).__name__,str(ex)[:180])
                    try:
                        d.execute_script("arguments[0].click()",e);time.sleep(1)
                        has_children=any(x.is_displayed() for x in d.find_elements(By.XPATH,"//*[contains(normalize-space(.),'Dzieci')]"))
                        if has_children: break
                    except: pass
        opened=bool(opened and has_children)
        print("OASIS_PARTY_OPENED",opened,"HAS_CHILDREN_UI",has_children);time.sleep(1)
        family_controls(d,"OASIS_CONTROLS_OPEN")
        # React renders the participant stepper mostly as styled divs, so
        # inspect the shortest visible DOM blocks around the family labels,
        # not only native button/input elements.
        for label in ["Dorośli","Dzieci","dzieci","Wiek"]:
            nodes=d.find_elements(By.XPATH,f"//*[contains(normalize-space(.),'{label}')]")
            nodes=[n for n in nodes if n.is_displayed()]
            nodes.sort(key=lambda n:len(compact(n.text)))
            for n in nodes[:8]:
                try:
                    print("OASIS_FAMILY_NODE",label,repr({
                      "tag":n.tag_name,"text":compact(n.text)[:500],"class":n.get_attribute("class"),
                      "html":(n.get_attribute("outerHTML") or "")[:5000]
                    }))
                    anc=n
                    for level in range(1,4):
                        anc=anc.find_element(By.XPATH,"..")
                        print("OASIS_FAMILY_ANCESTOR",label,level,(anc.get_attribute("outerHTML") or "")[:7000])
                except: pass
        for e in d.find_elements(By.XPATH,"//*[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'participant')]"):
            try:
                if e.is_displayed():
                    print("OASIS_PARTICIPANT_CLASS",repr({"tag":e.tag_name,"class":e.get_attribute("class"),
                      "text":compact(e.text)[:1000],"html":(e.get_attribute("outerHTML") or "")[:9000]}))
            except: pass

        ca,buttons=counter(d,"Dzieci")
        if ca is not None:
            plus=[b for b in buttons if compact(b.text) in ["+","＋"] or "plus" in ((b.get_attribute("aria-label") or "")+" "+(b.get_attribute("class") or "")).lower()]
            if not plus:plus=[buttons[-1]]
            for i in range(2):
                d.execute_script("arguments[0].click()",plus[-1]);time.sleep(.8);print("OASIS_CHILD_PLUS",i+1)
        family_controls(d,"OASIS_CONTROLS_AFTER_CHILDREN")
        for p in d.find_elements(By.CSS_SELECTOR,".participants"):
            try:
                if p.is_displayed():
                    print("OASIS_PARTICIPANTS_AFTER_CHILDREN",(p.get_attribute("outerHTML") or "")[:24000])
            except: pass
        # Dump shortest visible nodes mentioning child/age after React has
        # rendered the two child rows. These controls can be styled divs rather
        # than native input/select elements.
        for needle in ["Dziecko","dziecko","lat","Wiek","wiek"]:
            nodes=[x for x in d.find_elements(By.XPATH,f"//*[contains(normalize-space(.),'{needle}')]") if x.is_displayed()]
            nodes.sort(key=lambda x:len(compact(x.text)))
            for x in nodes[:16]:
                try:
                    print("OASIS_AFTER_CHILD_NODE",needle,repr({
                      "tag":x.tag_name,"text":compact(x.text)[:700],"class":x.get_attribute("class"),
                      "html":(x.get_attribute("outerHTML") or "")[:7000]
                    }))
                except: pass

        # Oasis renders two controlled DOB text fields only after the child
        # counter reaches 2. Fill those exact React controls first.
        age_inputs=[e for e in d.find_elements(By.CSS_SELECTOR,".participants input.ageInput") if e.is_displayed()]
        print("OASIS_EXACT_AGE_INPUT_COUNT",len(age_inputs))
        for i,(e,target) in enumerate(zip(age_inputs,["01.01.2021","01.01.2019"])):
            try:
                e.click()
                from selenium.webdriver.common.keys import Keys
                e.send_keys(Keys.CONTROL,"a");e.send_keys(target);e.send_keys(Keys.TAB);time.sleep(.7)
                print("OASIS_EXACT_DOB",i,target,"=>",e.get_attribute("value"))
            except Exception as ex:
                print("OASIS_EXACT_DOB_ERR",i,type(ex).__name__,str(ex)[:180])
        confirms=[e for e in d.find_elements(By.CSS_SELECTOR,".participants button.confirmButton") if e.is_displayed()]
        if confirms:
            print("OASIS_CONFIRM_STATE",{"disabled":confirms[0].get_attribute("disabled"),"html":(confirms[0].get_attribute("outerHTML") or "")[:1800]})
            if not confirms[0].get_attribute("disabled"):
                d.execute_script("arguments[0].click()",confirms[0]);time.sleep(1.2);print("OASIS_EXACT_PARTY_CONFIRMED",True)
            else:
                print("OASIS_EXACT_PARTY_CONFIRMED",False)
        else:
            print("OASIS_EXACT_PARTY_CONFIRMED",False)

        ages=[]
        for e in d.find_elements(By.XPATH,"//input|//select"):
            try:
                if not e.is_displayed():continue
                blob=" ".join(filter(None,[e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),compact(e.text)])).lower()
                if any(k in blob for k in ["wiek","age","urodz","birth","dziec","child"]):
                    ages.append(e);print("OASIS_AGE_FIELD",repr({"tag":e.tag_name,"name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),"placeholder":e.get_attribute("placeholder"),"html":(e.get_attribute("outerHTML") or "")[:2200]}))
            except:pass
        for i,target in enumerate(["5","7"]):
            if i>=len(ages):break
            e=ages[i]
            if e.tag_name=="select":
                try:
                    from selenium.webdriver.support.ui import Select
                    Select(e).select_by_value(target);time.sleep(.4);print("OASIS_AGE_SELECT",i,target,e.get_attribute("value"));continue
                except:pass
            set_field(d,e,target)

        family_controls(d,"OASIS_FINAL_FAMILY_CONTROLS")
        body=compact(d.find_element(By.TAG_NAME,"body").text)
        for needle in ["2 doros","2 dzieci","5 lat","7 lat"]:
            print("OASIS_BODY_PARTY",needle,needle.lower() in body.lower())

        # Party confirmation is handled exclusively by .confirmButton
        # above. Never use broad text matching here (e.g. "OK" matched KOCHAJ).
        time.sleep(1)
        print("OASIS_BEFORE_SEARCH",d.current_url)
        clicked=click_text(d,"Wyszukaj","search")
        print("OASIS_SEARCH_CLICKED",clicked);time.sleep(8)
        print("OASIS_FINAL_URL",d.current_url)
        body2=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body2.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["doros","dzieci","5 lat","7 lat","zł","all inclusive","cena"]):
                print("OASIS_SIGNAL",line[:1000])
        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if any(k in blob for k in ["adult","child","person","passenger","occup","room","search","offer","booking","bluevendo"]):
                    key=(u,post)
                    if key not in seen:
                        seen.add(key);print("OASIS_REQ",req.get("method"),u[:6000],"POST",post[:5000])
            except:pass
        print("OASIS_REQ_COUNT",len(seen))
        d.save_screenshot("oasis-exact.png")
    finally:d.quit()

if __name__=="__main__":main()
