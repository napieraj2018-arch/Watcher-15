import re
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://www.itaka.pl/last-minute/"

def compact(s):
    return " ".join((s or "").split())

def main():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,2800")
    opts.add_argument("--lang=pl-PL")
    d = webdriver.Chrome(options=opts)
    try:
        d.get(URL)
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(4)

        for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","Zezwól na wszystkie","OK"]:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed():
                    els[0].click(); time.sleep(0.7); break
            except Exception:
                pass

        # Open filters.
        buttons=[b for b in d.find_elements(By.TAG_NAME,"button") if b.is_displayed() and "Filtry" in compact(b.text)]
        if buttons:
            d.execute_script("arguments[0].click();",buttons[0]); time.sleep(1)

        # Open participants.
        part=d.find_element(By.CSS_SELECTOR,"[data-testid='participants-filter-input']")
        d.execute_script("arguments[0].click();",part); time.sleep(0.7)
        portal=d.find_element(By.CSS_SELECTOR,"[data-testid='portal-content']")

        # Set exactly two children.
        child_label=d.find_element(By.XPATH,"//span[contains(normalize-space(.),'Dzieci (0-17 lat)')]")
        child_row=child_label.find_element(By.XPATH,"./ancestor::div[contains(@class,'styles_wrapper')][1]")
        child_buttons=[b for b in child_row.find_elements(By.TAG_NAME,"button") if b.is_displayed()]
        plus=child_buttons[-1]
        for _ in range(2):
            d.execute_script("arguments[0].click();",plus); time.sleep(0.35)

        portal=d.find_element(By.CSS_SELECTOR,"[data-testid='portal-content']")
        selects=portal.find_elements(By.TAG_NAME,"select")
        if len(selects) < 2:
            raise RuntimeError(f"Expected 2 child age selects, found {len(selects)}")

        for s,target in zip(selects[:2],["5 lat","7 lat"]):
            d.execute_script("""
                const sel=arguments[0], wanted=arguments[1];
                const opt=[...sel.options].find(o => o.text.trim()===wanted);
                if (!opt) throw new Error("age option missing: "+wanted);
                sel.value=opt.value;
                sel.dispatchEvent(new Event('input',{bubbles:true}));
                sel.dispatchEvent(new Event('change',{bubbles:true}));
            """,s,target)
            time.sleep(0.4)

        portal=d.find_element(By.CSS_SELECTOR,"[data-testid='portal-content']")
        show=[b for b in portal.find_elements(By.TAG_NAME,"button") if compact(b.text)=="Pokaż oferty"]
        if not show:
            raise RuntimeError("Show offers button missing")
        d.execute_script("arguments[0].click();",show[0])
        time.sleep(5)

        print("PARTY_URL",d.current_url)
        print("PARTY_TEXT",compact(d.find_element(By.CSS_SELECTOR,"[data-testid='participants-filter-input']").text))

        candidates=[]
        for tile in d.find_elements(By.CSS_SELECTOR,"[data-testid='offer-list-item']"):
            try:
                txt=compact(tile.text)
                if not any(day in txt for day in ["24.09","25.09","26.09"]):
                    continue
                if "All inclusive" not in txt:
                    continue
                if not any(ap in txt for ap in ["Warszawa","Modlin","Radom"]):
                    continue
                mr=re.search(r"([0-9][.,][0-9])\s*/6",txt)
                mn=re.search(r"([0-9][0-9 ]*)\s+opini",txt,re.I)
                rating6=float(mr.group(1).replace(",", ".")) if mr else None
                reviews=int(mn.group(1).replace(" ","")) if mn else None
                if rating6 is None or rating6 < 4.8:
                    continue
                if reviews is None or reviews < 30:
                    continue
                a=tile.find_element(By.CSS_SELECTOR,"a[href*='/wczasy/']")
                href=a.get_attribute("href")
                candidates.append((rating6,reviews,txt,href))
                print("CANDIDATE",repr({"rating6":rating6,"reviews":reviews,"text":txt[:1600],"href":href}))
            except Exception as e:
                print("TILE_WARN",type(e).__name__,str(e)[:160])

        candidates.sort(key=lambda x:(-x[0],-x[1]))
        if not candidates:
            print("NO_DETAIL_CANDIDATE")
            d.save_screenshot("itaka-diagnostic.png")
            return

        detail=candidates[0][3]
        print("DETAIL_URL",detail)
        d.get(detail)
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(6)
        print("DETAIL_FINAL_URL",d.current_url)
        body=d.find_element(By.TAG_NAME,"body").text
        print("DETAIL_PRICE_LINES")
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
            lo=line.lower()
            if any(k in lo for k in ["zł","cena","razem","łącznie","doros","dzieci","uczest"]):
                print(line[:700])

        d.save_screenshot("itaka-diagnostic.png")
    finally:
        d.quit()

if __name__=="__main__":
    main()
