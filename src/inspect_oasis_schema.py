import re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE="https://oasis.pl/"
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL"}

def snippets(text,needle,r=900,limit=10):
 out=[];lo=text.lower();n=needle.lower();p=0
 while len(out)<limit:
  i=lo.find(n,p)
  if i<0:break
  s=re.sub(r"\s+"," ",text[max(0,i-r):min(len(text),i+len(n)+r)])
  if s not in out:out.append(s)
  p=i+len(n)
 return out

r=requests.get(BASE,headers=UA,timeout=30)
print("OASIS_SCHEMA_PAGE",r.status_code,len(r.content))
r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
urls=[]
for s in soup.find_all("script"):
 src=s.get("src")
 if src:
  u=urljoin(BASE,src)
  if u not in urls:urls.append(u)
print("OASIS_SCHEMA_SCRIPTS",len(urls))
for u in urls:
 try:
  rr=requests.get(u,headers=UA,timeout=25)
  if rr.status_code!=200 or len(rr.content)>5000000:continue
  t=rr.text
  hits=[x for x in ["search-search","adults","children","child","childage","age","participants","passengers","rooms","api-bv"] if x in t.lower()]
  if not hits:continue
  print("OASIS_SCHEMA_FILE",u,"LEN",len(t),"HITS",hits)
  for h in hits:
   for s in snippets(t,h,limit=5):print("OASIS_SCHEMA_SNIP",h,s[:3600])
 except Exception as e:print("OASIS_SCHEMA_ERR",u,type(e).__name__,str(e)[:160])
