import re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE="https://www.primaholiday.pl/"
UA={"User-Agent":"Mozilla/5.0","Accept-Language":"pl-PL,pl;q=0.9"}
TERMS=["BluevendoFastCalculation","bluevendoFastCalculation","departureCity","departureDate","offerid","search","filters","tripid","graphql","children","child","adult","age","availability","maintenance","transport","period"]

def snips(text,term,limit=5,r=1400):
    out=[];lo=text.lower();needle=term.lower();p=0
    while len(out)<limit:
        i=lo.find(needle,p)
        if i<0:break
        s=re.sub(r"\s+"," ",text[max(0,i-r):min(len(text),i+len(term)+r)])
        if s not in out:out.append(s)
        p=i+len(term)
    return out

r=requests.get(BASE,headers=UA,timeout=30)
print("PRIMASCHEMA_PAGE",r.status_code,len(r.content),r.url)
r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
queue=[]
for s in soup.find_all("script",src=True):
    u=urljoin(r.url,s["src"])
    if u not in queue:queue.append(u)
print("PRIMASCHEMA_SCRIPT_COUNT",len(queue))
seen=set()
while queue and len(seen)<100:
    u=queue.pop(0)
    if u in seen:continue
    seen.add(u)
    try:
        rr=requests.get(u,headers=UA,timeout=30)
        if rr.status_code!=200 or len(rr.content)>6000000:continue
        t=rr.text
        ops=sorted(set(re.findall(r'operationName\s*[:=]\s*["\']([^"\']+)',t)))
        defs=sorted(set(re.findall(r'\b(?:query|mutation)\s+([A-Za-z_][A-Za-z0-9_]*)\s*[({]',t)))
        for op in ops[:160]:print("PRIMASCHEMA_OPERATION",u,op)
        for op in defs[:160]:print("PRIMASCHEMA_DEFINITION",u,op)
        hits=[x for x in TERMS if x.lower() in t.lower()]
        if hits:
            print("PRIMASCHEMA_FILE",u,"LEN",len(t),"HITS",hits)
            for h in hits:
                for s in snips(t,h):print("PRIMASCHEMA_SNIP",h,s[:5200])
        for m in re.findall(r'["\']([^"\']+\.js)["\']',t):
            nu=urljoin(u,m)
            if "primaholiday.pl" in nu and nu not in seen and nu not in queue:queue.append(nu)
    except Exception as e:
        print("PRIMASCHEMA_ERR",u,type(e).__name__,str(e)[:180])
print("PRIMASCHEMA_DONE",len(seen))
