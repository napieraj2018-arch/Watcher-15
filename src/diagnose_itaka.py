import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.itaka.pl/last-minute/"

def compact(s):
    return " ".join((s or "").split())

def main():
    opts=Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,2800")
    opts.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=opts)
    try:
        d.get(URL)
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(5)
        for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","Zezwól na wszystkie","OK"]:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed():
                    els[0].click(); time.sleep(1); break
            except: pass

        print("TITLE",d.title)
        print("URL",d.current_url)
        # Open filters/search panel to expose party and departure controls.
        try:
            candidates=[
                b for b in d.find_elements(By.TAG_NAME,"button")
                if b.is_displayed() and "Filtry" in compact(b.text)
            ]
            if candidates:
                d.execute_script("arguments[0].click();",candidates[0])
                time.sleep(1.5)
                print("FILTER_OPENED",True)
            else:
                print("FILTER_OPENED",False)
        except Exception as e:
            print("FILTER_OPENED_ERROR",type(e).__name__,str(e)[:200])

        try:
            part=d.find_element(By.CSS_SELECTOR,"[data-testid='participants-filter-input']")
            d.execute_script("arguments[0].click();",part)
            time.sleep(1.0)
            print("PARTICIPANTS_PANEL_OPENED",True)
        except Exception as e:
            print("PARTICIPANTS_PANEL_OPENED",False,type(e).__name__,str(e)[:180])

        try:
            portal=d.find_element(By.CSS_SELECTOR,"[data-testid='portal-content']")
            print("PORTAL_HTML",portal.get_attribute("outerHTML")[:18000])
            print("PORTAL_BUTTONS")
            for idx,b in enumerate(portal.find_elements(By.TAG_NAME,"button")):
                try:
                    if b.is_displayed():
                        print(repr({
                          "idx":idx,
                          "text":compact(b.text),
                          "title":b.get_attribute("title"),
                          "aria":b.get_attribute("aria-label"),
                          "area":b.get_attribute("area-label"),
                          "class":(b.get_attribute("class") or "")[:240],
                          "html":b.get_attribute("outerHTML")[:900]
                        }))
                except: pass

            print("ITAKA_DETAIL_URL",detail_candidate)
            if detail_candidate:
                d.get(detail_candidate)
                WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
                time.sleep(6)
                print("ITAKA_DETAIL_FINAL_URL",d.current_url)
                detail_body=d.find_element(By.TAG_NAME,"body").text
                print("ITAKA_DETAIL_PRICE_LINES")
                for line in [x.strip() for x in detail_body.splitlines() if x.strip()]:
                    lo=line.lower()
                    if any(k in lo for k in ["zł","cena","razem","łącznie","doros","dzieci","uczest"]):
                        print(line[:600])
        except Exception as e:
            print("PORTAL_INSPECT_ERROR",type(e).__name__,str(e)[:180])

        try:
            label=d.find_element(By.XPATH,"//span[contains(normalize-space(.),'Dzieci (0-17 lat)')]")
            row=label.find_element(By.XPATH,"./ancestor::div[contains(@class,'styles_wrapper')][1]")
            child_buttons=[b for b in row.find_elements(By.TAG_NAME,"button") if b.is_displayed()]
            if len(child_buttons)>=2:
                d.execute_script("arguments[0].click();",child_buttons[-1]); time.sleep(0.35)
                d.execute_script("arguments[0].click();",child_buttons[-1]); time.sleep(0.8)
            portal=d.find_element(By.CSS_SELECTOR,"[data-testid='portal-content']")
            print("CHILDREN_AFTER_ADD",compact(portal.text))
            print("CHILDREN_PORTAL_HTML",portal.get_attribute("outerHTML")[:20000])
            print("CHILDREN_SELECTS")
            selects=portal.find_elements(By.TAG_NAME,"select")
            for s in selects:
                print(repr({
                  "displayed":s.is_displayed(),
                  "name":s.get_attribute("name"),
                  "value":s.get_attribute("value"),
                  "html":s.get_attribute("outerHTML")[:1600]
                }))

            # Set exact child ages using the underlying native selects.
            for s,target in zip(selects,["5 lat","7 lat"]):
                d.execute_script("""
                    const sel=arguments[0], wanted=arguments[1];
                    const opt=[...sel.options].find(o => o.text.trim()===wanted);
                    if (!opt) throw new Error("age option missing: "+wanted);
                    sel.value=opt.value;
                    sel.dispatchEvent(new Event('input',{bubbles:true}));
                    sel.dispatchEvent(new Event('change',{bubbles:true}));
                """,s,target)
                time.sleep(0.5)
            print("AGES_SET",[s.get_attribute("value") for s in selects])

            portal=d.find_element(By.CSS_SELECTOR,"[data-testid='portal-content']")
            show=[b for b in portal.find_elements(By.TAG_NAME,"button") if compact(b.text)=="Pokaż oferty"]
            if show:
                d.execute_script("arguments[0].click();",show[0])
                time.sleep(5)
            print("AFTER_PARTY_URL",d.current_url)
            try:
                print("AFTER_PARTY_TEXT",compact(d.find_element(By.CSS_SELECTOR,"[data-testid='participants-filter-input']").text))
            except: pass

            print("ITAKA_IMMINENT_TILES")
            detail_candidate=None
            for tile in d.find_elements(By.CSS_SELECTOR,"[data-testid='offer-list-item']"):
                try:
                    txt=compact(tile.text)
                    if any(day in txt for day in ["24.09","25.09","26.09"]):
                        a=tile.find_element(By.CSS_SELECTOR,"a[href*='/wczasy/']")
                        href=a.get_attribute("href")
                        print(repr({"text":txt[:1800],"href":href}))
                        if detail_candidate is None and "Warszawa" in txt and "All inclusive" in txt:
                            detail_candidate=href
                except: pass
            print("CHILDREN_INPUTS")
            for inp in portal.find_elements(By.TAG_NAME,"input"):
                if inp.is_displayed():
                    print(repr({
                      "type":inp.get_attribute("type"),
                      "name":inp.get_attribute("name"),
                      "placeholder":inp.get_attribute("placeholder"),
                      "value":inp.get_attribute("value"),
                      "aria":inp.get_attribute("aria-label"),
                      "html":inp.get_attribute("outerHTML")[:1200]
                    }))
            print("CHILDREN_BUTTONS")
            for idx,b in enumerate(portal.find_elements(By.TAG_NAME,"button")):
                if b.is_displayed():
                    print(repr({
                      "idx":idx,
                      "text":compact(b.text)[:200],
                      "title":b.get_attribute("title"),
                      "aria":b.get_attribute("aria-label"),
                      "class":(b.get_attribute("class") or "")[:220],
                      "html":b.get_attribute("outerHTML")[:1000]
                    }))
        except Exception as e:
            print("CHILDREN_ADD_ERROR",type(e).__name__,str(e)[:250])

        print("PARTICIPANT_TESTIDS")
        seenp=set()
        for el in d.find_elements(By.CSS_SELECTOR,"[data-testid]"):
            try:
                if not el.is_displayed():
                    continue
                tid=el.get_attribute("data-testid") or ""
                txt=compact(el.text)
                blob=(tid+" "+txt).lower()
                if any(k in blob for k in ["adult","child","dziec","uczest","person","participant","room","wiek","age"]):
                    item=(el.tag_name,tid,txt[:200])
                    if item in seenp: continue
                    seenp.add(item)
                    print(repr({
                      "tag":el.tag_name,
                      "testid":tid,
                      "text":txt[:350],
                      "aria":el.get_attribute("aria-label"),
                      "name":el.get_attribute("name"),
                      "value":el.get_attribute("value"),
                      "class":(el.get_attribute("class") or "")[:180],
                      "html":el.get_attribute("outerHTML")[:1100]
                    }))
            except: pass

        print("VISIBLE_TESTIDS")
        seen=set()
        for el in d.find_elements(By.CSS_SELECTOR,"[data-testid]"):
            try:
                if not el.is_displayed():
                    continue
                tid=el.get_attribute("data-testid") or ""
                txt=compact(el.text)
                item=(el.tag_name,tid,txt[:200])
                if item in seen: continue
                seen.add(item)
                if any(k in (tid+" "+txt).lower() for k in [
                    "adult","child","dziec","uczest","person","room","airport","date","price","meal","board","filter"
                ]):
                    print(repr({
                      "tag":el.tag_name,
                      "testid":tid,
                      "text":txt[:350],
                      "aria":el.get_attribute("aria-label"),
                      "value":el.get_attribute("value"),
                      "html":el.get_attribute("outerHTML")[:1000]
                    }))
            except: pass

        print("INPUTS")
        for el in d.find_elements(By.TAG_NAME,"input"):
            try:
                if el.is_displayed():
                    print(repr({
                      "name":el.get_attribute("name"),
                      "type":el.get_attribute("type"),
                      "placeholder":el.get_attribute("placeholder"),
                      "aria":el.get_attribute("aria-label"),
                      "value":el.get_attribute("value"),
                      "testid":el.get_attribute("data-testid"),
                      "id":el.get_attribute("id"),
                      "class":el.get_attribute("class"),
                    }))
            except: pass

        print("BUTTONS")
        n=0
        for el in d.find_elements(By.TAG_NAME,"button"):
            try:
                if el.is_displayed():
                    txt=compact(el.text); aria=compact(el.get_attribute("aria-label"))
                    if txt or aria:
                        print(repr({
                            "text":txt[:250],"aria":aria[:250],
                            "testid":el.get_attribute("data-testid"),
                            "id":el.get_attribute("id"),
                            "class":el.get_attribute("class")[:180]
                        }))
                        n+=1
                        if n>=220: break
            except: pass

        body=d.find_element(By.TAG_NAME,"body").text
        print("LINES")
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in [
                "uczest","doros","dzieci","wylot","warszawa","radom",
                "all inclusive","noc","cena","osob"
            ]):
                print(line[:600])
        d.save_screenshot("itaka-diagnostic.png")
    finally:
        d.quit()

if __name__=="__main__":
    main()
