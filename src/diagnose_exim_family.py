import time,re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL="https://www.exim.pl/last-minute"

def compact(s): return " ".join((s or "").split())

def click_text(d,text):
    els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{text}')]")
    for el in els:
        try:
            if el.is_displayed():
                d.execute_script("arguments[0].click();",el); time.sleep(.8); return True
        except: pass
    return False

def main():
    o=Options(); o.add_argument("--headless=new"); o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage"); o.add_argument("--window-size=1440,3000"); o.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL); WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete"); time.sleep(4)
        for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
            if click_text(d,t): break
        click_text(d,"Liczba uczestników")
        print("OPENED_PARTICIPANTS",d.current_url)

        print("PRESET_2PLUS2",click_text(d,"Rodzina 2+2"))
        time.sleep(2)
        print("AFTER_PRESET_URL",d.current_url)

        print("AGE_CONTROLS")
        for el in d.find_elements(By.XPATH,"//input|//select|//button"):
            try:
                if not el.is_displayed(): continue
                txt=compact(el.text); attrs=" ".join(filter(None,[
                    el.get_attribute("name"),el.get_attribute("id"),el.get_attribute("aria-label"),
                    el.get_attribute("placeholder"),el.get_attribute("data-testid"),txt
                ]))
                if any(k in attrs.lower() for k in ["wiek","dzie","child","age","rok","lat"]):
                    print(repr({"tag":el.tag_name,"text":txt[:250],"name":el.get_attribute("name"),"id":el.get_attribute("id"),"value":el.get_attribute("value"),"aria":el.get_attribute("aria-label"),"html":el.get_attribute("outerHTML")[:1200]}))
            except: pass

        print("SET_EXACT_CHILD_AGES")
        try:
            age_buttons=[b for b in d.find_elements(By.XPATH,"//button[.//div[contains(@class,'f_input-item-value')]]") if b.is_displayed() and ("lat" in compact(b.text).lower() or "poniżej" in compact(b.text).lower())]
            print("AGE_BUTTONS_BEFORE",[compact(b.text) for b in age_buttons])
            targets=["5 lat","7 lat"]
            for idx,target in enumerate(targets):
                age_buttons=[b for b in d.find_elements(By.XPATH,"//button[.//div[contains(@class,'f_input-item-value')]]") if b.is_displayed() and ("lat" in compact(b.text).lower() or "poniżej" in compact(b.text).lower())]
                if idx>=len(age_buttons):
                    raise RuntimeError(f"Missing child age button {idx}")
                d.execute_script("arguments[0].click();",age_buttons[idx]);time.sleep(.5)
                options=[b for b in d.find_elements(By.TAG_NAME,"button") if b.is_displayed() and compact(b.text).lower()==target]
                if not options:
                    print("AGE_OPTION_TEXTS",[compact(b.text) for b in d.find_elements(By.TAG_NAME,"button") if b.is_displayed() and ("lat" in compact(b.text).lower() or "rok" in compact(b.text).lower())][:80])
                    raise RuntimeError(f"Age option not found: {target}")
                d.execute_script("arguments[0].click();",options[-1]);time.sleep(.6)
            age_buttons=[b for b in d.find_elements(By.XPATH,"//button[.//div[contains(@class,'f_input-item-value')]]") if b.is_displayed() and ("lat" in compact(b.text).lower() or "poniżej" in compact(b.text).lower())]
            print("AGE_BUTTONS_AFTER",[compact(b.text) for b in age_buttons])
        except Exception as e:
            print("SET_AGES_ERROR",type(e).__name__,str(e)[:300])

        # Search/apply if a visible action exists.
        for text in ["WYSZUKAJ","SZUKAJ"]:
            if click_text(d,text):
                time.sleep(5); break
        print("AFTER_SEARCH_URL",d.current_url)

        print("DETAIL_LINK_PARAMS")
        n=0
        for a in d.find_elements(By.TAG_NAME,"a"):
            try:
                href=a.get_attribute("href") or ""
                txt=compact(a.text)
                if "Szczegóły hotelu" in txt and href:
                    print(repr({"href":href[:1800]})); n+=1
                    if n>=8: break
            except: pass

        # Open custom party editor too, for exact child ages.
        click_text(d,"Liczba uczestników")
        if click_text(d,"Ustaw inną liczbę osób"):
            time.sleep(1)
            print("CUSTOM_PARTY_OPENED")
            for el in d.find_elements(By.XPATH,"//input|//select|//button"):
                try:
                    if not el.is_displayed(): continue
                    txt=compact(el.text)
                    attrs=" ".join(filter(None,[el.get_attribute("name"),el.get_attribute("id"),el.get_attribute("aria-label"),el.get_attribute("placeholder"),txt]))
                    if any(k in attrs.lower() for k in ["wiek","dzie","child","age","doros","adult","pok","room"]):
                        print("CUSTOM",repr({"tag":el.tag_name,"text":txt[:240],"name":el.get_attribute("name"),"id":el.get_attribute("id"),"value":el.get_attribute("value"),"aria":el.get_attribute("aria-label"),"html":el.get_attribute("outerHTML")[:1400]}))
                except: pass
        d.save_screenshot("exim-family.png")
    finally: d.quit()
if __name__=="__main__": main()
