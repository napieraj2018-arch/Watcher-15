import json,requests
from urllib.parse import urlencode

BASE='https://www.exim.pl'
H={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Referer':BASE+'/last-minute'}

def walk(obj,path='',depth=0):
    if depth>5:return
    if isinstance(obj,dict):
        for k,v in obj.items():
            p=f'{path}.{k}' if path else k
            kl=k.lower()
            if any(x in kl for x in ['depart','airport','fly','flight','source','city','local','price','total','adult','child','age','occup','board','meal','rating','hotel','date']):
                try: print('FIELD',p,repr(v)[:2500])
                except: pass
            walk(v,p,depth+1)
    elif isinstance(obj,list):
        for i,v in enumerate(obj[:25]): walk(v,f'{path}[{i}]',depth+1)

def fetch(path):
    u=BASE+path
    r=requests.get(u,headers=H,timeout=30)
    print('FETCH',u,'STATUS',r.status_code,'CT',r.headers.get('content-type'),'LEN',len(r.content))
    try:
        j=r.json(); print('TOP',type(j).__name__, list(j.keys()) if isinstance(j,dict) else f'len={len(j)}')
        walk(j)
        return j
    except Exception:
        print('TEXT',r.text[:5000]); return None

def main():
    fetch('/api/searchfilter/getallfilters?segmentcode=residential')
    fetch('/api/searchfilter/getfilter?segmentCode=residential')
    fetch('/api/searchapi/getlocal')
    q={'ac1':'2','kc1':'2','ka1':'5|7','dd':'2026-09-24','rd':'2026-09-26','nn':'5|6|7|8','tt':'1','to':'4401|1149|1862|1825|4382|4378|2854|3095|3850|4380|4381|3911','sc':'residential'}
    fetch('/api/searchapi/getsearchresult?'+urlencode(q))
if __name__=='__main__':main()
