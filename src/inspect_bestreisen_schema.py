import re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE="https://bestreisengroup.pl/wyniki-wyszukiwania"
UA={"User-Agent":"Mozilla/5.0","Accept-Language":"pl-PL,pl;q=0.9"}
TERMS=["search-search","trip-calculation","searchrooms","childage","infants","customertotalprice","totalprice","startdate","startdateto","transporttypeid","maintenance","length"]

def snips(text,term,limit=8,r=1400):
    out=[];lo=text.lower();n=term.lower();p=0
    while len(out)<limit:
        i=lo.find(n,p)
        if i<0:break
        s=re.sub(r"\s+"," ",text[max(0,i-r):min(len(text),i+len(n)+r)])
        if s not in out:out.append(s)
        p=i+len(n)
    return out

r=requests.get(BASE,headers=UA,timeout=30)
print("BESTSCHEMA_PAGE",r.status_code,len(r.content),r.url)
r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
queue=[]
for s in soup.find_all("script",src=True):
    u=urljoin(r.url,s["src"])
    if u not in queue:queue.append(u)
seen=set()
while queue and len(seen)<80:
    u=queue.pop(0)
    if u in seen:continue
    seen.add(u)
    try:
        rr=requests.get(u,headers=UA,timeout=30)
        if rr.status_code!=200 or len(rr.content)>6000000:continue
        t=rr.text
        hits=[x for x in TERMS if x.lower() in t.lower()]
        if hits:
            print("BESTSCHEMA_FILE",u,"LEN",len(t),"HITS",hits)
            for h in hits:
                for s in snips(t,h):
                    print("BESTSCHEMA_SNIP",h,s[:5200])
        for m in re.findall(r'["\']([^"\']+\.js)["\']',t):
            nu=urljoin(u,m)
            if "bestreisengroup.pl" in nu and nu not in seen and nu not in queue:queue.append(nu)
    except Exception as e:
        print("BESTSCHEMA_ERR",u,type(e).__name__,str(e)[:180])
print("BESTSCHEMA_DONE",len(seen))
