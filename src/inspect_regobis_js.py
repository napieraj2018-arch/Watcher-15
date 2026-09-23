import re,requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

BASE="https://www.rego-bis.pl/rodzina2plus2"
UA={"User-Agent":"Mozilla/5.0","Accept-Language":"pl-PL,pl;q=0.9"}

def snippets(text,needle,limit=8,r=1200):
    out=[];lo=text.lower();n=needle.lower();p=0
    while len(out)<limit:
        i=lo.find(n,p)
        if i<0:break
        s=re.sub(r"\s+"," ",text[max(0,i-r):min(len(text),i+len(n)+r)])
        if s not in out:out.append(s)
        p=i+len(n)
    return out

r=requests.get(BASE,headers=UA,timeout=30);r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
urls=[]
for s in soup.find_all("script",src=True):
    u=urljoin(r.url,s["src"])
    if u not in urls:urls.append(u)
print("REGOJS_PAGE",r.status_code,len(r.content),"SCRIPTS",len(urls))
terms=["SearchParticipants","child","children","birth","urodz","age","adult","participants","guest","search-option","offer","api/","/api","filters"]
seen=set()
queue=list(urls)
while queue and len(seen)<60:
    u=queue.pop(0)
    if u in seen or "/build/assets/" not in u:continue
    seen.add(u)
    try:
        rr=requests.get(u,headers=UA,timeout=25)
        if rr.status_code!=200 or len(rr.content)>4500000:continue
        t=rr.text
        hits=[x for x in terms if x.lower() in t.lower()]
        if hits:
            print("REGOJS_FILE",u,"LEN",len(t),"HITS",hits)
            for h in hits:
                for s in snippets(t,h,limit=4):
                    print("REGOJS_SNIP",h,s[:5000])
        for m in re.findall(r'["\'](\.?/?[^"\']+\.js)["\']',t):
            nu=urljoin(u,m)
            if "/build/assets/" in nu and nu not in seen and nu not in queue:queue.append(nu)
    except Exception as e:
        print("REGOJS_ERR",u,type(e).__name__,str(e)[:180])
print("REGOJS_DONE",len(seen))
