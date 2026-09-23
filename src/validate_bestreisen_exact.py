import json,re,time
from urllib.parse import urlencode,urlsplit,parse_qs
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://bestreisengroup.pl/hotel/hiszpania/costa-brava/hotel-bluesea-montevista-hawai"
COMMON={"ad":"2","hid":"18290","ids":"789655192_2039328_2039305_1332477"}

def compact(s): return " ".join((s or "").split())

def load(d,label,extra):
    q=dict(COMMON);q.update(extra)
    url=BASE+"?"+urlencode(q,doseq=True)
    d.get(url);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(6)
    print("BEST_URL",label,d.current_url)
    body=d.find_element(By.TAG_NAME,"body").text
    lines=[x.strip() for x in body.splitlines() if x.strip()]
    signals=[]
    for line in lines:
        lo=line.lower()
        if any(k in lo for k in ["doros","dzieci","wiek","cena za osob","całkowita","calkowita","razem","pln","all inclusive","dostęp","wylot"]):
            signals.append(line)
            print("BEST_SIGNAL",label,line[:900])
    totals=[]
    for pat in [
      r"Całkowita\s*([0-9][0-9\s.]*)\s*PLN",
      r"Calkowita\s*([0-9][0-9\s.]*)\s*PLN",
      r"(?:Razem|Cena razem)\s*([0-9][0-9\s.]*)\s*PLN"
    ]:
        for m in re.findall(pat,body,re.I):
            n=re.sub(r"\D","",m)
            if n:totals.append(int(n))
    party=[x for x in signals if "doros" in x.lower() or "dzieci" in x.lower() or "wiek" in x.lower()]
    print("BEST_SUMMARY",label,json.dumps({
      "query":parse_qs(urlsplit(d.current_url).query),
      "party":party[:20],"totals":totals[:20]
    },ensure_ascii=False))
    return {"url":d.current_url,"body":body,"totals":totals,"party":party}

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3400","--lang=pl-PL"]:o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        base=load(d,"ADULTS",{"ch":""})
        variants=[
          ("COMMA",{"ch":"5,7"}),("PIPE",{"ch":"5|7"}),("DASH",{"ch":"5-7"}),
          ("ARRAY",{"ch":["5","7"]}),("AGES",{"ch":"5;7"})
        ]
        for label,q in variants:
            load(d,label,q)
        # Inspect controls and relevant requests on the final rendered detail.
        for e in d.find_elements(By.XPATH,"//input|//select|//button|//*[@role='button']|//*[@role='combobox']"):
            try:
                txt=compact(e.text)
                blob=" ".join(filter(None,[txt,e.get_attribute("name"),e.get_attribute("id"),e.get_attribute("placeholder"),e.get_attribute("aria-label"),e.get_attribute("class"),e.get_attribute("value")]))
                if any(k in blob.lower() for k in ["doros","dziec","dzieci","wiek","adult","child","age","guest","osob"]):
                    print("BEST_CTRL",json.dumps({"tag":e.tag_name,"text":txt[:400],"name":e.get_attribute("name"),"id":e.get_attribute("id"),"value":e.get_attribute("value"),"aria":e.get_attribute("aria-label"),"placeholder":e.get_attribute("placeholder"),"class":e.get_attribute("class"),"html":compact(e.get_attribute("outerHTML"))[:2800]},ensure_ascii=False))
            except:pass
        seen=set()
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or "";blob=(u+" "+post).lower()
                if "bestreisengroup.pl" in u and any(k in blob for k in ["search","offer","adult","child","age","price","hotel"]):
                    if (u,post) not in seen:
                        seen.add((u,post));print("BEST_REQ",req.get("method"),u[:5000],"POST",post[:5000])
            except:pass
        print("BEST_REQ_COUNT",len(seen))
    finally:d.quit()

if __name__=="__main__":main()
