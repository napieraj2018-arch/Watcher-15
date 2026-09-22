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
        d.save_screenshot("rainbow-family.png")
    finally:
        d.quit()
if __name__=="__main__": main()
