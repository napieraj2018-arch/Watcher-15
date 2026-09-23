import json, os, re, time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select, WebDriverWait

def compact(s): return " ".join((s or "").split())

def driver():
    o=Options()
    o.add_argument("--headless=new"); o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage"); o.add_argument("--window-size=1440,3000")
    o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs", {"performance":"ALL"})
    return webdriver.Chrome(options=o)

def dismiss(d):
    for t in ["Nie zezwalaj","Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","Zezwól na wszystkie","OK"]:
        try:
            xs=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
            if xs and xs[0].is_displayed():
                d.execute_script("arguments[0].click();",xs[0]); time.sleep(.4); return
        except: pass

def dump_network(d, label):
    print("NETWORK",label)
    seen=set()
    for e in d.get_log("performance"):
        try:
            msg=json.loads(e["message"])["message"]
            if msg["method"]!="Network.requestWillBeSent": continue
            u=msg["params"]["request"]["url"]
            low=u.lower()
            if u in seen: continue
            seen.add(u)
            if any(k in low for k in ["child","children","adult","occup","passenger","person","age","wiek","kc1","ac1","ic1","search","offer","trip"]):
                print(u[:3000])
        except: pass

def exim():
    d=driver()
    try:
        d.get("https://www.exim.pl/last-minute")
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(4);dismiss(d)
        d.get_log("performance")
        # participants -> family 2+2 -> exact ages
        btn=d.find_element(By.XPATH,"//button[contains(normalize-space(.),'Liczba uczestników')]")
        d.execute_script("arguments[0].click();",btn);time.sleep(.5)
        fam=[x for x in d.find_elements(By.TAG_NAME,"button") if x.is_displayed() and "Rodzina 2+2" in compact(x.text)]
        if fam: d.execute_script("arguments[0].click();",fam[0]);time.sleep(.8)
        age_buttons=[b for b in d.find_elements(By.XPATH,"//button[.//div[contains(@class,'f_input-item-value')]]") if b.is_displayed() and ("lat" in compact(b.text).lower() or "poniżej" in compact(b.text).lower())]
        for idx,target in enumerate(["5 lat","7 lat"]):
            age_buttons=[b for b in d.find_elements(By.XPATH,"//button[.//div[contains(@class,'f_input-item-value')]]") if b.is_displayed() and ("lat" in compact(b.text).lower() or "poniżej" in compact(b.text).lower())]
            if idx < len(age_buttons):
                d.execute_script("arguments[0].click();",age_buttons[idx]);time.sleep(.3)
                opts=[b for b in d.find_elements(By.TAG_NAME,"button") if b.is_displayed() and compact(b.text).lower()==target]
                if opts: d.execute_script("arguments[0].click();",opts[-1]);time.sleep(.4)
        # press search
        xs=[b for b in d.find_elements(By.TAG_NAME,"button") if b.is_displayed() and compact(b.text).upper()=="SZUKAJ"]
        if xs: d.execute_script("arguments[0].click();",xs[0]);time.sleep(7)
        print("EXIM_STATE",d.current_url)
        print("EXIM_PARTY",[compact(b.text) for b in d.find_elements(By.TAG_NAME,"button") if b.is_displayed() and "Liczba uczestników" in compact(b.text)][:3])
        dump_network(d,"EXIM")
        src=d.page_source
        print("EXIM_SOURCE_MATCHES")
        for pat in [r'.{0,160}AC1.{0,260}',r'.{0,160}KC1.{0,260}',r'.{0,160}IC1.{0,260}',r'.{0,160}(?:child|children|age|wiek).{0,260}']:
            for m in re.finditer(pat,src,re.I|re.S):
                print(compact(m.group(0))[:1000])
                break
    finally:d.quit()

def travelplanet():
    d=driver()
    try:
        d.get("https://www.travelplanet.pl/wakacje/super-last-minute/")
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(4);dismiss(d)
        d.get_log("performance")
        box=d.find_element(By.CSS_SELECTOR,"[data-testid='sf-passengers-picker-textbox']")
        d.execute_script("arguments[0].click();",box);time.sleep(.6)
        label=d.find_element(By.XPATH,"//label[.//*[contains(normalize-space(.),'Liczba dzieci')] or contains(normalize-space(.),'Liczba dzieci')]")
        spinner=label.find_element(By.XPATH,"./ancestor::div[contains(@class,'i-textbox--numeric-spinner')][1]")
        plus=[b for b in spinner.find_elements(By.TAG_NAME,"button") if b.is_displayed()][-1]
        for _ in range(2): d.execute_script("arguments[0].click();",plus);time.sleep(.4)
        s1=d.find_element(By.CSS_SELECTOR,"select[name='child-1']")
        s2=d.find_element(By.CSS_SELECTOR,"select[name='child-2']")
        Select(s1).select_by_value("5");time.sleep(.4)
        Select(s2).select_by_value("7");time.sleep(.6)
        # try click outside and submit
        d.execute_script("arguments[0].click();",box);time.sleep(.5)
        submit=d.find_element(By.CSS_SELECTOR,"[data-testid='sf-submit-button']")
        d.execute_script("arguments[0].click();",submit);time.sleep(7)
        print("TP_STATE",d.current_url)
        dump_network(d,"TRAVELPLANET")
        src=d.page_source
        print("TP_SOURCE_MATCHES")
        for pat in [
          r'.{0,160}nl_occupancy.{0,400}',r'.{0,160}child-1.{0,400}',
          r'.{0,160}(?:child|children|age).{0,400}'
        ]:
            for m in re.finditer(pat,src,re.I|re.S):
                print(compact(m.group(0))[:1200]); break
    finally:d.quit()

def grecos():
    d=driver()
    try:
        d.get("https://www.grecos.pl/last-minute")
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5);dismiss(d)
        print("GRECOS_URL",d.current_url)
        dump_network(d,"GRECOS")
        src=d.page_source
        print("GRECOS_SOURCE_MATCHES")
        for pat in [
          r'.{0,180}Adults.{0,500}',r'.{0,180}Children.{0,500}',
          r'.{0,180}(?:childage|childrenage|ageofchild|childAge|wiek).{0,500}'
        ]:
            found=0
            for m in re.finditer(pat,src,re.I|re.S):
                print(compact(m.group(0))[:1400]);found+=1
                if found>=4:break
    finally:d.quit()

if __name__=="__main__":
    which=os.environ.get("DIAG_SOURCE","exim")
    {"exim":exim,"travelplanet":travelplanet,"grecos":grecos}[which]()
