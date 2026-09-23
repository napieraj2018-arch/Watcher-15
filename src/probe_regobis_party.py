import json,time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

URL="https://www.rego-bis.pl/rodzina2plus2"
def compact(s): return " ".join((s or "").split())

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]: o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(4)
        for b in d.find_elements(By.TAG_NAME,"button"):
            try:
                if b.is_displayed() and any(x in compact(b.text).lower() for x in ["akceptuj","zaakceptuj","zgadzam"]):
                    d.execute_script("arguments[0].click()",b);time.sleep(.4);break
            except:pass
        trig=d.find_element(By.CSS_SELECTOR,"button[data-search-option-id='participants']")
        did=trig.get_attribute("aria-controls")
        d.execute_script("arguments[0].click()",trig);time.sleep(1)
        print("REGO2_DIALOG_ID",did)
        dialogs=d.find_elements(By.ID,did) if did else []
        if not dialogs:
            dialogs=d.find_elements(By.CSS_SELECTOR,"[role='dialog']")
        print("REGO2_DIALOG_COUNT",len(dialogs))
        if not dialogs:return
        root=dialogs[0]
        print("REGO2_DIALOG_TEXT",compact(root.text)[:8000])
        print("REGO2_DIALOG_HTML",compact(root.get_attribute("outerHTML"))[:30000])

        def dump(label):
            print(label)
            for e in root.find_elements(By.XPATH,".//input|.//select|.//button|.//*[@role='combobox']|.//*[@role='button']"):
                try:
                    if not e.is_displayed():continue
                    print("REGO2_CTRL",json.dumps({
                      "tag":e.tag_name,"text":compact(e.text)[:500],"name":e.get_attribute("name"),
                      "id":e.get_attribute("id"),"type":e.get_attribute("type"),"value":e.get_attribute("value"),
                      "aria":e.get_attribute("aria-label"),"class":e.get_attribute("class"),
                      "html":compact(e.get_attribute("outerHTML"))[:2500]
                    },ensure_ascii=False))
                except:pass
        dump("REGO2_BEFORE")

        # Force a clean 0 -> 2 transition to make age controls materialize.
        minus=d.find_elements(By.CSS_SELECTOR,"button[aria-label='Zmniejsz liczbę dzieci']")
        plus=d.find_elements(By.CSS_SELECTOR,"button[aria-label='Zwiększ liczbę dzieci']")
        for _ in range(4):
            if minus:
                try:d.execute_script("arguments[0].click()",minus[0]);time.sleep(.35)
                except:pass
        for i in range(2):
            if plus:
                d.execute_script("arguments[0].click()",plus[0]);time.sleep(.6)
                print("REGO2_CHILD_PLUS",i+1)
        dump("REGO2_AFTER_CHILDREN")

        age_selects=[]
        for e in root.find_elements(By.TAG_NAME,"select"):
            try:
                opts=[(x.get_attribute("value"),compact(x.text)) for x in e.find_elements(By.TAG_NAME,"option")]
                blob=json.dumps(opts,ensure_ascii=False)
                if any('"5"' in blob or '>5<' in blob for _ in [0]) and any('"7"' in blob or '>7<' in blob for _ in [0]):
                    age_selects.append(e);print("REGO2_AGE_SELECT",json.dumps({"name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),"options":opts[:40]},ensure_ascii=False))
            except:pass
        print("REGO2_AGE_SELECT_COUNT",len(age_selects))
        for i,target in enumerate(["5","7"]):
            if i>=len(age_selects):break
            try:
                Select(age_selects[i]).select_by_value(target);time.sleep(.4)
            except:
                try:Select(age_selects[i]).select_by_visible_text(target);time.sleep(.4)
                except:pass
            print("REGO2_AGE_SET",i+1,target,age_selects[i].get_attribute("value"))

        # Also inspect buttons/comboboxes with age text in case custom Vue controls are used.
        for e in root.find_elements(By.XPATH,".//*"):
            try:
                if not e.is_displayed():continue
                txt=compact(e.text)
                blob=" ".join(filter(None,[txt,e.get_attribute("aria-label"),e.get_attribute("class"),e.get_attribute("data-testid")]))
                if any(k in blob.lower() for k in ["wiek","age","lat","dziecko 1","dziecko 2"]):
                    print("REGO2_AGE_NODE",json.dumps({"tag":e.tag_name,"text":txt[:500],"aria":e.get_attribute("aria-label"),"class":e.get_attribute("class"),"html":compact(e.get_attribute("outerHTML"))[:3500]},ensure_ascii=False))
            except:pass

        # Apply exact party if the dialog exposes an explicit action.
        applied=False
        for b in root.find_elements(By.TAG_NAME,"button"):
            try:
                txt=compact(b.text).lower()
                if b.is_displayed() and b.is_enabled() and any(x in txt for x in ["zastosuj","gotowe","wybierz","szukaj","pokaż","pokaz"]):
                    print("REGO2_APPLY",compact(b.text));d.execute_script("arguments[0].click()",b);applied=True;break
            except:pass
        print("REGO2_APPLIED",applied);time.sleep(8)
        print("REGO2_FINAL_URL",d.current_url)
        print("REGO2_PARTY_LABEL",compact(d.find_element(By.CSS_SELECTOR,"button[data-search-option-id='participants']").text))
        body=d.find_element(By.TAG_NAME,"body").text
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["2 doros","2 dzieci","5 lat","7 lat","cena","zł","all inclusive","warszawa","radom","ofert"]):
                print("REGO2_SIGNAL",line[:1200])
        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or ""
                blob=(u+" "+post).lower()
                if "rego-bis.pl" in u and any(k in blob for k in ["search","offer","filter","participant","child","adult","age","guest","listing"]):
                    if (u,post) not in seen:
                        seen.add((u,post));print("REGO2_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except:pass
        print("REGO2_REQ_COUNT",len(seen))
    finally:d.quit()
if __name__=="__main__":main()
