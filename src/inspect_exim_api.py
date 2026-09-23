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
            if any(x in kl for x in ['depart','airport','fly','flight','source','city','local','price','total','adult','child','age','occup','board','meal','rating','review','hotel','date','star']):
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

def main():
    today=datetime.now(TZ).date()
    dd=today+timedelta(days=1)
    rd=today+timedelta(days=60)
    fetch('/api/searchfilter/getallfilters?segmentcode=residential')
    fetch('/api/searchfilter/getfilter?segmentCode=residential')
    fetch('/api/searchapi/getlocal')
    q={'ac1':'2','kc1':'2','ka1':'5|7','dd':dd.isoformat(),'rd':rd.isoformat(),'nn':'7|8|9|10','tt':'1','to':'3850|4380|4381','sc':'residential'}
    print('EXIM_QUERY_PARTY',{'adults':2,'children':2,'ages':[5,7],'dd':dd.isoformat(),'rd':rd.isoformat()})
    j=fetch('/api/searchapi/getsearchresult?'+urlencode(q))
    if isinstance(j,dict):
        print('TOURS_COUNT',j.get('toursCount'))
        tours=j.get('tours') or []
        print('TOURS_LEN',len(tours) if isinstance(tours,list) else type(tours).__name__)
        if isinstance(tours,list):
            for idx,t in enumerate(tours[:10]):
                print('TOUR_SAMPLE',idx,json.dumps(t,ensure_ascii=False)[:18000])
if __name__=='__main__':main()
