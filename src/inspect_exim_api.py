import json,requests
from datetime import datetime,timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

BASE='https://www.exim.pl'
H={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Referer':BASE+'/last-minute'}
TZ=ZoneInfo('Europe/Warsaw')

def walk(obj,path='',depth=0):
    if depth>6:return
    if isinstance(obj,dict):
        for k,v in obj.items():
            p=f'{path}.{k}' if path else k
            kl=k.lower()
            if any(x in kl for x in ['depart','airport','fly','flight','source','city','local','price','total','adult','child','age','occup','board','meal','rating','review','hotel','date','star','url']):
                try: print('FIELD',p,repr(v)[:2500])
                except: pass
            walk(v,p,depth+1)
    elif isinstance(obj,list):
        for i,v in enumerate(obj[:40]): walk(v,f'{path}[{i}]',depth+1)

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

def run_query(label,q):
    print('EXIM_QUERY',label,q)
    j=fetch('/api/searchapi/getsearchresult?'+urlencode(q))
    if not isinstance(j,dict):return 0
    print('TOURS_COUNT',label,j.get('toursCount'))
    tours=j.get('tours') or []
    print('TOURS_LEN',label,len(tours) if isinstance(tours,list) else type(tours).__name__)
    if isinstance(tours,list):
        for idx,t in enumerate(tours[:8]):print('TOUR_SAMPLE',label,idx,json.dumps(t,ensure_ascii=False)[:20000])
    return len(tours) if isinstance(tours,list) else 0

def main():
    today=datetime.now(TZ).date(); dd=today+timedelta(days=1)
    filt=fetch('/api/searchfilter/getfilter?segmentCode=residential')
    if isinstance(filt,dict):
        print('SEARCH_RESULT_URL',repr(filt.get('searchResultUrl')))
        print('DEFAULT_FILTER',json.dumps(filt.get('defaultFilterApiResponseModel'),ensure_ascii=False)[:12000])
    base={'ac1':'2','kc1':'2','ka1':'5|7','dd':dd.isoformat(),'tt':'1','sc':'residential'}
    q1=base|{'rd':(today+timedelta(days=3)).isoformat(),'nn':'5|6|7|8','to':'3850|4380|4381'}
    n=run_query('WATCHER_WINDOW',q1)
    if not n:
        q2=base|{'rd':(today+timedelta(days=180)).isoformat(),'nn':'7|10'}
        n=run_query('BROAD_VALIDATION',q2)
    print('EXIM_ANY_EXACT_FAMILY_TOURS',bool(n))
if __name__=='__main__':main()
