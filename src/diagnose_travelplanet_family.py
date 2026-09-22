import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select

URL="https://www.travelplanet.pl/wakacje/super-last-minute/"

def compact(s): return " ".join((s or "").split())

def main():
    o=Options(); o.add_argument("--headless=new"); o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage"); o.add_argument("--window-size=1440,3000"); o.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL); WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete"); time.sleep(4)
        for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed(): d.execute_script("arguments[0].click();",els[0]);time.sleep(.6);break
            except:pass

        child=d.find_element(By.CSS_SELECTOR,"[data-testid='person-textbox-control-children']")
        d.execute_script("arguments[0].click();",child);time.sleep(1)
        print("PICKER_OPEN_URL",d.current_url)

        print("PICKER_ELEMENTS")
        n=0
        for el in d.find_elements(By.CSS_SELECTOR,"[data-testid],button,input,select"):
            try:
                if not el.is_displayed(): continue
                txt=compact(el.text)
                attrs=" ".join(filter(None,[el.get_attribute("data-testid"),el.get_attribute("name"),el.get_attribute("aria-label"),el.get_attribute("placeholder"),txt]))
                if any(k in attrs.lower() for k in ["person","child","adult","dzie","doros","wiek","age","room","pok"]):
                    print(repr({"tag":el.tag_name,"text":txt[:240],"testid":el.get_attribute("data-testid"),"name":el.get_attribute("name"),"value":el.get_attribute("value"),"aria":el.get_attribute("aria-label"),"html":el.get_attribute("outerHTML")[:1200]}));n+=1
                    if n>=120:break
            except:pass

        # Locate the numeric spinner by its "Liczba dzieci" label and click
        # the append/plus button twice.
        pluses=[]
        try:
            label=d.find_element(By.XPATH,"//label[.//*[contains(normalize-space(.),'Liczba dzieci')] or contains(normalize-space(.),'Liczba dzieci')]")
            spinner=label.find_element(By.XPATH,"./ancestor::div[contains(@class,'i-textbox--numeric-spinner')][1]")
            buttons=[b for b in spinner.find_elements(By.TAG_NAME,"button") if b.is_displayed()]
            print("CHILD_SPINNER_HTML",spinner.get_attribute("outerHTML")[:4000])
            print("CHILD_SPINNER_BUTTONS",[compact(b.text) for b in buttons])
            if len(buttons)>=2:
                pluses=[buttons[-1]]
        except Exception as e:
            print("CHILD_SPINNER_ERROR",type(e).__name__,str(e)[:240])
        print("CHILD_PLUS_COUNT",len(pluses))
        if pluses:
            for _ in range(2):
                d.execute_script("arguments[0].click();",pluses[0]);time.sleep(.5)
        print("CHILD_COUNT_AFTER",d.find_element(By.CSS_SELECTOR,"[data-testid='person-textbox-control-children']").get_attribute("value"))

        print("AFTER_CHILDREN_ELEMENTS")
        for el in d.find_elements(By.XPATH,"//select|//input|//button"):
            try:
                if not el.is_displayed(): continue
                txt=compact(el.text)
                attrs=" ".join(filter(None,[el.get_attribute("data-testid"),el.get_attribute("name"),el.get_attribute("aria-label"),el.get_attribute("placeholder"),txt]))
                if any(k in attrs.lower() for k in ["age","wiek","child","dzie"]):
                    print(repr({"tag":el.tag_name,"text":txt[:240],"testid":el.get_attribute("data-testid"),"name":el.get_attribute("name"),"value":el.get_attribute("value"),"aria":el.get_attribute("aria-label"),"html":el.get_attribute("outerHTML")[:1400]}))
            except:pass

        print("SET_AGES_5_7")
        try:
            Select(d.find_element(By.CSS_SELECTOR,"select[name='child-1']")).select_by_value("5")
            time.sleep(.3)
            Select(d.find_element(By.CSS_SELECTOR,"select[name='child-2']")).select_by_value("7")
            time.sleep(.5)
            print("AGES_AFTER",
                  d.find_element(By.CSS_SELECTOR,"select[name='child-1']").get_attribute("value"),
                  d.find_element(By.CSS_SELECTOR,"select[name='child-2']").get_attribute("value"))
        except Exception as e:
            print("SET_AGES_ERROR",type(e).__name__,str(e)[:240])

        # Close picker by clicking the main page heading/search area if necessary.
        try:
            d.find_element(By.CSS_SELECTOR,"[data-testid='sf-submit-button']").click()
        except Exception:
            try:
                d.execute_script("arguments[0].click();",d.find_element(By.CSS_SELECTOR,"[data-testid='sf-submit-button']"))
            except Exception as e:
                print("SEARCH_CLICK_ERROR",type(e).__name__,str(e)[:200])
        time.sleep(6)
        print("AFTER_SEARCH_URL",d.current_url)
        print("AFTER_SEARCH_PARTY",
              d.find_element(By.CSS_SELECTOR,"[data-testid='person-textbox-control-adults']").get_attribute("value"),
              d.find_element(By.CSS_SELECTOR,"[data-testid='person-textbox-control-children']").get_attribute("value"))

        # Inspect a few listing links and first promising detail page.
        print("LISTING_CARDS")
        cards=d.find_elements(By.CSS_SELECTOR,"[data-testid='product-grid-item']")
        detail=None
        for card in cards[:20]:
            try:
                txt=compact(card.text)
                a=card.find_element(By.CSS_SELECTOR,"a[href*='/hotele/']")
                href=a.get_attribute("href")
                print(repr({"text":txt[:900],"href":href}))
                if detail is None and "All inclusive" in txt and href:
                    detail=href
            except Exception:
                pass
        print("DETAIL_CHOSEN",detail)
        if detail:
            d.get(detail)
            WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
            time.sleep(5)
            print("DETAIL_URL",d.current_url)
            body=d.find_element(By.TAG_NAME,"body").text
            print("DETAIL_RELEVANT")
            for line in [x.strip() for x in body.splitlines() if x.strip()]:
                lo=line.lower()
                if any(k in lo for k in ["cena","razem","łącznie","doros","dzieci","wiek","zł","all inclusive","uczest"]):
                    print(line[:700])

        d.save_screenshot("travelplanet-family.png")
    finally:d.quit()
if __name__=="__main__":main()
