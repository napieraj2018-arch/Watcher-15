import json,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://oasis.pl/"

def compact(s): return " ".join((s or "").split())

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3000","--lang=pl-PL"]: o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(4)
        for b in d.find_elements(By.TAG_NAME,"button"):
            try:
                if b.is_displayed() and any(x in compact(b.text) for x in ["Zaakceptuj wszystko","Akceptuję","Akceptuj"]):
                    d.execute_script("arguments[0].click()",b);time.sleep(.5);break
            except: pass
        ps=[x for x in d.find_elements(By.CSS_SELECTOR,".participants") if x.is_displayed()]
        print("OASIS_FOCUS_PARTICIPANTS",len(ps))
        if not ps:return
        p=ps[0]
        mains=p.find_elements(By.CSS_SELECTOR,".mainInput")
        if mains:d.execute_script("arguments[0].click()",mains[0])
        time.sleep(1)
        p=[x for x in d.find_elements(By.CSS_SELECTOR,".participants") if x.is_displayed()][0]
        print("OASIS_FOCUS_HTML",compact(p.get_attribute("outerHTML"))[:24000])
        rows=d.execute_script("""
          const root=arguments[0];
          return [...root.querySelectorAll('*')].map((e,i)=>({
            i,tag:e.tagName,text:(e.innerText||'').replace(/\s+/g,' ').trim().slice(0,180),
            cls:e.className&&typeof e.className==='string'?e.className:'',
            role:e.getAttribute('role'),aria:e.getAttribute('aria-label'),
            type:e.getAttribute('type'),name:e.getAttribute('name'),value:e.value||e.getAttribute('value'),
            placeholder:e.getAttribute('placeholder'),disabled:e.disabled===true
          })).filter(x=>x.text||x.tag==='INPUT'||x.tag==='BUTTON'||x.tag==='SELECT');
        """,p)
        for x in rows:
            blob=(" ".join(str(x.get(k) or "") for k in ["text","cls","role","aria","type","name","placeholder"])).lower()
            if any(k in blob for k in ["doros","dzie","wiek","lat","child","adult","age","plus","minus","confirm","counter"]) or x["tag"] in ["INPUT","BUTTON","SELECT"]:
                print("OASIS_FOCUS_NODE",json.dumps(x,ensure_ascii=False))
        # Target the exact "Dzieci" row discovered above. This avoids
        # ancestor heuristics that previously matched unrelated controls.
        child_row=None
        for row in p.find_elements(By.CSS_SELECTOR,".inputWrapper"):
            try:
                title=row.find_element(By.CSS_SELECTOR,".title")
                if compact(title.text)=="Dzieci":
                    child_row=row;break
            except: pass
        print("OASIS_FOCUS_CHILD_ROW_FOUND",child_row is not None)
        if child_row is not None:
            buttons=child_row.find_elements(By.CSS_SELECTOR,"button.inputButton")
            print("OASIS_FOCUS_CHILD_BUTTONS",len(buttons))
            if len(buttons)>=2:
                for i in range(2):
                    d.execute_script("arguments[0].click()",buttons[-1]);time.sleep(.8)
                    rows2=[x for x in p.find_elements(By.CSS_SELECTOR,".inputWrapper")]
                    value=None
                    for rr in rows2:
                        try:
                            if compact(rr.find_element(By.CSS_SELECTOR,".title").text)=="Dzieci":
                                value=compact(rr.find_element(By.CSS_SELECTOR,".inputValue").text)
                        except: pass
                    print("OASIS_FOCUS_CHILD_PLUS",i+1,value)
        time.sleep(1)
        p=[x for x in d.find_elements(By.CSS_SELECTOR,".participants") if x.is_displayed()][0]
        print("OASIS_FOCUS_AFTER_CHILDREN_HTML",compact(p.get_attribute("outerHTML"))[:30000])
        ages=[x for x in p.find_elements(By.XPATH,".//input") if x.is_displayed()]
        print("OASIS_FOCUS_AGE_INPUTS",len(ages))
        for i,e in enumerate(ages):
            print("OASIS_FOCUS_AGE_INPUT",i,json.dumps({
              "class":e.get_attribute("class"),"type":e.get_attribute("type"),
              "name":e.get_attribute("name"),"placeholder":e.get_attribute("placeholder"),
              "value":e.get_attribute("value")
            },ensure_ascii=False))
        # Print compact network search payloads emitted by initial page state.
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"]
                if "/api-bv/search-search" in req.get("url",""):
                    print("OASIS_FOCUS_SEARCH",req.get("postData") or "")
            except: pass
    finally:d.quit()
if __name__=="__main__":main()
