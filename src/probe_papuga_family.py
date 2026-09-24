import json,re,time
from urllib.parse import urlsplit
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select,WebDriverWait

BASE="https://wczasy.wakacyjnapapuga.pl/"

def compact(s): return " ".join((s or "").split())
def chrome():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,4200","--lang=pl-PL"]:
        o.add_argument(a)
    return webdriver.Chrome(options=o)
def cookies(d):
    for t in ["Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","OK"]:
        try:
            xs=[x for x in d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]") if x.is_displayed()]
            if xs:d.execute_script("arguments[0].click()",xs[0]);time.sleep(.4);return
        except:pass

def party(d,fam):
    child=None
    for sel in ["#searchWindow_main_children","input[id*='children']"]:
        xs=[x for x in d.find_elements(By.CSS_SELECTOR,sel) if x.is_displayed()]
        if xs: child=xs[0];break
    print("PAP_CHILD_INPUT",bool(child),child.get_attribute("id") if child else None)
    if child:d.execute_script("arguments[0].click()",child);time.sleep(.4)
    sels=[x for x in d.find_elements(By.CSS_SELECTOR,"select[id*='chd_'],select[class*='children_select']") if x.is_displayed()]
    print("PAP_CHILD_SELECTS",[(x.get_attribute("id"),x.get_attribute("value")) for x in sels])
    ages=[5,7] if fam else []
    for i,s in enumerate(sels):
        try:
            Select(s).select_by_value(str(ages[i]) if i<len(ages) else "")
            d.execute_script("arguments[0].dispatchEvent(new Event('change',{bubbles:true}))",s)
        except Exception as e:print("PAP_AGE_ERR",i,type(e).__name__)
    time.sleep(.5)
    print("PAP_AGES",[x.get_attribute("value") for x in sels])
    return True

def search(d):
    for el in d.find_elements(By.XPATH,"//button|//input[@type='submit']"):
        try:
            txt=(compact(el.text)+" "+(el.get_attribute("value") or "")).lower()
            if el.is_displayed() and "szukaj" in txt:
                d.execute_script("arguments[0].click()",el);return True
        except:pass
    return False

def list_links(d,label):
    body=d.find_element(By.TAG_NAME,"body").text
    print("PAP_RESULT_PARTY",label,"5lat",("5 lat" in body),"7lat",("7 lat" in body),"url",d.current_url)
    out={}
    for a in d.find_elements(By.TAG_NAME,"a"):
        try:
            href=a.get_attribute("href") or ""
            if "/ofr-" not in href:continue
            path=urlsplit(href).path
            txt=compact(a.text)
            if path not in out:
                out[path]={"href":href,"text":txt[:800]}
        except:pass
    print("PAP_LINK_COUNT",label,len(out))
    for k,x in list(out.items())[:20]:print("PAP_LINK",label,json.dumps({"key":k,**x},ensure_ascii=False))
    return out

def build(fam,label):
    d=chrome()
    try:
        d.get(BASE);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(4);cookies(d)
        party(d,fam);print("PAP_SEARCH",label,search(d));time.sleep(8)
        return list_links(d,label)
    finally:d.quit()

def detail(url,label):
    d=chrome()
    try:
        d.get(url);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5);cookies(d)
        body=d.find_element(By.TAG_NAME,"body").text
        m=re.search(r"Razem\s*:\s*([0-9][0-9 ]{2,})\s*zł",body,re.I)
        party_lines=[compact(x) for x in body.splitlines() if "Dorośli" in x or "Dzieci" in x]
        rec={"url":d.current_url,"total":int(m.group(1).replace(" ","")) if m else None,"party":party_lines[:10],"has5":("5 lat" in body),"has7":("7 lat" in body)}
        print("PAP_DETAIL",label,json.dumps(rec,ensure_ascii=False))
        return rec
    finally:d.quit()

def main():
    fam=build(True,"FAMILY");ad=build(False,"ADULTS")
    common=[k for k in fam if k in ad][:8]
    print("PAP_COMMON",len(common),common)
    proofs=[]
    for k in common:
        f=detail(fam[k]["href"],"FAMILY")
        a=detail(ad[k]["href"],"ADULTS")
        if f["total"] and a["total"] and f["total"]!=a["total"] and any("Dzieci" in x for x in f["party"]):
            p={"key":k,"family_total":f["total"],"adult_total":a["total"],"delta":f["total"]-a["total"],"family_url":f["url"]}
            proofs.append(p);print("PAP_PROOF",json.dumps(p,ensure_ascii=False))
            if len(proofs)>=3:break
    print("PAP_PARTY_SENSITIVE",len(proofs))
    print("PAP_FAMILY_TOTAL_VERIFIED",bool(proofs))

if __name__=="__main__":main()
