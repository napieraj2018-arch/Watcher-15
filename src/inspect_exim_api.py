import json,requests
from datetime import datetime,timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

BASE='https://www.exim.pl'
H={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Referer':BASE+'/last-minute'}
TZ=ZoneInfo('Europe/Warsaw')

def walk(obj,path='',depth=0):
    if depth>5:return
    if isinstance(obj,dict):
        for k,v in obj.items():
            p=f'{path}.{k}' if path else k;kl=k.lower()
            if any(x in kl for x in ['price','total','adult','child','age','occup','board','meal','rating','review','hotel','date','star','url','airport']):
                try:print('FIELD',p,repr(v)[:2500])
                except:pass
            walk(v,p,depth+1)
    elif isinstance(obj,list):
        for i,v in enumerate(obj[:25]):walk(v,f'{path}[{i}]',depth+1)

def fetch_json(path):
    u=BASE+path;r=requests.get(u,headers=H,timeout=30)
    print('FETCH',u,'STATUS',r.status_code,'LEN',len(r.content))
    try:return r.json()
    except Exception:print('TEXT',r.text[:3000]);return None

def run_query(label,q):
    print('EXIM_QUERY',label,q)
    j=fetch_json('/api/searchapi/getsearchresult?'+urlencode(q))
    if not isinstance(j,dict):return 0,None
    print('TOURS_COUNT',label,j.get('toursCount'),'DEST_COUNT',j.get('destinationsCount'))
    tours=j.get('tours') or [];print('TOURS_LEN',label,len(tours) if isinstance(tours,list) else type(tours).__name__)
    if isinstance(tours,list):
        for idx,t in enumerate(tours[:10]):
            print('TOUR_SAMPLE',label,idx,json.dumps(t,ensure_ascii=False)[:24000]);walk(t,f'tour[{idx}]')
    return (len(tours) if isinstance(tours,list) else 0),j

def main():
    today=datetime.now(TZ).date();dd=today
    filt=fetch_json('/api/searchfilter/getfilter?segmentCode=residential')
    if isinstance(filt,dict):
        fv=filt.get('filterValuesApiResponseModel') or {}
        print('AIRPORTS',[(x.get('id'),x.get('name')) for g in fv.get('airports',[]) for x in g.get('children',[]) if x.get('id') in [3850,4380,4381]])
        print('CHILD_AGES',[(x.get('value'),x.get('name')) for x in (((fv.get('rooms') or {}).get('roomTemplate') or {}).get('childAges') or []) if x.get('value') in [5,7]])
        print('FILTER_VALUE_KEYS',sorted(fv.keys()))
        for key,val in fv.items():
            lk=str(key).lower()
            if any(tok in lk for tok in ['dest','country','region','location','place','geo']):
                try:
                    print('DEST_STRUCTURE',key,json.dumps(val,ensure_ascii=False)[:30000])
                except Exception:
                    print('DEST_STRUCTURE',key,repr(val)[:30000])
    common={'ac1':'2','kc1':'2','ka1':'5|7','dd':dd.isoformat(),'tt':'1','sc':'residential','ds':'0','er':'0','isss':'0','ilm':'0','ifm':'0'}
    q1=common|{'rd':(today+timedelta(days=3)).isoformat(),'nn':'5|6|7|8','to':'3850|4380|4381'}
    n,_=run_query('WATCHER_WINDOW',q1)
    q2=common|{'rd':(today+timedelta(days=180)).isoformat(),'nn':'7|10'}
    if not n:n,_=run_query('BROAD_CATEGORIES',q2)
    # EXIM returns destination categories without individual tours until a destination
    # is selected. Use a concrete high-inventory destination only to validate the
    # exact-family response schema; watcher production filters remain unchanged.
    if not n:
        q3=q2|{'d':'64419|64420|64425'}
        n,j=run_query('EGYPT_EXACT_FAMILY_SCHEMA',q3)
        if n and isinstance(j,dict):
            print('EXIM_EXACT_FAMILY_SCHEMA_VERIFIED',True)
    print('EXIM_ANY_EXACT_FAMILY_TOURS',bool(n))
if __name__=='__main__':main()
