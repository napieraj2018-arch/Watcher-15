import json,requests
GQL="https://app.primaholiday.pl/graphql"
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}

def gql(q,v,op):
    r=requests.post(GQL,json={"operationName":op,"variables":v,"query":q},headers=H,timeout=40)
    print("PRIMAFLIGHT_STATUS",op,r.status_code,len(r.content))
    print("PRIMAFLIGHT_HEAD",op,r.text[:24000].replace("\n"," "))
    r.raise_for_status()
    return r.json()

def value(x):
    if isinstance(x,str):
        try:return json.loads(x)
        except:return x
    return x

def walk(x,path="",depth=0,out=None):
    if out is None:out=[]
    if depth>10 or len(out)>500:return out
    if isinstance(x,dict):
        sig={k:v for k,v in x.items() if any(t in k.lower() for t in ["trip","offer","price","total","room","departure","arrival","airport","date","meal","maint","avail","adult","child","age","person","transport","hotel"])}
        if sig:out.append((path,sig))
        for k,v in x.items():walk(v,f"{path}.{k}" if path else k,depth+1,out)
    elif isinstance(x,list):
        for i,v in enumerate(x[:120]):walk(v,f"{path}[{i}]",depth+1,out)
    return out

def main():
    raw=value((gql("query R{bluevendoSearch}",{},"R").get("data") or {}).get("bluevendoSearch")) or {}
    items=((raw.get("items") or {}).get("item") or []) if isinstance(raw,dict) else []
    if isinstance(items,dict):items=[items]
    flights=[]
    for item in items:
        ats=(item.get("availabletransporttypes") or {}).get("availabletransporttype") or []
        if isinstance(ats,dict):ats=[ats]
        for t in ats:
            if str(t.get("transporttypeid"))=="1" and t.get("offerid"):
                flights.append({"offerid":str(t["offerid"]),"mintripid":str(t.get("mintripid") or ""),"hotel":item.get("hotelname"),"standard":item.get("standard")})
    print("PRIMAFLIGHT_ALT_COUNT",len(flights))
    print("PRIMAFLIGHT_ALTS",json.dumps(flights[:30],ensure_ascii=False))

    oq="query O($id:ID!){bluevendoOffer(id:$id)}"
    for f in flights[:12]:
        d=gql(oq,{"id":f["offerid"]},"O")
        v=value((d.get("data") or {}).get("bluevendoOffer"))
        print("PRIMAFLIGHT_OFFER",f["offerid"],json.dumps(v,ensure_ascii=False)[:30000])
        for p,s in walk(v)[:160]:print("PRIMAFLIGHT_SIGNAL",f["offerid"],p,json.dumps(s,ensure_ascii=False)[:5000])

    tq='''query TypeNames { __schema { types { name kind } } }'''
    td=gql(tq,{},"TypeNames")
    types=(((td.get("data") or {}).get("__schema") or {}).get("types") or [])
    for t in types:
        n=t.get("name") or ""
        if any(k in n.lower() for k in ["person","roomconfig","tripcalc","price","transport"]):
            print("PRIMAFLIGHT_TYPE_NAME",json.dumps(t,ensure_ascii=False))
if __name__=="__main__":main()
