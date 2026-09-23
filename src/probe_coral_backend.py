import json,re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin,urlparse

UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL,pl;q=0.9"}
PAGES=[
 "https://www.coraltravel.pl/tours/radom/turcja/obagol/",
 "https://www.coraltravel.pl/tours/radom/turcja/",
 "https://www.coraltravel.pl/tours/warszawa/turcja/",
 "https://booking.coraltravel.pl/"
]
TERMS=["child","children","wiek","age","adult","participant","person","total","całkow","price","tour","search","offer","api","graphql","filter","booking","pax"]

def compact(s): return re.sub(r"\s+"," ",s or "").strip()

def snippets(text,term,limit=4,r=900):
    out=[];lo=text.lower();t=term.lower();p=0
    while len(out)<limit:
        i=lo.find(t,p)
        if i<0:break
        sn=compact(text[max(0,i-r):min(len(text),i+len(t)+r)])
        if sn and sn not in out:out.append(sn)
        p=i+len(t)
    return out

def inspect_page(url):
    r=requests.get(url,headers=UA,timeout=35,allow_redirects=True)
    print("CORALBACK_PAGE",r.status_code,r.url,len(r.content),r.headers.get("content-type"))
    txt=r.text
    soup=BeautifulSoup(txt,"html.parser")
    print("CORALBACK_TITLE",compact(soup.title.get_text(" ",strip=True) if soup.title else ""))
    # Forms/controls can expose exact occupancy parameter names even when JS UI fails headless.
    for i,f in enumerate(soup.find_all("form")[:30]):
        fields=[]
        for e in f.find_all(["input","select","button"]):
            rec={k:e.get(k) for k in ["name","id","type","value","placeholder","aria-label"]}
            rec["tag"]=e.name
            rec["text"]=compact(e.get_text(" ",strip=True))[:140]
            blob=json.dumps(rec,ensure_ascii=False).lower()
            if any(t in blob for t in TERMS): fields.append(rec)
        if fields:
            print("CORALBACK_FORM",i,f.get("method"),urljoin(r.url,f.get("action") or ""),json.dumps(fields[:80],ensure_ascii=False))
    for s in soup.find_all("script"):
        if s.get("src"):continue
        body=s.string or s.get_text(" ",strip=True) or ""
        if any(t in body.lower() for t in TERMS):
            print("CORALBACK_INLINE",compact(body)[:9000])
    scripts=[]
    for s in soup.find_all("script",src=True):
        u=urljoin(r.url,s["src"])
        if u not in scripts:scripts.append(u)
    print("CORALBACK_SCRIPT_COUNT",len(scripts))
    return scripts

def inspect_scripts(urls):
    seen=set()
    queue=list(urls)
    n=0
    while queue and n<50:
        u=queue.pop(0)
        if u in seen:continue
        seen.add(u);n+=1
        try:
            r=requests.get(u,headers=UA,timeout=25)
            ct=(r.headers.get("content-type") or "").lower()
            if r.status_code!=200 or len(r.content)>4500000 or ("javascript" not in ct and not u.split("?")[0].endswith(".js")):
                continue
            t=r.text;lo=t.lower()
            hits=[x for x in TERMS if x in lo]
            if not hits:continue
            print("CORALBACK_JS",u,len(t),hits)
            # Print URL-like literals first; these often reveal the real search backend.
            lits=sorted(set(re.findall(r'["\']([^"\']{1,500})["\']',t)))
            for v in lits:
                lv=v.lower()
                if any(k in lv for k in ["/api","search","tour","offer","price","booking","graphql"]) and not v.startswith("data:"):
                    print("CORALBACK_LITERAL",u,v[:1200])
            for h in hits[:10]:
                for sn in snippets(t,h,limit=2):
                    print("CORALBACK_SNIP",h,sn[:4200])
            # Crawl local chunk references.
            for m in re.findall(r'["\']([^"\']+\.js(?:\?[^"\']*)?)["\']',t):
                nu=urljoin(u,m)
                if urlparse(nu).netloc.endswith("coraltravel.pl") and nu not in seen and nu not in queue:
                    queue.append(nu)
        except Exception as e:
            print("CORALBACK_JS_ERR",u,type(e).__name__,str(e)[:180])
    print("CORALBACK_JS_DONE",len(seen))

def main():
    allscripts=[]
    for p in PAGES:
        try:
            for u in inspect_page(p):
                if u not in allscripts:allscripts.append(u)
        except Exception as e:
            print("CORALBACK_PAGE_ERR",p,type(e).__name__,str(e)[:220])
    inspect_scripts(allscripts)

if __name__=="__main__":main()
