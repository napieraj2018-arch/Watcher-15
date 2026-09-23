import json,requests
from datetime import datetime
from zoneinfo import ZoneInfo
GQL="https://app.primaholiday.pl/graphql"
TZ=ZoneInfo("Europe/Warsaw")
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}
QO="query O($id:ID!){bluevendoOffer(id:$id)}"
QT="""query T($tripid:ID!,$departureid:ID!,$arrivalid:ID!,$configuration:RoomConfiguration!){
 bluevendoTermPrice(tripid:$tripid,departureid:$departureid,arrivalid:$arrivalid,configuration:$configuration){
  lowestPrice fullResponse
 }
}"""

def gql(q,v,op):
 r=requests.post(GQL,json={"operationName":op,"variables":v,"query":q},headers=H,timeout=45)
 print("PRIMATERM_STATUS",op,r.status_code,len(r.content))
 print("PRIMATERM_HEAD",op,r.text[:12000].replace("\n"," "))
 r.raise_for_status();return r.json()

def val(v):
 if isinstance(v,str):
  try:return json.loads(v)
  except:return v
 return v

def signal(x,path="",depth=0,out=None):
 if out is None:out=[]
 if depth>10 or len(out)>300:return out
 if isinstance(x,dict):
  small={}
  for k,v in x.items():
   lo=str(k).lower()
   if any(t in lo for t in ["price","total","person","adult","child","birth","avail","room","trip","currency"]) and (isinstance(v,(str,int,float,bool)) or v is None):
    small[k]=v
  if small:out.append((path,small))
  for k,v in x.items():signal(v,f"{path}.{k}" if path else k,depth+1,out)
 elif isinstance(x,list):
  for i,v in enumerate(x[:80]):signal(v,f"{path}[{i}]",depth+1,out)
 return out

def term(t,birthdates,label):
 cfg={"roomid":str(t["roomid"]),"persons":[{"birthdate":d} for d in birthdates],"optionalComponentIds":[]}
 v={"tripid":str(t["id"]),"departureid":str(t["departureid"]),"arrivalid":str(t["arrivalid"]),"configuration":cfg}
 d=gql(QT,v,label)
 row=(d.get("data") or {}).get("bluevendoTermPrice")
 print("PRIMATERM_ROW",label,json.dumps(row,ensure_ascii=False)[:30000])
 fr=val((row or {}).get("fullResponse")) if isinstance(row,dict) else None
 for p,s in signal(fr)[:160]:print("PRIMATERM_SIGNAL",label,p,json.dumps(s,ensure_ascii=False)[:3500])
 return row,fr

def price_candidates(x):
 vals=[]
 def walk(v,path="",depth=0):
  if depth>10:return
  if isinstance(v,dict):
   for k,z in v.items():
    lo=str(k).lower()
    if any(t in lo for t in ["totalprice","customertotalprice","total_price","finalprice","final_price","price"]):
     try:
      n=float(str(z).replace(",","."))
      if n>0:vals.append((path+"."+str(k),n))
     except:pass
    walk(z,path+"."+str(k),depth+1)
  elif isinstance(v,list):
   for i,z in enumerate(v[:100]):walk(z,f"{path}[{i}]",depth+1)
 walk(x)
 return vals

def main():
 # Known current flight offers from bluevendoSearch alternates.
 offers=["275248","296508","333745","333721","319949","303203","290579","303248"]
 today=datetime.now(TZ).date()
 proofs=[]
 for oid in offers:
  d=gql(QO,{"id":oid},"O")
  ov=val((d.get("data") or {}).get("bluevendoOffer")) or {}
  trips=((ov.get("trips") or {}).get("trip") or []) if isinstance(ov,dict) else []
  if isinstance(trips,dict):trips=[trips]
  for t in trips:
   try:
    start=datetime.strptime(str(t.get("start")),"%Y-%m-%d").date()
    nights=int(t.get("length") or 0);mr=int(t.get("maxroom") or 0)
   except:continue
   if start<today or (start-today).days>45 or not 5<=nights<=8:continue
   if str(t.get("transporttypeid"))!="1" or str(t.get("onrequest")).lower() not in ("false","f","0") or mr<1:continue
   if not any(k in str(t.get("departurecityname") or "").lower() for k in ["warsz","radom","modlin"]):continue
   fam,ff=term(t,["1990-01-01","1990-01-01","2021-01-01","2019-01-01"],"FAMILY")
   ad,af=term(t,["1990-01-01","1990-01-01"],"ADULTS")
   fpc=price_candidates(ff);apc=price_candidates(af)
   print("PRIMATERM_PRICE_CANDIDATES",oid,t["id"],"FAMILY",json.dumps(fpc[:80],ensure_ascii=False))
   print("PRIMATERM_PRICE_CANDIDATES",oid,t["id"],"ADULTS",json.dumps(apc[:80],ensure_ascii=False))
   proof={"offerid":oid,"tripid":str(t["id"]),"start":str(t["start"]),"end":str(t["end"]),
      "nights":nights,"airport":t.get("departurecityname"),"roomid":str(t.get("roomid")),
      "meal":t.get("maintenancestandardname"),"maxroom":mr,
      "family_lowest":(fam or {}).get("lowestPrice") if isinstance(fam,dict) else None,
      "adults_lowest":(ad or {}).get("lowestPrice") if isinstance(ad,dict) else None,
      "family_prices":fpc[:20],"adult_prices":apc[:20]}
   print("PRIMATERM_COMPARE",json.dumps(proof,ensure_ascii=False))
   proofs.append(proof)
   if len(proofs)>=3:break
  if len(proofs)>=3:break
 print("PRIMATERM_EXACT_CHILD_DOBS",["2021-01-01","2019-01-01"])
 print("PRIMATERM_LIVE_COMPARE_COUNT",len(proofs))
if __name__=="__main__":main()
