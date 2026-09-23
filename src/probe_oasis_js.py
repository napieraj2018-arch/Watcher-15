import re,requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

BASE='https://oasis.pl/'
UA={'User-Agent':'Mozilla/5.0'}
r=requests.get(BASE,headers=UA,timeout=30)
print('OASIS_JS_PAGE',r.status_code,r.url,len(r.content))
r.raise_for_status()
soup=BeautifulSoup(r.text,'html.parser')
scripts=[]
for s in soup.find_all('script',src=True):
    u=urljoin(r.url,s['src'])
    if u not in scripts:scripts.append(u)
print('OASIS_JS_COUNT',len(scripts))
terms=['children','child','childage','childAge','age','ages','adults','participants','passengers','search-search','numOnPage']
for u in scripts:
    if '_next/static/' not in u: continue
    try:
        rr=requests.get(u,headers=UA,timeout=25)
        if rr.status_code!=200 or len(rr.content)>4000000: continue
        text=rr.text
        hits=[t for t in terms if t.lower() in text.lower()]
        if not hits: continue
        print('OASIS_JS_FILE',u,len(text),hits)
        low=text.lower()
        for term in hits:
            pos=0
            for _ in range(4):
                i=low.find(term.lower(),pos)
                if i<0: break
                snip=re.sub(r'\s+',' ',text[max(0,i-700):min(len(text),i+1800)])
                print('OASIS_JS_SNIP',term,snip[:2600])
                pos=i+len(term)
    except Exception as e:
        print('OASIS_JS_ERR',u,type(e).__name__,str(e)[:160])
