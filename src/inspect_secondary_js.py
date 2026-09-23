import os,re,requests
from collections import deque
from urllib.parse import urljoin
from bs4 import BeautifulSoup

SOURCES={
 "fly_pl":"https://fly.pl/szukaj-wycieczek/",
 "nekera_pl":"https://www.nekera.pl/",
 "oasis_pl":"https://oasis.pl/",
}
TERMS=[
 "filter[person]","adult","adults","child","children","kid","kids","age","birth",
 "dzieci","dziecko","doros","uczest","passenger","occupancy","room","persons",
 "searchbar","search","offer","booking","departure","price","total",
]
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36"}

def snippets(text,term,radius=650,limit=5):
 out=[]; low=text.lower(); t=term.lower(); start=0
 while len(out)<limit:
  i=low.find(t,start)
  if i<0: break
  s=re.sub(r"\s+"," ",text[max(0,i-radius):min(len(text),i+len(term)+radius)])
  if s not in out: out.append(s)
  start=i+len(term)
 return out

def imports(text,base):
 out=[]
 # ES modules: import ... from "./x.js", export ... from, import("./x.js"), import "./x.js"
 pats=[
  r'(?:from|import)\s*[\(]?\s*["\']([^"\']+\.js(?:\?[^"\']*)?)["\']',
  r'import\s+["\']([^"\']+\.js(?:\?[^"\']*)?)["\']',
 ]
 for pat in pats:
  for m in re.finditer(pat,text):
   raw=m.group(1)
   if raw.startswith(("http://","https://","/","./","../")):
    u=urljoin(base,raw)
    if u not in out: out.append(u)
 return out

def score_url(cid,u):
 lu=u.lower()
 score=sum(1 for x in ["search","offer","booking","app","main","chunk","form","filter"] if x in lu)
 if cid=="nekera_pl" and any(x in lu for x in ["searchbar","offercollection","searchbarbase","searchbarlisting"]): score+=25
 if cid=="fly_pl" and any(x in lu for x in ["live-search","edit-result-search","form","filter"]): score+=20
 if cid=="oasis_pl" and "_next/static/chunks" in lu: score+=3
 return score

def main():
 cid=os.environ["CHANNEL_ID"]; url=SOURCES[cid]
 r=requests.get(url,headers=UA,timeout=35)
 print("JS_PAGE",cid,r.status_code,r.url,len(r.content))
 r.raise_for_status(); soup=BeautifulSoup(r.text,"html.parser")
 roots=[]
 for s in soup.find_all("script"):
  src=s.get("src")
  if src:
   u=urljoin(r.url,src)
   if u not in roots: roots.append(u)
 print("JS_SCRIPT_COUNT",len(roots))

 # Crawl selected ES-module imports too. This matters especially for Nekera,
 # whose entry bundle imports the participant serializer from relative modules.
 q=deque(u for _,u in sorted(((score_url(cid,u),u) for u in roots),reverse=True)[:30])
 seen=set(); fetched=0; max_files=70
 while q and fetched<max_files:
  u=q.popleft()
  if u in seen: continue
  seen.add(u)
  try:
   rr=requests.get(u,headers=UA,timeout=25)
   print("JS_FETCH",rr.status_code,u,"LEN",len(rr.content))
   if rr.status_code!=200 or len(rr.content)>4_000_000: continue
   text=rr.text; fetched+=1
   deps=imports(text,u)
   if deps:
    print("JS_IMPORTS",u,len(deps),deps[:30])
    for dep in deps:
     if dep not in seen:q.append(dep)
   hits=[term for term in TERMS if term.lower() in text.lower()]
   if not hits: continue
   print("JS_FILE",u,"LEN",len(text),"HITS",hits)
   for term in hits:
    for s in snippets(text,term,limit=4):
     print("JS_SNIP",term,s[:2600])
  except Exception as e:
   print("JS_ERR",u,type(e).__name__,str(e)[:180])
 print("JS_CRAWL_DONE",cid,"FILES",fetched,"SEEN",len(seen))

if __name__=="__main__": main()
