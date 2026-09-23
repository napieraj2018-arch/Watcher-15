import re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE="https://www.primaholiday.pl/"
UA={"User-Agent":"Mozilla/5.0","Accept-Language":"pl-PL,pl;q=0.9"}

r=requests.get(BASE,headers=UA,timeout=30);r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
queue=[urljoin(r.url,s["src"]) for s in soup.find_all("script",src=True)]
seen=set()
while queue and len(seen)<100:
    u=queue.pop(0)
    if u in seen: continue
    seen.add(u)
    try:
        rr=requests.get(u,headers=UA,timeout=25)
        if rr.status_code!=200 or len(rr.content)>6000000: continue
        t=rr.text
        low=t.lower()
        for needle in ["qapitoken","getoffers","qapi","authorization","token"]:
            pos=0;n=0
            while n<12:
                i=low.find(needle.lower(),pos)
                if i<0:break
                sn=re.sub(r"\s+"," ",t[max(0,i-2200):min(len(t),i+4200)])
                print("PRIMATOKEN_SNIP",needle,u,sn[:6500])
                pos=i+len(needle);n+=1
        for m in re.findall(r'["\']([^"\']+\.js)["\']',t):
            nu=urljoin(u,m)
            if "primaholiday.pl" in nu and nu not in seen and nu not in queue:queue.append(nu)
    except Exception as e:
        print("PRIMATOKEN_ERR",u,type(e).__name__,str(e)[:180])
print("PRIMATOKEN_DONE",len(seen))
