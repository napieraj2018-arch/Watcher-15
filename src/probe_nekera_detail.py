import re,requests
from urllib.parse import urljoin,urlsplit,parse_qsl,urlencode,urlunsplit
from bs4 import BeautifulSoup

BASE="https://www.nekera.pl/hotels/"
FAMILY=[("adults","2"),("child","2021-01-01"),("child","2019-01-01"),("product","F")]
ADULTS=[("adults","2"),("product","F")]
HEAD={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL"}

def compact(s): return " ".join((s or "").split())

def with_party(url,party):
    p=urlsplit(urljoin(BASE,url));q=parse_qsl(p.query,keep_blank_values=True)
    q=[(k,v) for k,v in q if k not in {"adults","child","product","pricetype"}]
    q+=party
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q,doseq=True),p.fragment))

def explicit_totals(text):
    pats=[
      r"(?:cena\s*(?:całkowita|razem|łączna|końcowa)|do\s*zapłaty|razem|za\s*wszystkich)\D{0,100}(\d[\d .]{2,})\s*zł",
      r"(\d[\d .]{2,})\s*zł\D{0,80}(?:razem|łącznie|za\s*wszystkich|do\s*zapłaty)",
    ]
    out=[]
    for pat in pats:
        for m in re.findall(pat,text,re.I):
            n=re.sub(r"\D","",m)
            if n:
                v=int(n)
                if v not in out:out.append(v)
    return out

def exact_family_state(url,text):
    q=parse_qsl(urlsplit(url).query,keep_blank_values=True)
    children=[v for k,v in q if k=="child"]
    return (("adults","2") in q and sorted(children)==["2019-01-01","2021-01-01"]) or (
        "2021-01-01" in text and "2019-01-01" in text
    )

def inspect(url,label):
    r=requests.get(url,headers=HEAD,timeout=35,allow_redirects=True)
    print("NEKERA_OFFER_FETCH",label,r.status_code,r.url,len(r.content))
    if r.status_code!=200:return None
    s=BeautifulSoup(r.text,"html.parser");text=compact(s.get_text(" ",strip=True))
    totals=explicit_totals(text)
    print("NEKERA_OFFER_EXACT_STATE",label,exact_family_state(r.url,text))
    print("NEKERA_OFFER_TOTALS",label,totals[:20])
    for needle in ["2 doros","2 dzieci","2021-01-01","2019-01-01","za wszystkich","razem","do zapłaty","dostępn","rezerw","all inclusive"]:
        i=text.lower().find(needle.lower())
        if i>=0:print("NEKERA_OFFER_SIGNAL",label,needle,text[max(0,i-260):i+900])
    for form in s.find_all("form"):
        html=compact(str(form))
        if any(k in html.lower() for k in ["rezerw","booking","adult","child","price","offer"]):
            print("NEKERA_OFFER_FORM",label,html[:9000])
    for a in s.find_all("a",href=True):
        blob=(compact(a.get_text(" ",strip=True))+" "+a.get("href","")).lower()
        if any(k in blob for k in ["rezerw","book","sprawdź cen","sprawdz cen","wybierz ofert"]):
            print("NEKERA_OFFER_ACTION",label,urljoin(r.url,a.get("href","")),compact(a.get_text(" ",strip=True))[:500])
    return {"url":r.url,"totals":totals,"text":text}

r=requests.get(BASE,params=FAMILY,headers=HEAD,timeout=35)
print("NEKERA_LIST_STATUS",r.status_code,r.url,len(r.content));r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
anchors=[]
for a in soup.find_all("a",href=True):
    txt=compact(a.get_text(" ",strip=True));u=urljoin(r.url,a.get("href", ""));p=urlsplit(u)
    if "szczegó" not in txt.lower():continue
    if p.netloc not in {"www.nekera.pl","nekera.pl"}:continue
    if not p.path.startswith("/offers/"):continue
    if u not in [x[0] for x in anchors]:anchors.append((u,txt))
print("NEKERA_REAL_OFFER_ANCHORS",len(anchors))
for i,(u,txt) in enumerate(anchors[:8]):print("NEKERA_REAL_OFFER",i,u,txt)

party_sensitive=0;compared=0;family_total_rows=0
for i,(native,txt) in enumerate(anchors[:6]):
    family_url=with_party(native,FAMILY);adult_url=with_party(native,ADULTS)
    fam=inspect(family_url,f"FAMILY-{i}")
    ad=inspect(adult_url,f"ADULTS-{i}")
    if not fam or not ad:continue
    if fam["totals"]:family_total_rows+=1
    if fam["totals"] and ad["totals"]:
        compared+=1
        different=fam["totals"]!=ad["totals"]
        party_sensitive+=int(different)
        print("NEKERA_OFFER_COMPARE",i,{"family":fam["totals"],"adults":ad["totals"],"different":different,"native":native})
print("NEKERA_OFFER_FAMILY_TOTAL_ROWS",family_total_rows)
print("NEKERA_OFFER_COMPARE_COUNT",compared)
print("NEKERA_OFFER_PARTY_SENSITIVE_COUNT",party_sensitive)
print("NEKERA_OFFER_FAMILY_TOTAL_VERIFIED",party_sensitive>0)


# Browser-level detail repricing. The detail page does not honor child query
# parameters until its own passenger chooser is updated, so verify the actual
# offer calculator instead of trusting URL state.
def browser_reprice(native,label):
    import time,json
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--window-size=1440,3200");o.add_argument("--lang=pl-PL")
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        adult_url=with_party(native,ADULTS)
        d.get(adult_url);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5)
        body0=" ".join(d.find_element(By.TAG_NAME,"body").text.split())
        before=explicit_totals(body0)
        print("NEKERA_UI_REPRICE_BEFORE",label,{"url":d.current_url,"totals":before})
        btns=[x for x in d.find_elements(By.CSS_SELECTOR,".offer_chooser__passengers_button") if x.is_displayed()]
        if not btns:
            print("NEKERA_UI_REPRICE_FAIL",label,"no passenger button");return
        d.execute_script("arguments[0].click()",btns[0]);time.sleep(.7)
        child_count=d.find_element(By.ID,"children-input")
        add=d.find_element(By.ID,"child-add")
        for _ in range(4):
            try:
                n=int(child_count.get_attribute("value") or "0")
            except:n=0
            if n>=2:break
            d.execute_script("arguments[0].click()",add);time.sleep(.4)
        print("NEKERA_UI_CHILD_COUNT",label,child_count.get_attribute("value"))
        for eid,val in [("child_1","2021-01-01"),("child_2","2019-01-01")]:
            e=d.find_element(By.ID,eid)
            d.execute_script("""
              const e=arguments[0],v=arguments[1];
              const p=Object.getPrototypeOf(e),desc=Object.getOwnPropertyDescriptor(p,'value');
              if(desc&&desc.set)desc.set.call(e,v);else e.value=v;
              for(const n of ['input','change','blur'])e.dispatchEvent(new Event(n,{bubbles:true}));
            """,e,val)
            time.sleep(.3)
            print("NEKERA_UI_CHILD_DOB",label,eid,e.get_attribute("value"))
        updates=[x for x in d.find_elements(By.CSS_SELECTOR,".offer_chooser_update_button") if x.is_displayed()]
        if not updates:
            print("NEKERA_UI_REPRICE_FAIL",label,"no update button");return
        d.get_log("performance")
        d.execute_script("arguments[0].click()",updates[0]);time.sleep(8)
        body=" ".join(d.find_element(By.TAG_NAME,"body").text.split())
        after=explicit_totals(body)
        print("NEKERA_UI_REPRICE_AFTER",label,{"url":d.current_url,"totals":after,
          "two_children":"2 dzieci" in body.lower(),
          "dob1":"2021-01-01" in body,"dob2":"2019-01-01" in body,
          "unavailable":"oferta chwilowo niedostępna" in body.lower()})
        for needle in ["2 dzieci","Dziecko","Razem","do zapłaty","Dostępna","niedostępna"]:
            i=body.lower().find(needle.lower())
            if i>=0:print("NEKERA_UI_SIGNAL",label,needle,body[max(0,i-250):i+900])
        for row in d.get_log("performance"):
            try:
                m=json.loads(row["message"])["message"]
                if m.get("method")!="Network.requestWillBeSent":continue
                req=m["params"]["request"];u=req.get("url","");post=req.get("postData") or ""
                blob=(u+" "+post).lower()
                if any(k in blob for k in ["child","passenger","offer","price","booking"]):
                    print("NEKERA_UI_REQ",label,req.get("method"),u[:5000],"POST",post[:5000])
            except:pass
        changed=bool(before and after and before!=after)
        print("NEKERA_UI_PARTY_SENSITIVE",label,changed)
    finally:d.quit()

for i,(native,_) in enumerate(anchors[:2]):
    try: browser_reprice(native,f"UI-{i}")
    except Exception as e: print("NEKERA_UI_REPRICE_ERR",i,type(e).__name__,str(e)[:300])
