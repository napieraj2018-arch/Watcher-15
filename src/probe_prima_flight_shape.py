import json, requests
GQL="https://app.primaholiday.pl/graphql"
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}

def gql(q,v=None,op=None):
    r=requests.post(GQL,json={"operationName":op,"variables":v or {},"query":q},headers=H,timeout=40)
    print("PRIMASHAPE_STATUS",op,r.status_code,len(r.content))
    r.raise_for_status(); return r.json()

def val(v):
    if isinstance(v,str):
        try:return json.loads(v)
        except:return v
    return v

def compact_nodes(x,path="",depth=0,out=None):
    if out is None: out=[]
    if depth>10 or len(out)>500:return out
    if isinstance(x,dict):
        keys=[str(k) for k in x.keys()]
        lk=" ".join(keys).lower()
        if any(t in lk for t in ["trip","room","date","start","end","departure","arrival","transport","price","avail","meal","maint","hotel","offer"]):
            small={}
            for k,v in x.items():
                if isinstance(v,(str,int,float,bool)) or v is None:
                    small[k]=v
            out.append((path,keys,small))
        for k,v in x.items(): compact_nodes(v,f"{path}.{k}" if path else str(k),depth+1,out)
    elif isinstance(x,list):
        for i,v in enumerate(x[:80]): compact_nodes(v,f"{path}[{i}]",depth+1,out)
    return out

CALC="""query C($persons:[PersonsGroupInput!]!,$trips:[TripInput!]!){
 bluevendoFastCalculation(persons:$persons,trips:$trips){trips{price tripId lowestPrice persons{totalPrice}}}
}"""

def calc(tripid,ages):
    v={"persons":[{"person":[{"age":a} for a in ages]}],"trips":[{"tripid":int(tripid),"departureid":0,"arrivalid":0}]}
    d=gql(CALC,v,"C")
    rows=(((d.get("data") or {}).get("bluevendoFastCalculation") or {}).get("trips") or [])
    if not isinstance(rows,list):rows=[rows] if rows else []
    return rows[0] if rows else None

def main():
    raw=val((gql("query R{bluevendoSearch}",op="R").get("data") or {}).get("bluevendoSearch")) or {}
    items=((raw.get("items") or {}).get("item") or []) if isinstance(raw,dict) else []
    if isinstance(items,dict):items=[items]
    flights=[]
    for item in items:
        ats=(item.get("availabletransporttypes") or {}).get("availabletransporttype") or []
        if isinstance(ats,dict):ats=[ats]
        for t in ats:
            if str(t.get("transporttypeid"))=="1" and t.get("mintripid"):
                flights.append({
                  "offerid":str(t.get("offerid") or ""),
                  "mintripid":str(t.get("mintripid")),
                  "hotel":item.get("hotelname"),"hotelid":item.get("hotelid"),
                  "item_start":item.get("minstartdate"),"item_end":item.get("maxstartdate"),
                  "item_room":(item.get("mintrip") or {}).get("roomid") if isinstance(item.get("mintrip"),dict) else None,
                  "item_mintrip":item.get("mintrip")
                })
    print("PRIMASHAPE_FLIGHT_COUNT",len(flights))
    for f in flights[:12]:
        fam=calc(f["mintripid"],[18,18,5,7]); adults=calc(f["mintripid"],[18,18])
        print("PRIMASHAPE_FLIGHT",json.dumps({**{k:v for k,v in f.items() if k!="item_mintrip"},"family":fam,"adults":adults},ensure_ascii=False))
        if f["offerid"]:
            d=gql("query O($id:ID!){bluevendoOffer(id:$id)}",{"id":f["offerid"]},"O")
            ov=val((d.get("data") or {}).get("bluevendoOffer"))
            print("PRIMASHAPE_OFFER_TOP",f["offerid"],type(ov).__name__,json.dumps(list(ov.keys()) if isinstance(ov,dict) else [],ensure_ascii=False))
            for path,keys,small in compact_nodes(ov)[:120]:
                print("PRIMASHAPE_NODE",f["offerid"],path,json.dumps({"keys":keys,"scalar":small},ensure_ascii=False)[:3500])

if __name__=="__main__":main()
