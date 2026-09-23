import os,re,requests
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
 "searchbar","search","offer","booking",
]
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36"}

def snippets(text,term,radius=500,limit=8):
 out=[]
 low=text.lower(); t=term.lower(); start=0
 while len(out)<limit:
  i=low.find(t,start)
  if i<0:break
  s=re.sub(r"\s+"," ",text[max(0,i-radius):min(len(text),i+len(term)+radius)])
  if s not in out:out.append(s)
  start=i+len(term)
 return out

def main():
 cid=os.environ["CHANNEL_ID"]; url=SOURCES[cid]
 r=requests.get(url,headers=UA,timeout=35);print("JS_PAGE",cid,r.status_code,r.url,len(r.content))
 r.raise_for_status(); soup=BeautifulSoup(r.text,"html.parser")
 scripts=[]
 for s in soup.find_all("script"):
  src=s.get("src")
  if src:
   u=urljoin(r.url,src)
   if u not in scripts:scripts.append(u)
 print("JS_SCRIPT_COUNT",len(scripts))
 scored=[]
 for u in scripts:
  lu=u.lower()
  score=sum(1 for x in ["search","offer","booking","app","main","chunk","form","filter"] if x in lu)
  if cid=="nekera_pl" and any(x in lu for x in ["searchbar","offercollection"]):score+=20
  if cid=="fly_pl" and any(x in lu for x in ["live-search","edit-result-search","app.global","form.js"]):score+=20
  if cid=="oasis_pl" and "_next/static/chunks" in lu:score+=3
  scored.append((score,u))
 for _,u in sorted(scored,reverse=True)[:30]:
  try:
   rr=requests.get(u,headers=UA,timeout=25)
   if rr.status_code!=200 or len(rr.content)>4_000_000:continue
   text=rr.text
   hits=[]
   for term in TERMS:
    if term.lower() in text.lower():hits.append(term)
   if not hits:continue
   print("JS_FILE",u,"LEN",len(text),"HITS",hits)
   for term in hits:
    for s in snippets(text,term,limit=3):
     print("JS_SNIP",term,s[:2200])
  except Exception as e:print("JS_ERR",u,type(e).__name__,str(e)[:180])

if __name__=="__main__":main()
