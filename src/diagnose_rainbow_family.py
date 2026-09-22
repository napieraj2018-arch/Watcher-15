import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

URL=(
"https://r.pl/wyloty-z-warszawy?"
"dlugoscPobytu=5-8&dlugoscPobytu.od=5&dlugoscPobytu.do=8&"
"cena=avg&cena.od=&cena.do=&ocenaKlientow=*-*&odlegloscLotnisko=*-*&"
"dlugoscPobytu.od.force=t&dlugoscPobytu.do.force=t&cena.od.force=t&cena.do.force=t&"
"wybraneSkad=WAW&wybraneSkad=WMI&typTransportu=AIR&"
"data=2026-09-24&dataWylotu=2026-09-24&"
"dorosli=1996-09-22&dorosli=1996-09-22&"
"dzieci=2021-08-24&dzieci=2019-08-24&"
"liczbaPokoi=1&dowolnaLiczbaPokoi=nie&hotelUrl&produktUrl&sortowanie=cena-asc"
)

def compact(s): return " ".join((s or "").split())

def main():
    o=Options()
    o.add_argument("--headless=new"); o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage"); o.add_argument("--window-size=1440,2800")
    o.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=o)
    try:
        d.get(URL)
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(5)
        print("FINAL_URL",d.current_url)
        body=d.find_element(By.TAG_NAME,"body").text
        lines=[x.strip() for x in body.splitlines() if x.strip()]
        print("PARTY_LINES")
        for line in lines:
            lo=line.lower()
            if any(k in lo for k in ["doros","dzie","uczest","pokój","osób"]):
                print(line[:500])
        print("OFFER_LINES")
        for i,line in enumerate(lines):
            lo=line.lower()
            if ("all inclusive" in lo or "zł/os" in lo or "szczegóły" in lo) and i<600:
                print(line[:600])
        print("LINKS")
        n=0
        for a in d.find_elements(By.TAG_NAME,"a"):
            try:
                href=a.get_attribute("href") or ""
                txt=compact(a.text)
                if href and txt and ("szczegó" in txt.lower() or "/hotel" in href.lower() or "/oferta" in href.lower()):
                    print(repr({"text":txt[:300],"href":href[:1000]}))
                    n+=1
                    if n>=40: break
            except: pass
        print("DETAIL_CHECKS")
        candidates=[]
        for a in d.find_elements(By.TAG_NAME,"a"):
            try:
                href=a.get_attribute("href") or ""
                txt=compact(a.text)
                if not href or not txt or "SZCZEGÓŁY" not in txt:
                    continue
                if "All inclusive" not in txt and "All Inclusive" not in txt:
                    continue
                m=__import__("re").search(r"(\d[.,]\d)\s*/\s*6\s*\((\d+)\s+opini",txt)
                if not m:
                    continue
                rating=float(m.group(1).replace(",","."))
                reviews=int(m.group(2).replace(" ",""))
                if rating < 4.8 or reviews < 30:
                    continue
                candidates.append((href,txt,rating,reviews))
            except Exception:
                pass

        for href,txt,rating,reviews in candidates[:3]:
            print("DETAIL_OPEN",repr({"href":href,"rating6":rating,"reviews":reviews,"listing":txt[:700]}))
            d.get(href)
            WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
            time.sleep(5)
            body2=d.find_element(By.TAG_NAME,"body").text
            lines2=[x.strip() for x in body2.splitlines() if x.strip()]
            print("DETAIL_URL",d.current_url)
            print("DETAIL_RELEVANT_LINES")
            for line in lines2:
                lo=line.lower()
                if any(k in lo for k in ["cena", "razem", "łącznie", "doros", "dzieci", "osób", "zł", "all inclusive", "24.09.2026"]):
                    print(line[:700])
            d.back()
            WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
            time.sleep(3)

        d.save_screenshot("rainbow-family.png")
    finally:
        d.quit()
if __name__=="__main__": main()
