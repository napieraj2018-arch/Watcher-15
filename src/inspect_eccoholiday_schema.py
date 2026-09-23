import re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE="https://www.eccoholiday.com/"
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL,pl;q=0.9"}
TERMS=["searchWindow_main_children","searchWindow_main_adults","childAge","childrenAge","children","child","wiek","age","adult","searchWindow","offer","price","api","ajax","wszystkich","priceClick","za osobę","za wszystkich"]

def compact(s):return re.sub(r"\s+"," ",s or "").strip()
def snippets(t,term,limit=6,r=1200):
    lo=t.lower();q=term.lower();p=0;out=[]
    while len(out)<limit:
        i=lo.find(q,p)
        if i<0:break
        s=compact(t[max(0,i-r):min(len(t),i+len(q)+r)])
        if s not in out:out.append(s)
        p=i+len(q)
    return out

def main():
    r=requests.get(BASE,headers=UA,timeout=35);print("ECCOSCHEMA_PAGE",r.status_code,r.url,len(r.content));r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    for s in soup.find_all("script"):
        if not s.get("src"):
            t=s.string or s.get_text(" ",strip=True) or ""
            if any(x.lower() in t.lower() for x in TERMS):
                print("ECCOSCHEMA_INLINE",compact(t)[:10000])
    urls=[]
    for s in soup.find_all("script",src=True):
        u=urljoin(r.url,s["src"])
        if u not in urls:urls.append(u)
    print("ECCOSCHEMA_SCRIPT_COUNT",len(urls))
    for u in urls[:100]:
        try:
            rr=requests.get(u,headers=UA,timeout=25)
            if rr.status_code!=200 or len(rr.content)>5000000:continue
            t=rr.text
            hits=[x for x in TERMS if x.lower() in t.lower()]
            if not hits:continue
            print("ECCOSCHEMA_FILE",u,len(t),hits)
            for h in hits:
                for sn in snippets(t,h,limit=4):
                    print("ECCOSCHEMA_SNIP",h,sn[:5000])
            for lit in sorted(set(re.findall(r'["\']([^"\']{1,500})["\']',t))):
                lo=lit.lower()
                if any(x in lo for x in ["ajax","api","offer","search","price"]) and not lit.startswith("data:"):
                    print("ECCOSCHEMA_LITERAL",u,lit[:1500])
        except Exception as ex:print("ECCOSCHEMA_ERR",u,type(ex).__name__,str(ex)[:200])

if __name__=="__main__":main()
