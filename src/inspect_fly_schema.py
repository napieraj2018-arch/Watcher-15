import re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE="https://fly.pl/szukaj-wycieczek/"
UA={"User-Agent":"Mozilla/5.0","Accept-Language":"pl-PL"}

r=requests.get(BASE,headers=UA,timeout=30)
print("FLY_SCHEMA_PAGE",r.status_code,len(r.content),r.url)
r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
urls=[]
for s in soup.find_all("script"):
    src=s.get("src")
    if src:
        u=urljoin(r.url,src)
        if "fly.pl" in u and u not in urls: urls.append(u)
print("FLY_SCHEMA_SCRIPT_COUNT",len(urls))

terms=["data-childlist","filter[child]","data-counter","childlist","childAge","child_age","birthday","birth","data urodzenia","children"]
def snippets(text,needle,radius=850,limit=8):
    out=[];lo=text.lower();q=needle.lower();p=0
    while len(out)<limit:
        i=lo.find(q,p)
        if i<0:break
        s=re.sub(r"\s+"," ",text[max(0,i-radius):min(len(text),i+len(q)+radius)])
        if s not in out:out.append(s)
        p=i+len(q)
    return out

for u in urls:
    try:
        rr=requests.get(u,headers=UA,timeout=25)
        if rr.status_code!=200 or len(rr.content)>5000000:continue
        t=rr.text
        hits=[x for x in terms if x.lower() in t.lower()]
        if not hits:continue
        print("FLY_SCHEMA_FILE",u,"LEN",len(t),"HITS",hits)
        for h in hits:
            for s in snippets(t,h,limit=6):
                print("FLY_SCHEMA_SNIP",h,s[:3800])
    except Exception as e:print("FLY_SCHEMA_ERR",u,type(e).__name__,str(e)[:160])
